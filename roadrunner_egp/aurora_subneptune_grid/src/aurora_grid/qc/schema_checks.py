from __future__ import annotations

import json
from typing import Any

import numpy as np
import xarray as xr

from aurora_grid.io.netcdf_schema import validate_aurora_netcdf_schema

from . import QCFlag


REQUIRED_ATTRS = [
    "author",
    "contact",
    "code",
    "model_name",
    "run_id",
    "run_index",
    "created_utc",
    "git_commit",
    "planet_params",
    "stellar_params",
    "orbit_params",
    "cld_params",
    "grid_params",
]

ESSENTIAL_SPECTRAL_VARS = ("geometric_albedo", "reflected_planet_star_flux_ratio")
KNOWN_NON_CHEMISTRY = {
    "geometric_albedo",
    "reflected_planet_star_flux_ratio",
    "reflected_flux",
    "thermal_flux",
    "pressure_bar",
    "temperature_k",
    "mole_fraction",
    "layer_pressure_bar",
    "layer_temperature_k",
    "cloud_optical_depth",
    "single_scattering_albedo",
    "asymmetry_factor",
    "fpfs_emission",
    "flux_emission",
    "aurora_reflected_fraction",
    "aurora_flux_reflected",
    "temperature",
    "opd",
    "ssa",
    "asy",
    "qc_adiabat",
    "qc_dtdp",
    "qc_adiabat_pressure",
    "qc_brightness_temperature",
    "qc_brightness_wavelength",
    "fnet_irfnet",
    "Fnet_IRFnet",
    "Fnet/IR-Fnet",
}
KNOWN_CHEMISTRY_NAMES = {
    "H2O",
    "CH4",
    "CO2",
    "CO",
    "NH3",
    "Na",
    "K",
    "TiO",
    "VO",
    "FeH",
    "H2S",
    "HCN",
    "PH3",
    "H2",
    "He",
}


def array_values(ds: xr.Dataset, name: str) -> np.ndarray | None:
    aliases = {
        "wavelength": "wavelength_um",
        "pressure": "pressure_bar",
        "pressure_bar": "pressure",
        "temperature": "temperature_k",
        "temperature_k": "temperature",
        "albedo": "geometric_albedo",
        "geometric_albedo": "albedo",
        "fpfs_reflected": "reflected_planet_star_flux_ratio",
        "fpfs_reflection": "reflected_planet_star_flux_ratio",
        "reflected_planet_star_flux_ratio": "fpfs_reflected",
        "opd": "cloud_optical_depth",
        "ssa": "single_scattering_albedo",
        "asy": "asymmetry_factor",
        "cloud_optical_depth": "opd",
        "single_scattering_albedo": "ssa",
        "asymmetry_factor": "asy",
        "Fnet_IRFnet": "fnet_irfnet",
        "fnet_irfnet": "Fnet_IRFnet",
    }
    if name not in ds and name == "fnet_irfnet":
        for candidate in ("Fnet_IRFnet", "Fnet/IR-Fnet"):
            if candidate in ds:
                name = candidate
                break
    if name not in ds and name in aliases:
        name = aliases[name]
    if name not in ds:
        return None
    try:
        return np.asarray(ds[name].values, dtype=float)
    except Exception:
        return None


def manifest_row(ds: xr.Dataset) -> dict[str, Any]:
    try:
        return json.loads(str(ds.attrs.get("source_manifest_row", "{}")))
    except Exception:
        return {}


def has_wavelength(ds: xr.Dataset) -> bool:
    """A valid Aurora model-store file must carry numeric wavelength values.

    A bare dimension named "wavelength" is not enough because downstream
    validation, plotting, and Zarr stacking need the actual coordinate array.
    """
    return "wavelength_um" in ds.coords or "wavelength" in ds.coords


def has_pressure(ds: xr.Dataset) -> bool:
    return "pressure_bar" in ds.data_vars or "pressure" in ds.coords or "pressure" in ds.dims or "pressure" in ds.data_vars


def pressure_dependent_vars(ds: xr.Dataset) -> list[str]:
    names: list[str] = []
    for name, data_array in ds.data_vars.items():
        if name in KNOWN_NON_CHEMISTRY:
            continue
        if name in KNOWN_CHEMISTRY_NAMES or any(dim == "pressure" for dim in data_array.dims):
            names.append(name)
    return sorted(names)


