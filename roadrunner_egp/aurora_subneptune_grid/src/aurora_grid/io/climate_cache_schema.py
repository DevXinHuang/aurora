from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from ..picaso_runner import _thermal_fpfs, wavelength_grid_um
from ..stellar_spectrum import stellar_spectrum_attrs
from .netcdf_schema import (
    _extract_cloud_profile,
    _extract_pt_profile,
)

CLIMATE_CACHE_SCHEMA_NAME = "aurora_climate_cache"
CLIMATE_CACHE_SCHEMA_VERSION = "1.0"


@dataclass
class ClimateCacheState:
    pressure_bar: np.ndarray
    temperature_k: np.ndarray
    species: list[str]
    mole_fraction: np.ndarray
    wavelength_um: np.ndarray
    thermal_planet_star_flux_ratio: np.ndarray | None
    thermal_flux: np.ndarray | None
    cloud_optical_depth: np.ndarray | None = None
    single_scattering_albedo: np.ndarray | None = None
    asymmetry_factor: np.ndarray | None = None
    cloud_native_wavelength_um: np.ndarray | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


def _picaso_version() -> str:
    try:
        return metadata.version("picaso")
    except Exception:
        try:
            import picaso

            return str(getattr(picaso, "__version__", "unknown"))
        except Exception:
            return "unknown"


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _param_dicts_from_row(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "planet_params": {
            "planet_radius_rearth": float(row["planet_radius_rearth"]),
            "gravity_ms2": float(row["gravity_ms2"]),
            "picaso_tint_k": float(row["picaso_tint_k"]),
        },
        "star_params": {
            "star_teff_k": float(row["star_teff_k"]),
            "star_radius_rsun": float(row["star_radius_rsun"]),
            **stellar_spectrum_attrs(row),
        },
        "orbit_params": {
            "semi_major_au": float(row["semi_major_au"]),
            "insolation_searth": float(row["insolation_searth"]),
            "equilibrium_temperature_k": float(row.get("equilibrium_temperature_k", np.nan)),
        },
        "chemistry_params": {
            "metallicity_xsolar": float(row["metallicity_xsolar"]),
            "c_to_o_xsolar": float(row["c_to_o_xsolar"]),
            "kzz_cm2_s": float(row["kzz_cm2_s"]),
        },
        "cloud_params": {
            "cloud_fraction": float(row["cloud_fraction"]),
            "cloud_model": str(row.get("cloud_model", "")),
            "virga_condensates": str(row.get("virga_condensates", "")),
            "fsed": float(row["fsed"]) if row.get("fsed") not in (None, "") else None,
        },
    }


