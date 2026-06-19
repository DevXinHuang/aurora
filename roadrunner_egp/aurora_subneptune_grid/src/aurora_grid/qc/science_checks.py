from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from . import QCFlag
from .schema_checks import array_values, has_pressure, pressure_dependent_vars


ADIABAT_RATIO_THRESHOLD = 1.05
FNET_IRFNET_THRESHOLD = 1.0e-3
FNET_UPPER_PRESSURE_BAR = 1.0e-2
BRIGHTNESS_BOTTOM_FRACTION = 0.99


def _mostly_between(values: np.ndarray, lo: float, hi: float, tolerance: float = 1.0e-8, fraction: float = 0.95) -> bool:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return False
    in_range = (finite >= lo - tolerance) & (finite <= hi + tolerance)
    return float(np.count_nonzero(in_range)) / float(finite.size) >= fraction


def _not_flat(values: np.ndarray, rtol: float = 1.0e-8, atol: float = 1.0e-14) -> bool:
    finite = values[np.isfinite(values)]
    if finite.size < 2:
        return False
    return not bool(np.allclose(finite, finite[0], rtol=rtol, atol=atol))


def _pressure_for_values(ds: xr.Dataset, values: np.ndarray) -> np.ndarray | None:
    for name in ("pressure", "layer_pressure_bar", "qc_adiabat_pressure"):
        pressure = array_values(ds, name)
        if pressure is not None and pressure.size == values.size:
            return np.ravel(pressure)
    return None


