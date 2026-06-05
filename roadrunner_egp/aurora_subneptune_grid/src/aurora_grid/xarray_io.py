from __future__ import annotations

import json
import math
import os
import subprocess
import typing
from datetime import datetime, timezone
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

from .parameters import NOTEBOOK_REFERENCE, REPO_ROOT


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=_json_safe)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _row_value(row: dict[str, Any], key: str, default: Any = "") -> Any:
    value = row.get(key, default)
    if value is None:
        return default
    try:
        if bool(np.asarray(value != value).item()):
            return default
    except Exception:
        pass
    return value


def _planet_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rp": {"value": float(row["planet_radius_rearth"]), "unit": "R_earth"},
        "gravity": {"value": float(row["gravity_ms2"]), "unit": "m s-2"},
        "mh": {"value": float(row["metallicity_xsolar"]), "unit": "x_solar"},
        "cto": {"value": float(row["c_to_o_xsolar"]), "unit": "x_solar_C_to_O"},
        "cto_picaso_tag": {"value": str(row["c_to_o_picaso_tag"]).zfill(3), "unit": "table_tag"},
        "logkzz": {"value": float(row["logkzz"]), "unit": "log10_cm2_s-1"},
        "picaso_tint": {"value": float(row["picaso_tint_k"]), "unit": "K"},
    }


def _stellar_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "steff": {"value": float(row["star_teff_k"]), "unit": "K"},
        "rs": {"value": float(row["star_radius_rsun"]), "unit": "R_sun"},
        "luminosity": {"value": float(row["stellar_luminosity_lsun"]), "unit": "L_sun"},
    }


def _orbit_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sma": {"value": float(row["semi_major_au"]), "unit": "AU"},
        "insolation": {"value": float(row["insolation_searth"]), "unit": "S_earth"},
        "phase": {"value": float(row["phase_deg"]), "unit": "deg"},
        "equilibrium_temperature": {"value": float(row["equilibrium_temperature_k"]), "unit": "K"},
    }


def _cld_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cloud_fraction": {"value": float(row["cloud_fraction"]), "unit": "unitless"},
        "cloud_model": {"value": str(row.get("cloud_model", "")), "unit": "label"},
        "fsed": {"value": float(row["fsed"]), "unit": "unitless"},
        "kzz": {"value": float(row["kzz_cm2_s"]), "unit": "cm2 s-1"},
    }


def _grid_params(row: dict[str, Any], model_output: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_index": int(row["run_index"]),
        "model_name": str(row["model_name"]),
        "picaso_tint_mode": str(row.get("picaso_tint_mode", "equilibrium")),
        "picaso_tint_fixed_k": float(row.get("picaso_tint_fixed_k", 1000.0)),
        "picaso_tint_floor_k": float(row.get("picaso_tint_floor_k", 100.0)),
        "wavelength_min_um": float(np.nanmin(model_output["wavelength_um"])),
        "wavelength_max_um": float(np.nanmax(model_output["wavelength_um"])),
        "wavelength_points": int(np.asarray(model_output["wavelength_um"]).size),
        "picaso_metadata": model_output.get("picaso_metadata", {}),
    }


def _config_code(row: dict[str, Any]) -> str:
    code = row.get("code", "{}")
    if isinstance(code, str):
        return code
    return _json_dumps(code)


def build_dataset(model_output: dict[str, Any], row: dict[str, Any]) -> xr.Dataset:
    wavelength = np.asarray(model_output["wavelength_um"], dtype=float)
    data_vars: dict[str, tuple[tuple[str], np.ndarray, dict[str, str]]] = {
        "fpfs_reflection": (
            ("wavelength_um",),
            np.asarray(model_output["fpfs_reflection"], dtype=float),
            {"units": "planet_star_flux_ratio"},
        ),
        "albedo": (
            ("wavelength_um",),
            np.asarray(model_output["albedo"], dtype=float),
            {"units": "unitless"},
        ),
    }

    optional_units = {
        "fpfs_emission": "planet_star_flux_ratio",
        "reflected_fraction": "unitless",
        "absolute_flux_reflected": "erg cm-2 s-1 um-1",
        "absolute_flux_thermal": "erg cm-2 s-1 um-1",
    }
    for key, units in optional_units.items():
        values = model_output.get(key)
        if values is not None:
            data_vars[key] = (
                ("wavelength_um",),
                np.asarray(values, dtype=float),
                {"units": units},
            )

    dataset = xr.Dataset(
        data_vars=data_vars,
        coords={"wavelength_um": ("wavelength_um", wavelength, {"units": "micron"})},
    )
    dataset.attrs.update(
        {
            "model_name": str(row["model_name"]),
            "run_id": str(row["run_id"]),
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "git_commit": _git_commit(),
            "author": str(_row_value(row, "author")),
            "contact": str(_row_value(row, "contact")),
            "project": str(_row_value(row, "project")),
            "notes": str(_row_value(row, "notes")),
            "code": _config_code(row),
            "planet_params": _json_dumps(_planet_params(row)),
            "stellar_params": _json_dumps(_stellar_params(row)),
            "orbit_params": _json_dumps(_orbit_params(row)),
            "cld_params": _json_dumps(_cld_params(row)),
            "grid_params": _json_dumps(_grid_params(row, model_output)),
            "source_manifest_row": _json_dumps(row),
            "source_notebook_reference": str(row.get("source_notebook_reference", NOTEBOOK_REFERENCE)),
        }
    )
    return dataset


def write_dataset_atomic(ds: xr.Dataset, output_path: str | Path, overwrite: bool = False) -> dict[str, str]:
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
