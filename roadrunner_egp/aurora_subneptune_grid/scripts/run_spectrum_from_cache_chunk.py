#!/usr/bin/env python
"""Write one spectrum NetCDF from a cached climate PT profile (stage 2)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.cahoy_climate_cache import climate_cache_path, load_climate_cache
from aurora_grid.io.netcdf_schema import build_aurora_run_dataset, write_aurora_run_netcdf
from aurora_grid.parameters import read_manifest_csv, resolve_repo_path
from aurora_grid.picaso_runner import run_picaso_model_from_climate_cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2: reflected spectrum from cached climate.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--array-index", type=int, required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--ck-root", default=None)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def existing_output_matches_run_id(path: Path, expected_run_id: str) -> bool:
    try:
        with xr.open_dataset(path) as dataset:
            return str(dataset.attrs.get("run_id", "")) == str(expected_run_id)
    except Exception:
        return False


def main() -> int:
    args = parse_args()
    table = read_manifest_csv(args.manifest)
    matches = [row for row in table.rows if int(row["run_index"]) == int(args.array_index)]
    if not matches:
        raise ValueError(f"No manifest row for run_index={args.array_index}")
    row = dict(matches[0])
    if str(row["model_name"]) != args.model_name:
        raise ValueError(f"Row model_name mismatch: {row['model_name']!r} != {args.model_name!r}")
    climate_group_key = str(row.get("climate_group_key", "")).strip()
    if not climate_group_key:
        raise ValueError(
            "Manifest is stale: missing climate_group_key. Regenerate it before running spectra."
        )

    output_path = resolve_repo_path(row["output_nc"])
    if output_path.exists() and not args.overwrite:
        if not existing_output_matches_run_id(output_path, str(row["run_id"])):
            raise ValueError(
                f"Existing output {output_path} does not match run_id {row['run_id']!r}; "
                "archive it or rerun with --overwrite."
            )
        print(f"skipped_exists: {output_path}")
        return 0

    output_root = str(Path(row["output_nc"]).parent.parent)
    group_index = int(row["climate_group_index"])
    cache_file = climate_cache_path(output_root, group_index)
    climate_cache = load_climate_cache(
        cache_file,
        expected_climate_group_key=climate_group_key,
    )

    start = perf_counter()
    model_output = run_picaso_model_from_climate_cache(row, climate_cache, ck_root=args.ck_root)
    runtime_seconds = perf_counter() - start
    dataset = build_aurora_run_dataset(
        model_output,
        row,
        runtime_seconds=runtime_seconds,
        run_success=True,
    )
    write_status = write_aurora_run_netcdf(dataset, output_path, overwrite=args.overwrite)
    print(f"status: {write_status['status']}")
    print(f"output_nc: {output_path}")
    print(f"climate_group_index: {group_index}")
    print(f"phase_deg: {row.get('phase_deg')}")
    print(f"climate_cache: {cache_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