def _check_spectrum(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    wavelength = array_values(ds, "wavelength")
    if wavelength is not None and not np.all(np.isfinite(wavelength)):
        flags.append(QCFlag("spectrum", "fail", "wavelength contains nonfinite values"))

    for name in ("geometric_albedo", "reflected_planet_star_flux_ratio"):
        values = array_values(ds, name)
        if values is None:
            continue
        if not np.all(np.isfinite(values)):
            flags.append(QCFlag("spectrum", "fail", f"{name} contains nonfinite values"))
        finite = values[np.isfinite(values)]
        if finite.size and np.all(np.abs(finite) <= 1.0e-300):
            flags.append(QCFlag("spectrum", "fail", f"{name} is all zeros"))
        if finite.size and not _not_flat(finite):
            flags.append(QCFlag("spectrum", "warning", f"{name} is completely flat"))

    albedo = array_values(ds, "geometric_albedo")
    if albedo is not None and not _mostly_between(albedo, 0.0, 1.0, tolerance=1.0e-6):
        flags.append(QCFlag("spectrum", "warning", "albedo mostly outside [0, 1]"))

    reflected_name = "reflected_planet_star_flux_ratio"
    reflected = array_values(ds, reflected_name)
    if reflected is not None:
        finite = reflected[np.isfinite(reflected)]
        if finite.size and float(np.nanmin(finite)) < -1.0e-14:
            flags.append(QCFlag("spectrum", "fail", f"{reflected_name} has significant negative values"))


def _check_pt(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    if not has_pressure(ds):
        return
    pressure = array_values(ds, "pressure")
    temperature = array_values(ds, "temperature")
    if pressure is None or temperature is None:
        flags.append(QCFlag("climate", "warning", "pressure or temperature is not numeric"))
        return
    if pressure.ndim != 1 or temperature.ndim != 1:
        flags.append(QCFlag("climate", "warning", "pressure or temperature is not 1D"))
        return
    if pressure.size != temperature.size:
        flags.append(QCFlag("climate", "warning", "pressure and temperature sizes differ"))
        return
    if not np.all(np.isfinite(pressure)):
        flags.append(QCFlag("climate", "fail", "pressure contains nonfinite values"))
    if not np.all(pressure > 0):
        flags.append(QCFlag("climate", "fail", "nonpositive pressure values"))
    if not np.all(np.isfinite(temperature)):
        flags.append(QCFlag("climate", "fail", "temperature contains nonfinite values"))
    if not np.all(temperature > 0):
        flags.append(QCFlag("climate", "fail", "temperature contains nonpositive values"))
    if pressure.size > 1:
        diff = np.diff(pressure)
        if not (np.all(diff > 0) or np.all(diff < 0)):
            flags.append(QCFlag("climate", "fail", "pressure grid is not monotonic"))

    finite = np.isfinite(pressure) & np.isfinite(temperature) & (pressure > 0) & (temperature > 0)
    if np.count_nonzero(finite) < 3:
        return
    p = pressure[finite]
    t = temperature[finite]
    jumps = np.abs(np.diff(t))
    if jumps.size and float(np.nanmax(jumps)) > 1000.0:
        flags.append(QCFlag("climate", "warning", "temperature has absurd layer jump", "max_temperature_jump", float(np.nanmax(jumps))))
    logp = np.log10(p)
    dlogp = np.diff(logp)
    dt = np.diff(t)
    with np.errstate(divide="ignore", invalid="ignore"):
        slopes = np.abs(dt / dlogp)
    finite_slopes = slopes[np.isfinite(slopes)]
    if finite_slopes.size and float(np.nanmax(finite_slopes)) > 2000.0:
        flags.append(QCFlag("climate", "warning", "runaway dT/dlogP slope", "max_abs_dtdlogp", float(np.nanmax(finite_slopes))))
    flat_pressure = np.abs(dlogp) < 1.0e-8
    if np.any(flat_pressure & (np.abs(dt) > 10.0)):
        flags.append(QCFlag("climate", "fail", "flat pressure with large temperature jump"))


def _check_chemistry(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    for name in pressure_dependent_vars(ds):
        values = array_values(ds, name)
        if values is None:
            flags.append(QCFlag("chemistry", "warning", f"{name} chemistry is not numeric"))
            continue
        if not np.all(np.isfinite(values)):
            flags.append(QCFlag("chemistry", "fail", f"{name} chemistry contains nonfinite values"))
            continue
        if float(np.nanmin(values)) < -1.0e-30:
            flags.append(QCFlag("chemistry", "fail", f"{name} chemistry contains negative values"))
        if float(np.nanmax(values)) > 1.0 + 1.0e-6:
            flags.append(QCFlag("chemistry", "warning", f"{name} chemistry exceeds 1"))


def _check_clouds(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    checks = {
        "cloud_optical_depth": (0.0, np.inf, "fail"),
        "single_scattering_albedo": (0.0, 1.0, "warning"),
        "asymmetry_factor": (-1.0, 1.0, "warning"),
    }
    for name, (lo, hi, severity) in checks.items():
        values = array_values(ds, name)
        if values is None:
            continue
        if not np.all(np.isfinite(values)):
            flags.append(QCFlag("cloud", "fail", f"{name} contains nonfinite values"))
            continue
        if name == "cloud_optical_depth" and float(np.nanmin(values)) < -1.0e-12:
            flags.append(QCFlag("cloud", "fail", "cloud_optical_depth contains negative values"))
        elif name != "cloud_optical_depth" and not _mostly_between(values, float(lo), float(hi), tolerance=1.0e-6):
            flags.append(QCFlag("cloud", severity, f"{name} mostly outside [{lo}, {hi}]"))


def _check_exact_adiabat(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    adiabat = array_values(ds, "qc_adiabat")
    dtdp = array_values(ds, "qc_dtdp")
    if adiabat is None or dtdp is None or adiabat.size != dtdp.size:
        return
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = dtdp / adiabat
    finite = ratio[np.isfinite(ratio)]
    if finite.size == 0:
        return
    bad = finite > ADIABAT_RATIO_THRESHOLD
    if not np.any(bad):
        return
    max_ratio = float(np.nanmax(finite))
    n_bad = int(np.count_nonzero(bad))
    severity = "warning" if n_bad <= 2 and max_ratio <= 1.2 else "rerun_recommended"
    flags.append(
        QCFlag(
            "adiabat",
            severity,
            f"Adiabat violated at {n_bad} layer(s) (max dTdp/dTdp_ad = {max_ratio:.3f})",
            "max_adiabat_ratio",
            max_ratio,
        )
    )


def _check_exact_flux_balance(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    fnet = array_values(ds, "fnet_irfnet")
    if fnet is None:
        return
    fnet = np.ravel(fnet)
    pressure = _pressure_for_values(ds, fnet)
    if pressure is None:
        return
    mask = np.isfinite(fnet) & np.isfinite(pressure) & (pressure < FNET_UPPER_PRESSURE_BAR)
    bad = mask & (np.abs(fnet) > FNET_IRFNET_THRESHOLD)
    if not np.any(bad):
        return
    max_abs = float(np.nanmax(np.abs(fnet[bad])))
    n_bad = int(np.count_nonzero(bad))
    flags.append(
        QCFlag(
            "flux_balance",
            "warning",
            f"Fnet/IR-Fnet > {FNET_IRFNET_THRESHOLD:.0e} at {n_bad} upper-atmosphere layer(s) (p < {FNET_UPPER_PRESSURE_BAR:g} bar) (max = {max_abs:.2e})",
            "max_abs_fnet_irfnet",
            max_abs,
        )
    )


def _check_exact_brightness_temperature(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    brightness = array_values(ds, "qc_brightness_temperature")
    temperature = array_values(ds, "temperature")
    if brightness is None or temperature is None or temperature.size == 0:
        return
    finite = brightness[np.isfinite(brightness)]
    if finite.size == 0:
        return
    bottom_temperature = float(np.ravel(temperature)[-1])
    max_brightness = float(np.nanmax(finite))
    if max_brightness < BRIGHTNESS_BOTTOM_FRACTION * bottom_temperature:
        return
    flags.append(
        QCFlag(
            "brightness_temperature",
            "rerun_recommended",
            f"Brightness temperature reaches/exceeds bottom layer (T_bottom = {bottom_temperature:.1f} K, max Tbrt = {max_brightness:.1f} K). Need deeper grid.",
            "max_brightness_temperature",
            max_brightness,
        )
    )


def _check_exact_climate_diagnostics(ds: xr.Dataset, flags: list[QCFlag]) -> None:
    _check_exact_adiabat(ds, flags)
    _check_exact_flux_balance(ds, flags)
    _check_exact_brightness_temperature(ds, flags)


def validate_science(ds: xr.Dataset, row: dict[str, Any] | None = None) -> list[QCFlag]:
    flags: list[QCFlag] = []
    _check_spectrum(ds, flags)
    _check_pt(ds, flags)
    _check_chemistry(ds, flags)
    _check_clouds(ds, flags)
    _check_exact_climate_diagnostics(ds, flags)
    return flags
