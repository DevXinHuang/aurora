from __future__ import annotations

import os
import typing
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self

import xarray as xr

from ..xarray_io import _git_commit, build_dataset as build_spectrum_dataset


SCHEMA_VERSION = "picaso_model_store_v1"

SPECTRUM_UNITS = {
    "fpfs_reflected": "planet_star_flux_ratio",
    "fpfs_reflection": "planet_star_flux_ratio",
    "fpfs_emission": "planet_star_flux_ratio",
    "albedo": "unitless",
    "flux_emission": "erg cm-2 s-1 um-1",
    "aurora_flux_reflected": "erg cm-2 s-1 um-1",
    "aurora_reflected_fraction": "unitless",
}


def _picaso_version() -> str:
    try:
        return metadata.version("picaso")
    except Exception:
        try:
            import picaso

            return str(getattr(picaso, "__version__", "unknown"))
        except Exception:
            return "unknown"


def _has_dataarray(ds: xr.Dataset, name: str) -> bool:
    return name in ds.data_vars or name in ds.coords


def _as_1d_array(values: Any) -> np.ndarray | None:
    if values is None:
        return None
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        return None
    return array


def _ensure_wavelength(ds: xr.Dataset, model_output: dict[str, Any] | None = None) -> xr.Dataset:
    if "wavelength_um" in ds.dims and "wavelength" not in ds.dims:
        ds = ds.rename({"wavelength_um": "wavelength"})
    elif "wavelength_um" in ds.coords and "wavelength" not in ds.coords:
        ds = ds.rename({"wavelength_um": "wavelength"})

    wavelength = None if model_output is None else _as_1d_array(model_output.get("wavelength_um"))
    if wavelength is not None and "wavelength" in ds.sizes and ds.sizes["wavelength"] != wavelength.size:
        if "picaso_wavelength" not in ds.sizes and "picaso_wavelength" not in ds.coords:
            ds = ds.rename({"wavelength": "picaso_wavelength"})
            if "picaso_wavelength" in ds.coords:
                ds["picaso_wavelength"].attrs.setdefault("units", "micron")

    if "wavelength" not in ds.coords and wavelength is not None:
        ds = ds.assign_coords({"wavelength": ("wavelength", wavelength)})

    if "wavelength" in ds.coords:
        ds["wavelength"].attrs["units"] = "micron"
    return ds


def _add_spectrum_variable(
    ds: xr.Dataset,
    name: str,
    values: Any,
    *,
    units: str,
) -> xr.Dataset:
    array = _as_1d_array(values)
    if array is None or name in ds.data_vars:
        return ds

    if "wavelength" not in ds.coords:
        return ds
    wavelength_size = int(ds.sizes.get("wavelength", -1))
    if array.size != wavelength_size:
        return ds

    ds[name] = (("wavelength",), array)
    ds[name].attrs["units"] = units
    return ds


def _copy_dataarray(ds: xr.Dataset, source: str, target: str) -> xr.Dataset:
    if target not in ds.data_vars and source in ds.data_vars:
        ds[target] = ds[source].copy(deep=True)
    return ds


def _drop_if_present(ds: xr.Dataset, name: str) -> xr.Dataset:
    if name in ds.data_vars:
        ds = ds.drop_vars(name)
    return ds


def _try_picaso_output_xarray(model_output: dict[str, Any]) -> tuple[xr.Dataset | None, str | None]:
    out_ref = model_output.get("picaso_out_reflected")
    out_emission = model_output.get("picaso_out_emission")
    case = model_output.get("picaso_case")
    if out_ref is None or case is None:
        return None, "missing picaso_out_reflected or picaso_case"

    try:
        from picaso import justdoit as jdi
    except Exception as exc:
        return None, f"picaso import failed: {exc}"

    output_xarray = getattr(jdi, "output_xarray", None)
    if output_xarray is None:
        return None, "picaso.justdoit.output_xarray unavailable"

    add_output = {}
    if isinstance(out_emission, dict):
        add_output["thermal_output"] = out_emission

    try:
        dataset = output_xarray(out_ref, case, add_output=add_output, savefile=None)
    except Exception as exc:
        if add_output:
            try:
                dataset = output_xarray(out_ref, case, add_output={}, savefile=None)
            except Exception:
                return None, f"picaso output_xarray failed: {exc}"
        else:
            return None, f"picaso output_xarray failed: {exc}"
    if not isinstance(dataset, xr.Dataset):
        return None, f"picaso output_xarray returned {type(dataset).__name__}"
    return dataset.copy(deep=True), None


