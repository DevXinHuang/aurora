from __future__ import annotations

import typing
from pathlib import Path
from typing import Any

if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self

import xarray as xr

from .parameters import resolve_repo_path
from .picaso_runner import run_picaso_model
from .storage.picaso_model_store import build_picaso_model_dataset, save_picaso_model_dataset


def run_one(row: dict[str, Any], overwrite: bool = False, dry_run: bool = False) -> dict[str, Any]:
    output_path = resolve_repo_path(row["output_nc"])
    if output_path.exists() and not overwrite:
        return {
            "status": "skipped_exists",
            "run_id": str(row["run_id"]),
            "output_nc": str(output_path),
        }

    model_output = run_picaso_model(row, dry_run=dry_run)
    dataset = build_picaso_model_dataset(model_output, row)
    write_status = save_picaso_model_dataset(dataset, output_path, overwrite=overwrite)

    with xr.open_dataset(output_path) as reopened:
        if "wavelength" not in reopened.dims and "wavelength" not in reopened.coords:
            raise RuntimeError(f"NetCDF verification failed for {output_path}: missing wavelength coordinate.")
        if "albedo" not in reopened.data_vars:
            raise RuntimeError(f"NetCDF verification failed for {output_path}: missing albedo.")
        if "fpfs_reflected" not in reopened.data_vars:
            raise RuntimeError(f"NetCDF verification failed for {output_path}: missing fpfs_reflected.")
        if "fpfs_reflection" not in reopened.data_vars:
            raise RuntimeError(f"NetCDF verification failed for {output_path}: missing fpfs_reflection compatibility alias.")

    return {
        "status": write_status["status"],
        "run_id": str(row["run_id"]),
        "output_nc": str(Path(write_status["output_nc"])),
    }
