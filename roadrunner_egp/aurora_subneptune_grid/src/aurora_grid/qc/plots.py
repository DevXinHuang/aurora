from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from . import QCResult
from .schema_checks import array_values


def _matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _plot_pt(ax, ds: xr.Dataset) -> None:
    pressure = array_values(ds, "pressure")
    temperature = array_values(ds, "temperature")
    if pressure is None or temperature is None:
        ax.text(0.5, 0.5, "PT unavailable", ha="center", va="center")
        return
    ax.plot(temperature, pressure)
    ax.set_xlabel("Temperature [K]")
    ax.set_ylabel("Pressure [bar]")
    ax.set_yscale("log")
    ax.invert_yaxis()


def make_qc_plot(ds: xr.Dataset, qc_result: QCResult, out_png: Path | str) -> Path:
    plt = _matplotlib()
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    ax = axes.ravel()

    adiabat = array_values(ds, "qc_adiabat")
    dtdp = array_values(ds, "qc_dtdp")
    adiabat_pressure = array_values(ds, "qc_adiabat_pressure")
    if adiabat is not None and dtdp is not None:
        x = np.arange(adiabat.size) if adiabat_pressure is None else adiabat_pressure
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = dtdp / adiabat
        ax[0].plot(ratio, x)
        ax[0].axvline(1.05, color="crimson", linewidth=1)
        ax[0].set_xlabel("dT/dP / adiabat")
        ax[0].set_ylabel("Pressure [bar]" if adiabat_pressure is not None else "Layer")
        if adiabat_pressure is not None and np.all(adiabat_pressure > 0):
            ax[0].set_yscale("log")
            ax[0].invert_yaxis()
    else:
        ax[0].text(0.5, 0.5, "Adiabat unavailable", ha="center", va="center")
    ax[0].set_title("Adiabatic Slope")

    _plot_pt(ax[1], ds)
    ax[1].set_title("PT Profile")

    flux_name = "Fnet_IRFnet" if "Fnet_IRFnet" in ds else "fnet_irfnet"
    flux = array_values(ds, flux_name)
    pressure = array_values(ds, "pressure")
    if flux is not None:
        x = np.ravel(flux)
        y = np.arange(x.size) if pressure is None or pressure.size != x.size else pressure
        ax[2].plot(x, y)
        ax[2].axvline(1.0e-3, color="crimson", linewidth=1)
        ax[2].axvline(-1.0e-3, color="crimson", linewidth=1)
        ax[2].set_xlabel("Fnet / IR-Fnet")
        ax[2].set_ylabel("Pressure [bar]" if pressure is not None and pressure.size == x.size else "Layer")
        if pressure is not None and pressure.size == x.size and np.all(pressure > 0):
            ax[2].set_yscale("log")
            ax[2].invert_yaxis()
    else:
        ax[2].text(0.5, 0.5, "Flux balance unavailable", ha="center", va="center")
    ax[2].set_title("Flux Balance")

    brightness = array_values(ds, "qc_brightness_temperature")
    brightness_wavelength = array_values(ds, "qc_brightness_wavelength")
    if brightness is not None:
        x = np.arange(brightness.size) if brightness_wavelength is None else brightness_wavelength
        ax[3].plot(x, brightness)
        ax[3].set_xlabel("Wavelength [micron]" if brightness_wavelength is not None else "Sample")
        ax[3].set_ylabel("Brightness T [K]")
    else:
        ax[3].text(0.5, 0.5, "Brightness T unavailable", ha="center", va="center")
    ax[3].set_title("Brightness Temperature")

    fig.suptitle(f"{qc_result.run_id or Path(qc_result.file_path).stem}: {qc_result.status}")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    return out_png


def make_spectrum_plot(ds: xr.Dataset, qc_result: QCResult, out_png: Path | str) -> Path:
    plt = _matplotlib()
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    wavelength = array_values(ds, "wavelength")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    panels = [
        ("albedo", "Albedo"),
        ("fpfs_reflected" if "fpfs_reflected" in ds else "fpfs_reflection", "Reflected Fp/Fs"),
        ("fpfs_emission", "Emission Fp/Fs"),
        ("aurora_reflected_fraction", "Reflected Fraction"),
    ]
    for ax, (name, title) in zip(axes.ravel(), panels, strict=False):
        values = array_values(ds, name)
        if wavelength is not None and values is not None and values.size == wavelength.size:
            ax.plot(wavelength, values)
            ax.set_xlabel("Wavelength [micron]")
        elif values is not None:
            ax.plot(np.ravel(values))
            ax.set_xlabel("Sample")
        else:
            ax.text(0.5, 0.5, f"{name} unavailable", ha="center", va="center")
        ax.set_title(title)
    fig.suptitle(f"{qc_result.run_id or Path(qc_result.file_path).stem}: spectrum")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    return out_png


def failed_check_names(qc_result: QCResult) -> list[str]:
    names = [flag.check for flag in qc_result.flags if flag.severity in {"warning", "fail", "rerun_recommended"}]
    return sorted(set(names)) or ["schema"]
