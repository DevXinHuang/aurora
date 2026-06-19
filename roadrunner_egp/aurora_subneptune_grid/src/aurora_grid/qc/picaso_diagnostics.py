from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from . import QCFlag
from .schema_checks import array_values


def _add_1d(ds: xr.Dataset, name: str, values: Any, dim: str, units: str | None = None) -> xr.Dataset:
    if values is None:
        return ds
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        array = np.ravel(array)
    ds[name] = ((dim,), array)
    if units:
        ds[name].attrs["units"] = units
    return ds


def _parse_adiabat_result(result: Any) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    if result is None:
        return None, None, None
    if not isinstance(result, (tuple, list)):
        return None, None, None
    if len(result) >= 4:
        _, adiabat, dtdp, pressure = result[:4]
    elif len(result) >= 3:
        adiabat, dtdp, pressure = result[:3]
    else:
        return None, None, None
    return np.asarray(adiabat, dtype=float), np.asarray(dtdp, dtype=float), np.asarray(pressure, dtype=float)


def _brightness_wavelength(raw_output: dict[str, Any], brightness: np.ndarray) -> np.ndarray | None:
    spectrum = raw_output.get("spectrum_output") if isinstance(raw_output, dict) else None
    if isinstance(spectrum, dict) and "wavenumber" in spectrum:
        wno = np.asarray(spectrum["wavenumber"], dtype=float)
    elif isinstance(raw_output, dict) and "wavenumber" in raw_output:
        wno = np.asarray(raw_output["wavenumber"], dtype=float)
    else:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        wavelength = 1.0e4 / wno
    if wavelength.size != brightness.size:
        return None
    return wavelength


def run_picaso_diagnostics(
    raw_output: dict[str, Any] | None,
    case: Any,
    opacity: Any,
    ds: xr.Dataset,
    row: dict[str, Any] | None = None,
) -> tuple[xr.Dataset, list[QCFlag], dict[str, Any]]:
    flags: list[QCFlag] = []
    metrics: dict[str, Any] = {}
    if raw_output is None or case is None or opacity is None:
        flags.append(QCFlag("picaso_diagnostics", "info", "PICASO raw diagnostics unavailable"))
        return ds, flags, metrics

    try:
        from picaso import justplotit as jpi
    except Exception as exc:
        flags.append(QCFlag("picaso_diagnostics", "info", f"PICASO plotting diagnostics unavailable: {exc}"))
        return ds, flags, metrics

    pt_adiabat = getattr(jpi, "pt_adiabat", None)
    if pt_adiabat is not None:
        try:
            adiabat, dtdp, pressure = _parse_adiabat_result(pt_adiabat(raw_output, case, opacity, plot=False))
            if adiabat is not None and dtdp is not None and pressure is not None:
                ds = _add_1d(ds, "qc_adiabat", adiabat, "qc_adiabat_layer")
                ds = _add_1d(ds, "qc_dtdp", dtdp, "qc_adiabat_layer")
                ds = _add_1d(ds, "qc_adiabat_pressure", pressure, "qc_adiabat_layer", "bar")
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.asarray(dtdp, dtype=float) / np.asarray(adiabat, dtype=float)
                finite = ratio[np.isfinite(ratio)]
                if finite.size:
                    max_ratio = float(np.nanmax(finite))
                    n_violations = int(np.count_nonzero(finite > 1.05))
                    metrics["max_adiabat_ratio"] = max_ratio
                    metrics["n_adiabat_violations"] = n_violations
                    if n_violations > 0:
                        severity = "warning" if n_violations <= 2 and max_ratio <= 1.2 else "rerun_recommended"
                        flags.append(QCFlag("adiabat", severity, "adiabat violation", "max_adiabat_ratio", max_ratio))
        except Exception as exc:
            flags.append(QCFlag("adiabat", "info", f"adiabat diagnostic unavailable: {exc}"))
    else:
        flags.append(QCFlag("adiabat", "info", "pt_adiabat unavailable"))

    brightness_temperature = getattr(jpi, "brightness_temperature", None)
    if brightness_temperature is not None and isinstance(raw_output, dict) and "spectrum_output" in raw_output:
        try:
            brightness = np.asarray(brightness_temperature(raw_output["spectrum_output"], plot=False), dtype=float)
            wavelength = _brightness_wavelength(raw_output, brightness)
            if wavelength is not None:
                order = np.argsort(wavelength)
                wavelength = wavelength[order]
                brightness = brightness[order]
                ds.coords["qc_brightness_wavelength_um"] = (
                    ("brightness_wavelength_um",),
                    wavelength,
                    {"units": "um"},
                )
                ds = _add_1d(ds, "qc_brightness_temperature", brightness, "brightness_wavelength_um", "K")
                ds = _add_1d(ds, "qc_brightness_wavelength", wavelength, "brightness_wavelength_um", "um")
            finite = brightness[np.isfinite(brightness)]
            if finite.size:
                max_tb = float(np.nanmax(finite))
                metrics["max_brightness_temperature"] = max_tb
                temperature = array_values(ds, "temperature")
                if temperature is not None and temperature.size:
                    bottom_temperature = float(np.ravel(temperature)[-1])
                    metrics["bottom_temperature"] = bottom_temperature
                    if max_tb >= 0.99 * bottom_temperature:
                        flags.append(QCFlag("brightness_temperature", "rerun_recommended", "brightness temperature reaches bottom layer", "max_brightness_temperature", max_tb))
        except Exception as exc:
            flags.append(QCFlag("brightness_temperature", "info", f"brightness diagnostic unavailable: {exc}"))
    else:
        flags.append(QCFlag("brightness_temperature", "info", "brightness diagnostic unavailable or reflected-only run"))

    for flux_name in ("Fnet_IRFnet", "fnet_irfnet", "Fnet/IR-Fnet"):
        if flux_name not in ds:
            continue
        values = array_values(ds, flux_name)
        pressure = array_values(ds, "pressure")
        if values is None:
            continue
        mask = np.isfinite(values)
        if pressure is not None and pressure.size == values.size:
            mask &= pressure < 0.01
        finite = np.abs(values[mask])
        if finite.size:
            max_abs = float(np.nanmax(finite))
            metrics["max_abs_fnet_irfnet"] = max_abs
            if max_abs > 1.0e-3:
                flags.append(QCFlag("flux_balance", "warning", "Fnet/IR-Fnet flux-balance issue", "max_abs_fnet_irfnet", max_abs))
        break
    else:
        flags.append(QCFlag("flux_balance", "info", "flux balance fields unavailable"))

    ds.attrs.update({key: value for key, value in metrics.items() if isinstance(value, (int, float, str))})
    return ds, flags, metrics