def build_climate_cache_dataset(
    model_output: dict[str, Any],
    row: dict[str, Any],
    *,
    runtime_seconds: float | None = None,
) -> xr.Dataset:
    wavelength_um = np.asarray(model_output.get("wavelength_um", wavelength_grid_um()), dtype=float)
    pressure_bar, temperature_k, species, mole_fraction = _extract_pt_profile(model_output)
    nlayer = pressure_bar.size - 1
    cloud_optical_depth = None
    single_scattering_albedo = None
    asymmetry_factor = None
    cloud_native_wavelength_um = None
    try:
        cloud_optical_depth, single_scattering_albedo, asymmetry_factor = _extract_cloud_profile(
            model_output,
            row,
            wavelength_um,
            nlayer,
        )
        cloud_profile = model_output.get("cloud_profile")
        if isinstance(cloud_profile, dict) and "wavelength_um" in cloud_profile:
            cloud_native_wavelength_um = np.asarray(cloud_profile["wavelength_um"], dtype=float)
    except Exception:
        pass

    thermal_fpfs = model_output.get("fpfs_emission")
    if thermal_fpfs is None and model_output.get("picaso_out_emission") is not None:
        thermal_fpfs = _thermal_fpfs(model_output["picaso_out_emission"], wavelength_um)
    thermal_flux = model_output.get("absolute_flux_thermal")

    data_vars: dict[str, Any] = {
        "pressure_bar": (("level",), pressure_bar, {"units": "bar"}),
        "temperature_k": (("level",), temperature_k, {"units": "K"}),
        "mole_fraction": (
            ("level", "species"),
            mole_fraction,
            {"units": "volume mixing ratio"},
        ),
        "wavelength_um": (("wavelength",), wavelength_um, {"units": "um"}),
    }
    if thermal_fpfs is not None:
        data_vars["thermal_planet_star_flux_ratio"] = (
            ("wavelength",),
            np.asarray(thermal_fpfs, dtype=float),
            {"units": "dimensionless"},
        )
    if thermal_flux is not None:
        data_vars["thermal_flux"] = (
            ("wavelength",),
            np.asarray(thermal_flux, dtype=float),
            {"units": "erg cm-2 s-1 um-1"},
        )
    if cloud_optical_depth is not None:
        data_vars["cloud_optical_depth"] = (("layer", "cloud_wavelength"), cloud_optical_depth, {"units": "dimensionless"})
        data_vars["single_scattering_albedo"] = (("layer", "cloud_wavelength"), single_scattering_albedo, {"units": "dimensionless"})
        data_vars["asymmetry_factor"] = (("layer", "cloud_wavelength"), asymmetry_factor, {"units": "dimensionless"})
        if cloud_native_wavelength_um is not None:
            data_vars["cloud_native_wavelength_um"] = (("cloud_wavelength",), cloud_native_wavelength_um, {"units": "um"})
        else:
            data_vars["cloud_native_wavelength_um"] = (("cloud_wavelength",), wavelength_um, {"units": "um"})

    ds = xr.Dataset(
        data_vars=data_vars,
        coords={
            "level": np.arange(pressure_bar.size),
            "layer": np.arange(nlayer),
            "species": list(species),
        },
    )
    param_dicts = _param_dicts_from_row(row)
    created_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    ds.attrs.update(
        {
            "schema_name": CLIMATE_CACHE_SCHEMA_NAME,
            "schema_version": CLIMATE_CACHE_SCHEMA_VERSION,
            "model_name": str(row["model_name"]),
            "climate_key": str(row.get("climate_key", "")),
            "climate_index": int(row.get("climate_index", -1)),
            "planet_class_id": str(row.get("planet_class_id", "")),
            "separation_id": str(row.get("separation_id", "")),
            "picaso_version": _picaso_version(),
            "created_utc": created_utc,
            "runtime_seconds": float(runtime_seconds or 0.0),
            "wavelength_min_um": float(np.nanmin(wavelength_um)),
            "wavelength_max_um": float(np.nanmax(wavelength_um)),
            "source_climate_row": json.dumps(row, sort_keys=True, default=str),
            **{key: json.dumps(value, sort_keys=True) for key, value in param_dicts.items()},
            **stellar_spectrum_attrs(row),
        }
    )
    return ds


def write_climate_cache_netcdf(ds: xr.Dataset, output_path: str | Path, overwrite: bool = False) -> dict[str, str]:
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


def load_climate_cache(path: str | Path) -> ClimateCacheState:
    with xr.open_dataset(path) as ds:
        if ds.attrs.get("schema_name") != CLIMATE_CACHE_SCHEMA_NAME:
            raise ValueError(f"{path} is not an aurora_climate_cache file.")
        species = [str(item) for item in ds["species"].values]
        state = ClimateCacheState(
            pressure_bar=np.asarray(ds["pressure_bar"].values, dtype=float),
            temperature_k=np.asarray(ds["temperature_k"].values, dtype=float),
            species=species,
            mole_fraction=np.asarray(ds["mole_fraction"].values, dtype=float),
            wavelength_um=np.asarray(ds["wavelength_um"].values, dtype=float),
            thermal_planet_star_flux_ratio=(
                np.asarray(ds["thermal_planet_star_flux_ratio"].values, dtype=float)
                if "thermal_planet_star_flux_ratio" in ds
                else None
            ),
            thermal_flux=np.asarray(ds["thermal_flux"].values, dtype=float) if "thermal_flux" in ds else None,
            cloud_optical_depth=(
                np.asarray(ds["cloud_optical_depth"].values, dtype=float)
                if "cloud_optical_depth" in ds
                else None
            ),
            single_scattering_albedo=(
                np.asarray(ds["single_scattering_albedo"].values, dtype=float)
                if "single_scattering_albedo" in ds
                else None
            ),
            asymmetry_factor=(
                np.asarray(ds["asymmetry_factor"].values, dtype=float)
                if "asymmetry_factor" in ds
                else None
            ),
            cloud_native_wavelength_um=(
                np.asarray(ds["cloud_native_wavelength_um"].values, dtype=float)
                if "cloud_native_wavelength_um" in ds
                else None
            ),
            attrs=dict(ds.attrs),
        )
    return state


def _profile_dataframe_from_cache(state: ClimateCacheState) -> pd.DataFrame:
    data = {
        "pressure": state.pressure_bar,
        "temperature": state.temperature_k,
    }
    for index, species in enumerate(state.species):
        data[species] = state.mole_fraction[:, index]
    return pd.DataFrame(data)


