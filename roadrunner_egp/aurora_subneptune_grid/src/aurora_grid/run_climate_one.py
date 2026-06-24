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
from .io.climate_cache_schema import (
    CLIMATE_CACHE_SCHEMA_NAME,
    build_climate_cache_dataset,
    write_climate_cache_netcdf,
)
from .picaso_climate import run_picaso_climate


def run_climate_one(row: dict[str, Any], overwrite: bool = False, dry_run: bool = False) -> dict[str, Any]:
    output_path = resolve_repo_path(row["climate_cache_nc"])
    if output_path.exists() and not overwrite:
        return {
            "status": "skipped_exists",
            "climate_key": str(row.get("climate_key", "")),
            "climate_cache_nc": str(output_path),
        }

    start = perf_counter()
    model_output = run_picaso_climate(row, dry_run=dry_run)
    runtime_seconds = perf_counter() - start
    dataset = build_climate_cache_dataset(model_output, row, runtime_seconds=runtime_seconds)
    write_status = write_climate_cache_netcdf(dataset, output_path, overwrite=overwrite)

    with xr.open_dataset(output_path) as reopened:
        if reopened.attrs.get("schema_name") != CLIMATE_CACHE_SCHEMA_NAME:
            raise RuntimeError(f"Climate cache verification failed for {output_path}: missing schema_name.")
        for name in ("pressure_bar", "temperature_k", "mole_fraction", "wavelength_um"):
            if name not in reopened:
                raise RuntimeError(f"Climate cache verification failed for {output_path}: missing {name}.")

    return {
        "status": write_status["status"],
        "climate_key": str(row.get("climate_key", "")),
        "climate_cache_nc": str(Path(write_status["output_nc"])),
    }
