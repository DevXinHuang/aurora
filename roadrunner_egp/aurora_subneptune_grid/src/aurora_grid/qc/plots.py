from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from . import EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE, QCResult, SEVERITY_ORDER
from .schema_checks import array_values, manifest_row
from .science_checks import FNET_IRFNET_THRESHOLD


SCHEMA_QC_CHECKS = {"schema"}
PT_SPECTRUM_CLOUD_QC_CHECKS = {"spectrum", "climate", "chemistry", "cloud"}
EXACT_PICASO_CLIMATE_QC_CHECKS = {"picaso_diagnostics", "adiabat", "flux_balance", "brightness_temperature"}


def _matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _plot_pt(ax, ds: xr.Dataset) -> bool:
    pressure = array_values(ds, "pressure")
    temperature = array_values(ds, "temperature")
    if pressure is None or temperature is None:
        ax.text(0.5, 0.5, "PT unavailable", ha="center", va="center")
        return False
    ax.plot(temperature, pressure)
    ax.set_xlabel("Temperature [K]")
    ax.set_ylabel("Pressure [bar]")
    ax.set_yscale("log")
    ax.invert_yaxis()
    return True


def _pressure_for_values(ds: xr.Dataset, values: np.ndarray) -> np.ndarray | None:
    for name in ("pressure", "layer_pressure_bar", "qc_adiabat_pressure"):
        pressure = array_values(ds, name)
        if pressure is not None and pressure.size == values.size:
            return np.ravel(pressure)
    return None


def _plot_adiabat(ax, ds: xr.Dataset) -> bool:
    adiabat = array_values(ds, "qc_adiabat")
    dtdp = array_values(ds, "qc_dtdp")
    if adiabat is None or dtdp is None:
        _show_exact_diagnostics_unavailable(ax)
        return False
    adiabat = np.ravel(adiabat)
    dtdp = np.ravel(dtdp)
    if adiabat.size != dtdp.size:
        _show_exact_diagnostics_unavailable(ax)
        return False
    layers = np.arange(1, adiabat.size + 1)
    ax.plot(dtdp, layers, color="blue", label="model dTdp")
    ax.plot(adiabat, layers, color="red", label="adiabat")
    ax.axvline(0.0, color="0.5", linewidth=0.6, linestyle="--")
    ax.set_xlabel("dT/dp")
    ax.set_ylabel("layer number")
    ax.legend(fontsize=8)
    ax.invert_yaxis()
    return True


def _plot_flux_balance(ax, ds: xr.Dataset) -> bool:
    for flux_name in ("fnet_irfnet", "Fnet_IRFnet", "Fnet/IR-Fnet"):
        flux = array_values(ds, flux_name)
        if flux is not None:
            break
    else:
        flux = None
    if flux is None:
        _show_exact_diagnostics_unavailable(ax)
        return False
    flux = np.ravel(flux)
    pressure = _pressure_for_values(ds, flux)
    if pressure is None:
        _show_exact_diagnostics_unavailable(ax)
        return False
    x = np.where(np.abs(flux) > 0.0, np.abs(flux), np.nan)
    finite = np.isfinite(x) & np.isfinite(pressure) & (x > 0.0) & (pressure > 0.0)
    if not np.any(finite):
        _show_exact_diagnostics_unavailable(ax)
        return False
    ax.loglog(x[finite], pressure[finite], color="deeppink", linewidth=1.2)
    ax.axvline(FNET_IRFNET_THRESHOLD, color="cyan", linewidth=1.0, linestyle="--", label=f"threshold {FNET_IRFNET_THRESHOLD:.0e}")
    ax.set_xlabel("|Fnet / IR-Fnet|")
    ax.set_ylabel("Pressure [bar]")
    ax.legend(fontsize=8)
    ax.invert_yaxis()
    return True


def _plot_brightness_temperature(ax, ds: xr.Dataset) -> bool:
    brightness = array_values(ds, "qc_brightness_temperature")
    brightness_wavelength = array_values(ds, "qc_brightness_wavelength")
    if brightness is None or brightness_wavelength is None or brightness.size != brightness_wavelength.size:
        _show_exact_diagnostics_unavailable(ax)
        return False
    brightness = np.ravel(brightness)
    brightness_wavelength = np.ravel(brightness_wavelength)
    finite = np.isfinite(brightness) & np.isfinite(brightness_wavelength) & (brightness_wavelength > 0.0)
    if not np.any(finite):
        _show_exact_diagnostics_unavailable(ax)
        return False
    ax.semilogx(brightness_wavelength[finite], brightness[finite], color="purple", linewidth=1.2)
    ax.set_xscale("log")
    temperature = array_values(ds, "temperature_k")
    if temperature is None:
        temperature = array_values(ds, "temperature")
    if temperature is not None and temperature.size:
        bottom_temperature = float(np.ravel(temperature)[-1])
        ax.axhline(bottom_temperature, color="black", linewidth=1.0, linestyle="--", label=f"T_bottom = {bottom_temperature:.0f} K")
        ax.legend(fontsize=8)
    ax.set_xlabel("Wavelength [um]")
    ax.set_ylabel("Brightness Temperature [K]")
    ax.invert_yaxis()
    return True