def standardize_picaso_dataset_names(ds: xr.Dataset) -> xr.Dataset:
    """Normalize PICASO/Aurora names to the v1 model-store schema."""
    ds = _ensure_wavelength(ds)

    rename_vars: dict[str, str] = {}
    for old_name, new_name in {
        "absolute_flux_thermal": "flux_emission",
        "reflected_fraction": "aurora_reflected_fraction",
        "absolute_flux_reflected": "aurora_flux_reflected",
    }.items():
        if old_name in ds.data_vars and new_name not in ds.data_vars:
            rename_vars[old_name] = new_name
    if rename_vars:
        ds = ds.rename_vars(rename_vars)

    for old_name in ("absolute_flux_thermal", "reflected_fraction", "absolute_flux_reflected"):
        ds = _drop_if_present(ds, old_name)

    ds = _copy_dataarray(ds, "fpfs_reflection", "fpfs_reflected")
    ds = _copy_dataarray(ds, "fpfs_reflected", "fpfs_reflection")

    coord_units = {
        "wavelength": "micron",
        "pressure": "bar",
        "pressure_layer": "bar",
        "wno": "cm^-1",
        "wavenumber_layer": "cm^-1",
    }
    for name, units in coord_units.items():
        if _has_dataarray(ds, name):
            ds[name].attrs["units"] = units

    for name, units in SPECTRUM_UNITS.items():
        if name in ds.data_vars:
            ds[name].attrs.setdefault("units", units)

    return ds


def add_aurora_spectral_aliases(ds: xr.Dataset, model_output: dict[str, Any]) -> xr.Dataset:
    """Add Aurora reduced spectra and compatibility aliases on wavelength."""
    ds = _ensure_wavelength(ds, model_output)
    spectrum_sources = {
        "fpfs_reflected": model_output.get("fpfs_reflection"),
        "fpfs_reflection": model_output.get("fpfs_reflection"),
        "albedo": model_output.get("albedo"),
        "fpfs_emission": model_output.get("fpfs_emission"),
        "flux_emission": model_output.get("absolute_flux_thermal"),
        "aurora_reflected_fraction": model_output.get("reflected_fraction"),
        "aurora_flux_reflected": model_output.get("absolute_flux_reflected"),
    }
    for name, values in spectrum_sources.items():
        ds = _add_spectrum_variable(
            ds,
            name,
            values,
            units=SPECTRUM_UNITS.get(name, "unitless"),
        )

    ds = standardize_picaso_dataset_names(ds)
    return ds


def add_aurora_metadata(ds: xr.Dataset, model_output: dict[str, Any], row: dict[str, Any]) -> xr.Dataset:
    """Attach Aurora metadata and schema attrs to a PICASO or fallback dataset."""
    fallback_dataset = build_spectrum_dataset(model_output, row)
    fallback_attrs = dict(fallback_dataset.attrs)
    fallback_dataset.close()
    ds.attrs.update(fallback_attrs)
    ds.attrs.update(
        {
            "run_index": int(row["run_index"]),
            "git_commit": _git_commit(),
            "picaso_version": _picaso_version(),
            "aurora_schema_version": SCHEMA_VERSION,
        }
    )
    if "picaso_output_xarray_error" in model_output:
        ds.attrs["picaso_output_xarray_error"] = str(model_output["picaso_output_xarray_error"])
    return ds


def build_picaso_model_dataset(model_output: dict[str, Any], row: dict[str, Any]) -> xr.Dataset:
    """Build one per-run PICASO/Aurora archive dataset."""
    dataset, error = _try_picaso_output_xarray(model_output)
    if dataset is None:
        dataset = build_spectrum_dataset(model_output, row)
        model_output = dict(model_output)
        if error:
            model_output["picaso_output_xarray_error"] = error
        dataset.attrs["storage_level"] = "spectrum_only"
    else:
        dataset.attrs["storage_level"] = "picaso_reusable"

    dataset = add_aurora_spectral_aliases(dataset, model_output)
    dataset = add_aurora_metadata(dataset, model_output, row)
    dataset_names = set(dataset.coords) | set(dataset.data_vars) | set(dataset.dims)
    if {"pressure", "temperature"}.issubset(dataset_names):
        dataset.attrs["storage_level"] = "aurora_extended" if "albedo" in dataset.data_vars else "picaso_reusable"
    return dataset


def write_netcdf_atomic(ds: xr.Dataset, output_path: str | Path, overwrite: bool = False) -> dict[str, str]:
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        return {"status": "skipped_exists", "output_nc": str(output_path)}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(str(output_path) + ".tmp.nc")
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        ds.to_netcdf(tmp_path)
        os.replace(tmp_path, output_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    finally:
        ds.close()

    return {"status": "wrote", "output_nc": str(output_path)}


def save_picaso_model_dataset(ds: xr.Dataset, output_path: str | Path, overwrite: bool = False) -> dict[str, str]:
    return write_netcdf_atomic(ds, output_path, overwrite=overwrite)