def _cloud_dataframe_from_cache(state: ClimateCacheState) -> pd.DataFrame | None:
    if state.cloud_optical_depth is None:
        return None
    wavelength = state.cloud_native_wavelength_um
    if wavelength is None:
        return None
    rows = []
    nlayer = state.cloud_optical_depth.shape[0]
    for layer_index in range(nlayer):
        for wave_index, wave in enumerate(wavelength):
            rows.append(
                {
                    "pressure": state.pressure_bar[layer_index],
                    "wavelength": float(wave),
                    "opd": float(state.cloud_optical_depth[layer_index, wave_index]),
                    "w0": float(state.single_scattering_albedo[layer_index, wave_index])
                    if state.single_scattering_albedo is not None
                    else 0.0,
                    "g0": float(state.asymmetry_factor[layer_index, wave_index])
                    if state.asymmetry_factor is not None
                    else 0.0,
                }
            )
    return pd.DataFrame(rows)


def apply_climate_cache_to_case(case, state: ClimateCacheState, *, verbose: bool = False) -> None:
    """Attach cached PT/chemistry/cloud profiles to an existing PICASO case."""
    profile_df = _profile_dataframe_from_cache(state)
    atmosphere_loaded = False
    for loader in (
        lambda: case.atmosphere(df=profile_df),
        lambda: case.atmosphere(filename=_write_temp_pt_file(profile_df), sep=r"\s+"),
    ):
        try:
            loader()
            atmosphere_loaded = True
            break
        except Exception:
            continue
    if not atmosphere_loaded:
        raise RuntimeError("Failed to load cached atmosphere into PICASO case.")

    cloud_df = _cloud_dataframe_from_cache(state)
    if cloud_df is not None and not cloud_df.empty:
        cloud_df.columns = [str(col).lower() for col in cloud_df.columns]
        try:
            case.clouds(df=cloud_df)
        except Exception as exc:
            if verbose:
                print(f"Warning: could not reload cached clouds ({exc}); continuing with PT-only case.")

    if verbose:
        print(f"Loaded cached climate with {profile_df.shape[0]} levels and {len(state.species)} species.")


def _write_temp_pt_file(profile_df: pd.DataFrame) -> str:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".pt", delete=False)
    try:
        profile_df.to_csv(handle, sep=" ", index=False)
        handle.flush()
        return handle.name
    finally:
        handle.close()


def row_from_climate_cache(state: ClimateCacheState) -> dict[str, Any]:
    source = _json_dict(state.attrs.get("source_climate_row"))
    if source:
        return source
    planet = _json_dict(state.attrs.get("planet_params"))
    star = _json_dict(state.attrs.get("star_params"))
    orbit = _json_dict(state.attrs.get("orbit_params"))
    chemistry = _json_dict(state.attrs.get("chemistry_params"))
    cloud = _json_dict(state.attrs.get("cloud_params"))
    return {
        "model_name": state.attrs.get("model_name", ""),
        "climate_key": state.attrs.get("climate_key", ""),
        "climate_index": state.attrs.get("climate_index", -1),
        "planet_class_id": state.attrs.get("planet_class_id", ""),
        "separation_id": state.attrs.get("separation_id", ""),
        "star_teff_k": star.get("star_teff_k", np.nan),
        "star_radius_rsun": star.get("star_radius_rsun", np.nan),
        "stellar_spectrum_filename": state.attrs.get(
            "stellar_spectrum_filename",
            star.get("stellar_spectrum_filename", ""),
        ),
        "stellar_spectrum_w_unit": state.attrs.get(
            "stellar_spectrum_w_unit",
            star.get("stellar_spectrum_w_unit", ""),
        ),
        "stellar_spectrum_f_unit": state.attrs.get(
            "stellar_spectrum_f_unit",
            star.get("stellar_spectrum_f_unit", ""),
        ),
        "planet_radius_rearth": planet.get("planet_radius_rearth", np.nan),
        "gravity_ms2": planet.get("gravity_ms2", np.nan),
        "picaso_tint_k": planet.get("picaso_tint_k", np.nan),
        "semi_major_au": orbit.get("semi_major_au", np.nan),
        "insolation_searth": orbit.get("insolation_searth", np.nan),
        "metallicity_xsolar": chemistry.get("metallicity_xsolar", np.nan),
        "c_to_o_xsolar": chemistry.get("c_to_o_xsolar", 1.0),
        "kzz_cm2_s": chemistry.get("kzz_cm2_s", np.nan),
        "cloud_fraction": cloud.get("cloud_fraction", 0.0),
        "cloud_model": cloud.get("cloud_model", "none"),
        "fsed": cloud.get("fsed", np.nan),
    }