def _show_exact_diagnostics_unavailable(ax) -> None:
    ax.text(
        0.5,
        0.5,
        EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE,
        ha="center",
        va="center",
        fontsize=8,
        wrap=True,
        transform=ax.transAxes,
    )
    ax.set_xticks([])
    ax.set_yticks([])


def _category_status(qc_result: QCResult, checks: set[str]) -> str:
    severities = [flag.severity for flag in qc_result.flags if flag.check in checks]
    if not severities:
        return "pass"
    return max(severities, key=lambda severity: SEVERITY_ORDER.get(severity, 0))


def _exact_picaso_status(qc_result: QCResult) -> str:
    for flag in qc_result.flags:
        if flag.check == "picaso_diagnostics" and flag.message == EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE:
            return "unavailable"
    return _category_status(qc_result, EXACT_PICASO_CLIMATE_QC_CHECKS)


def _format_number(value: object, fmt: str = ".3g", default: str = "?") -> str:
    try:
        return format(float(value), fmt)
    except Exception:
        return default


def _diagnostic_title(ds: xr.Dataset, qc_result: QCResult) -> str:
    row = manifest_row(ds)
    category_line = (
        f"Schema QC: {_category_status(qc_result, SCHEMA_QC_CHECKS)} | "
        f"PT/spectrum/cloud QC: {_category_status(qc_result, PT_SPECTRUM_CLOUD_QC_CHECKS)} | "
        f"Exact PICASO climate diagnostics: {_exact_picaso_status(qc_result)}"
    )
    parts = [
        f"T_eq={_format_number(row.get('equilibrium_temperature_k'), '.0f')}K",
        f"g={_format_number(row.get('gravity_ms2'), '.3g')} m/s2",
        f"fsed={_format_number(row.get('fsed'), '.3g')}",
        f"metallicity={_format_number(row.get('metallicity_xsolar'), '.3g')}x",
        f"C/O={_format_number(row.get('c_to_o_xsolar'), '.3g')}x",
        f"cloud={_format_number(row.get('cloud_fraction'), '.3g')}",
        f"phase={_format_number(row.get('phase_deg'), '.3g')} deg",
    ]
    flagged = [flag.message for flag in qc_result.flags if flag.severity in {"warning", "fail", "rerun_recommended"}]
    subtitle = " | ".join(flagged[:4])
    if len(flagged) > 4:
        subtitle += f" | +{len(flagged) - 4} more"
    detail_line = f"! {subtitle}" if subtitle else qc_result.status
    return f"{category_line}\n" + "  ".join(parts) + f"\n{detail_line}"


def make_qc_plot(ds: xr.Dataset, qc_result: QCResult, out_png: Path | str) -> Path:
    plt = _matplotlib()
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(12, 10), constrained_layout=True)
    ax = axes.ravel()

    _plot_adiabat(ax[0], ds)
    ax[0].set_title("Exact PICASO Climate: dT/dp vs Adiabat")

    _plot_pt(ax[1], ds)
    ax[1].set_title("PT/Spectrum/Cloud QC: PT Profile")

    _plot_flux_balance(ax[2], ds)
    ax[2].set_title("Exact PICASO Climate: Fnet / IR-Fnet")

    _plot_brightness_temperature(ax[3], ds)
    ax[3].set_title("Exact PICASO Climate: IR Brightness Temperature")

    fig.suptitle(_diagnostic_title(ds, qc_result), fontsize=9, wrap=True)
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    return out_png


def make_spectrum_plot(ds: xr.Dataset, qc_result: QCResult, out_png: Path | str) -> Path:
    plt = _matplotlib()
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    wavelength = array_values(ds, "wavelength")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    panels = [
        ("geometric_albedo", "Albedo"),
        ("reflected_planet_star_flux_ratio", "Reflected Fp/Fs"),
        ("thermal_planet_star_flux_ratio", "Emission Fp/Fs"),
        ("total_planet_star_flux_ratio", "Total Fp/Fs"),
    ]
    for ax, (name, title) in zip(axes.ravel(), panels, strict=False):
        values = array_values(ds, name)
        if wavelength is not None and values is not None and values.size == wavelength.size:
            ax.plot(wavelength, values)
            ax.set_xlabel("Wavelength [um]")
        elif values is not None:
            ax.plot(np.ravel(values))
            ax.set_xlabel("Sample")
        else:
            ax.text(0.5, 0.5, f"{name} unavailable", ha="center", va="center")
        ax.set_title(title)
    fig.suptitle(f"{qc_result.run_id or Path(qc_result.file_path).stem}: PT/spectrum/cloud QC spectrum")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    return out_png


def failed_check_names(qc_result: QCResult) -> list[str]:
    names = [flag.check for flag in qc_result.flags if flag.severity in {"warning", "fail", "rerun_recommended"}]
    return sorted(set(names)) or ["schema"]