def classify_storage(ds: xr.Dataset | None, flags: list[QCFlag] | None = None) -> str:
    if ds is None:
        return "failed"
    flags = flags or []
    essential_failed = any(flag.check == "schema" and flag.severity == "fail" for flag in flags)
    if essential_failed:
        return "failed"
    if str(ds.attrs.get("schema_name", "")) == "aurora_subneptune_netcdf":
        return "aurora_schema_v1"
    if not (
        has_wavelength(ds)
        and ("geometric_albedo" in ds.data_vars or "albedo" in ds.data_vars)
        and (
            "reflected_planet_star_flux_ratio" in ds.data_vars
            or "fpfs_reflected" in ds.data_vars
            or "fpfs_reflection" in ds.data_vars
        )
    ):
        return "failed"
    if not has_pressure(ds) or "temperature" not in ds:
        return "spectrum_only"
    if "aurora_reflected_fraction" in ds.data_vars or "aurora_flux_reflected" in ds.data_vars:
        return "aurora_extended"
    return "picaso_reusable"


def validate_schema(ds: xr.Dataset, row: dict[str, Any] | None = None) -> list[QCFlag]:
    flags: list[QCFlag] = []
    if str(ds.attrs.get("schema_name", "")) == "aurora_subneptune_netcdf":
        for issue in validate_aurora_netcdf_schema(ds):
            severity = "warning" if issue.startswith("WARNING:") else "fail"
            flags.append(QCFlag("schema", severity, issue.split(": ", 1)[-1]))
        missing_diagnostics = []
        if not {"qc_adiabat", "qc_dtdp", "qc_adiabat_pressure"}.issubset(ds.data_vars):
            missing_diagnostics.append("adiabat")
        if "fnet_irfnet" not in ds.data_vars and "Fnet_IRFnet" not in ds.data_vars and "Fnet/IR-Fnet" not in ds.data_vars:
            missing_diagnostics.append("flux_balance")
        if not {"qc_brightness_temperature", "qc_brightness_wavelength"}.issubset(ds.data_vars):
            missing_diagnostics.append("brightness_temperature")
        if missing_diagnostics:
            flags.append(
                QCFlag(
                    "picaso_diagnostics",
                    "warning",
                    f"exact climate QC diagnostics unavailable: {','.join(missing_diagnostics)}",
                )
            )
        return flags

    if not has_wavelength(ds):
        flags.append(QCFlag("schema", "fail", "missing wavelength coordinate"))
    else:
        wavelength = array_values(ds, "wavelength")
        if wavelength is None or wavelength.ndim != 1:
            flags.append(QCFlag("schema", "fail", "wavelength is not 1D numeric"))
        elif not np.all(np.isfinite(wavelength)):
            flags.append(QCFlag("schema", "fail", "wavelength contains nonfinite values"))
        elif wavelength.size > 1:
            diff = np.diff(wavelength)
            if np.all(diff > 0):
                flags.append(QCFlag("schema", "info", "wavelength order increasing", "wavelength_order", "increasing"))
            elif np.all(diff < 0):
                flags.append(QCFlag("schema", "info", "wavelength order decreasing", "wavelength_order", "decreasing"))
            else:
                flags.append(QCFlag("schema", "fail", "wavelength is not strictly monotonic"))

    if "geometric_albedo" not in ds.data_vars and "albedo" not in ds.data_vars:
        flags.append(QCFlag("schema", "fail", "missing albedo"))
    if (
        "reflected_planet_star_flux_ratio" not in ds.data_vars
        and "fpfs_reflected" not in ds.data_vars
        and "fpfs_reflection" not in ds.data_vars
    ):
        flags.append(QCFlag("schema", "fail", "missing reflected fpfs variable"))
    if has_pressure(ds) and "temperature" not in ds:
        flags.append(QCFlag("schema", "warning", "pressure exists without temperature"))
    if "temperature" in ds and not has_pressure(ds):
        flags.append(QCFlag("schema", "warning", "temperature exists without pressure"))

    missing_attrs = [name for name in REQUIRED_ATTRS if name not in ds.attrs]
    if missing_attrs:
        flags.append(QCFlag("schema", "warning", f"missing attrs: {'|'.join(missing_attrs)}"))

    for cloud_name in ("cloud_optical_depth", "single_scattering_albedo", "asymmetry_factor", "opd", "ssa", "asy"):
        if cloud_name not in ds.data_vars:
            continue
        missing_dims = [dim for dim in ds[cloud_name].dims if dim not in ds.sizes]
        if missing_dims:
            flags.append(QCFlag("schema", "fail", f"{cloud_name} has invalid dimensions: {'|'.join(missing_dims)}"))

    return flags
