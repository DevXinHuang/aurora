#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import shutil
import sys
import typing
from pathlib import Path
from typing import Any

if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self

import numpy as np
import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


DEFAULT_OUT = GRID_ROOT / "data" / "combined" / "subneptune_grid_spectra_v1.zarr"
DEFAULT_VARIABLES = [
    "geometric_albedo",
    "reflected_planet_star_flux_ratio",
    "reflected_flux",
    "thermal_flux",
    "thermal_planet_star_flux_ratio",
    "total_planet_star_flux_ratio",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post-process finished Aurora per-run NetCDF files into a spectra-only Zarr collection."
    )
    parser.add_argument("--output-root", required=True, help="Directory containing per-run .nc files.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output Zarr store path.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing Zarr store.")
    parser.add_argument(
        "--variables",
        nargs="+",
        default=DEFAULT_VARIABLES,
        help="1D wavelength variables to combine.",
    )
    return parser.parse_args()


def _manifest_row(dataset: xr.Dataset) -> dict[str, Any]:
    try:
        return json.loads(str(dataset.attrs.get("source_manifest_row", "{}")))
    except Exception:
        return {}


def _run_index(dataset: xr.Dataset) -> int | None:
    value = dataset["run_index"].item() if "run_index" in dataset.data_vars else dataset.attrs.get("run_index", _manifest_row(dataset).get("run_index"))
    try:
        return int(value)
    except Exception:
        return None


def _can_stack(dataset: xr.Dataset, name: str, wavelength_size: int) -> bool:
    if name not in dataset.data_vars:
        return False
    data = dataset[name]
    return data.dims == ("wavelength",) and int(data.size) == int(wavelength_size)


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    output_path = Path(args.out)
    if output_path.exists():
        if not args.overwrite:
            raise FileExistsError(f"{output_path} exists; pass --overwrite to replace it.")
        if output_path.is_dir():
            shutil.rmtree(output_path)
        else:
            output_path.unlink()

    reference_wavelength: np.ndarray | None = None
    run_indices: list[int] = []
    file_paths: list[str] = []
    stacked: dict[str, list[np.ndarray]] = {name: [] for name in args.variables}
    skipped: list[str] = []

    for path in sorted(output_root.rglob("*.nc")):
        if path.name.endswith(".tmp.nc"):
            continue
        try:
            with xr.open_dataset(path) as dataset:
                if "wavelength_um" not in dataset.coords and "wavelength" not in dataset.coords:
                    skipped.append(f"{path}: missing wavelength")
                    continue
                wavelength_name = "wavelength_um" if "wavelength_um" in dataset.coords else "wavelength"
                wavelength = np.asarray(dataset[wavelength_name].values, dtype=float)
                if reference_wavelength is None:
                    reference_wavelength = wavelength
                elif wavelength.shape != reference_wavelength.shape or not np.allclose(
                    wavelength,
                    reference_wavelength,
                    rtol=0.0,
                    atol=1.0e-12,
                ):
                    skipped.append(f"{path}: wavelength grid mismatch")
                    continue
                run_index = _run_index(dataset)
                if run_index is None:
                    skipped.append(f"{path}: missing run_index")
                    continue

                run_indices.append(run_index)
                file_paths.append(str(path))
                for name in args.variables:
                    if _can_stack(dataset, name, wavelength.size):
                        stacked[name].append(np.asarray(dataset[name].values, dtype=float))
                    else:
                        stacked[name].append(np.full(wavelength.size, np.nan, dtype=float))
        except Exception as exc:
            skipped.append(f"{path}: {exc}")

    if reference_wavelength is None or not run_indices:
        raise RuntimeError("No stackable NetCDF files found.")

    order = np.argsort(np.asarray(run_indices, dtype=int))
    sorted_run_indices = np.asarray(run_indices, dtype=int)[order]
    sorted_file_paths = np.asarray(file_paths, dtype=object)[order]

    data_vars = {}
    for name, arrays in stacked.items():
        if not arrays:
            continue
        values = np.asarray(arrays, dtype=float)[order, :]
        if np.all(np.isnan(values)):
            continue
        data_vars[name] = (("run_index", "wavelength"), values)

    combined = xr.Dataset(
        data_vars=data_vars,
        coords={
            "run_index": ("run_index", sorted_run_indices),
            "wavelength_um": ("wavelength", reference_wavelength),
            "source_file": ("run_index", sorted_file_paths),
        },
        attrs={
            "aurora_collection_schema_version": "picaso_model_store_spectra_collection_v1",
            "source": "post-job collection of per-run Aurora PICASO model-store NetCDF files",
        },
    )
    combined["wavelength_um"].attrs["units"] = "um"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_zarr(output_path)

    print(f"combined_runs: {len(run_indices)}")
    print(f"combined_variables: {list(data_vars)}")
    print(f"skipped_files: {len(skipped)}")
    for item in skipped[:20]:
        print(f"skipped: {item}")
    if len(skipped) > 20:
        print(f"skipped_more: {len(skipped) - 20}")
    print(f"zarr: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
