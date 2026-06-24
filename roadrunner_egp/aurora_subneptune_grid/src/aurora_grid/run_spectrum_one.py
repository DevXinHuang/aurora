from __future__ import annotations

import typing
from time import perf_counter
from pathlib import Path
from typing import Any

if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self

import xarray as xr

from .factorization import resolve_repo_path
from .io.climate_cache_schema import row_from_climate_cache, load_climate_cache
from .io.netcdf_schema import build_aurora_run_dataset, write_aurora_run_netcdf
from .picaso_spectrum_from_cache import run_picaso_spectrum_from_cache


def run_spectrum_one(row: dict[str, Any], overwrite: bool = False, dry_run: bool = False) -> dict[str, Any]:
    output_path = resolve_repo_path(row["output_nc"])
    climate_cache_path = resolve_repo_path(row["climate_cache_nc"])
    if not climate_cache_path.exists():
        raise FileNotFoundError(f"Climate cache not found: {climate_cache_path}")

    if output_path.exists() and not overwrite:
        return {
            "status": "skipped_exists",
            "spectrum_run_id": str(row.get("spectrum_run_id", "")),
            "output_nc": str(output_path),
        }

    climate_row = row_from_climate_cache(load_climate_cache(climate_cache_path))
    full_row = dict(climate_row)
    full_row.update(row)
    full_row["run_index"] = int(row.get("spectrum_index", row.get("run_index", 0)))
    full_row["run_id"] = str(row.get("spectrum_run_id", row.get("run_id", "")))
    full_row["phase_deg"] = float(row["phase_deg"])
    full_row["output_nc"] = str(row["output_nc"])
    for key in ("stellar_spectrum_filename", "stellar_spectrum_w_unit", "stellar_spectrum_f_unit"):
        if climate_row.get(key) not in (None, ""):
            full_row[key] = climate_row[key]
        elif row.get(key) not in (None, ""):
            full_row[key] = row[key]

    start = perf_counter()
    model_output = run_picaso_spectrum_from_cache(row, climate_cache_path, dry_run=dry_run)
    runtime_seconds = perf_counter() - start
    dataset = build_aurora_run_dataset(
        model_output,
        full_row,
        runtime_seconds=runtime_seconds,
        run_success=True,
    )
    write_status = write_aurora_run_netcdf(dataset, output_path, overwrite=overwrite)

    with xr.open_dataset(output_path) as reopened:
        if reopened.attrs.get("schema_name") != "aurora_subneptune_netcdf":
            raise RuntimeError(f"NetCDF verification failed for {output_path}: missing schema_name.")
        for name in [
            "wavelength_um",
            "reflected_planet_star_flux_ratio",
            "geometric_albedo",
            "pressure_bar",
            "temperature_k",
            "mole_fraction",
            "cloud_optical_depth",
        ]:
            if name not in reopened:
                raise RuntimeError(f"NetCDF verification failed for {output_path}: missing {name}.")

    return {
        "status": write_status["status"],
        "spectrum_run_id": str(row.get("spectrum_run_id", "")),
        "output_nc": str(Path(write_status["output_nc"])),
    }
