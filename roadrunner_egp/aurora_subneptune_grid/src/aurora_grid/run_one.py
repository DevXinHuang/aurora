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

from .io.netcdf_schema import build_aurora_run_dataset, write_aurora_run_netcdf
from .parameters import resolve_repo_path
from .picaso_runner import run_picaso_model


def run_one(
    row: dict[str, Any],
    overwrite: bool = False,
    dry_run: bool = False,
    *,
    run_exact_climate_qc: bool = False,
    ck_root: str | Path | None = None,
) -> dict[str, Any]:
    output_path = resolve_repo_path(row["output_nc"])
    if output_path.exists() and not overwrite:
        return {
            "status": "skipped_exists",
            "run_id": str(row["run_id"]),
            "output_nc": str(output_path),
        }

    start = perf_counter()
    model_output = run_picaso_model(
        row,
        dry_run=dry_run,
        run_exact_climate_qc=run_exact_climate_qc,
        ck_root=ck_root,
    )
    runtime_seconds = perf_counter() - start
    dataset = build_aurora_run_dataset(
        model_output,
        row,
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
        "run_id": str(row["run_id"]),
        "output_nc": str(Path(write_status["output_nc"])),
    }
