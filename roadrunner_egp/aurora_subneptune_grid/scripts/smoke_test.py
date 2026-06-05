#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
import typing
from pathlib import Path

if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self

import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
REPO_ROOT = ROADRUNNER_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.parameters import create_manifest_dataframe, load_config, read_manifest_csv, resolve_repo_path
from aurora_grid.run_one import run_one


SMOKE_CONFIG = GRID_ROOT / "params" / "smoke_test.yaml"
SMOKE_MANIFEST = GRID_ROOT / "manifests" / "smoke_test_manifest.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Aurora smoke test.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Use toy spectra. This is the default.")
    mode.add_argument("--real", action="store_true", help="Attempt real PICASO runs.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing smoke outputs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dry_run = not args.real

    config = load_config(SMOKE_CONFIG)
    manifest = create_manifest_dataframe(config)
    SMOKE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(SMOKE_MANIFEST, index=False)
    manifest = read_manifest_csv(SMOKE_MANIFEST)

    print(f"smoke_manifest: {SMOKE_MANIFEST}")
    print(f"expected_rows: {len(manifest)}")
    print(f"dry_run: {dry_run}")

    statuses = []
    for row in manifest:
        result = run_one(row, overwrite=args.overwrite, dry_run=dry_run)
        statuses.append(result)
        print(result)

    expected_paths = [resolve_repo_path(row["output_nc"]) for row in manifest]
    existing_paths = [path for path in expected_paths if path.exists()]
    if len(existing_paths) != len(expected_paths):
        missing = [str(path) for path in expected_paths if not path.exists()]
        print(f"missing_outputs: {missing}")
        return 1

    sample_path = existing_paths[0]
    with xr.open_dataset(sample_path) as dataset:
        print(f"sample_output: {sample_path}")
        print("dimensions:")
        print(dict(dataset.sizes))
        print("data_variables:")
        print(list(dataset.data_vars))
        print("key_attrs:")
        for key in ["model_name", "run_id", "planet_params", "stellar_params", "orbit_params", "cld_params"]:
            print(f"{key}: {dataset.attrs.get(key)}")

    bad_statuses = [
        status
        for status in statuses
        if status.get("status") not in {"wrote", "skipped_exists"}
    ]
    if bad_statuses:
        print(f"bad_statuses: {bad_statuses}")
        return 1

    print(f"verified_outputs: {len(existing_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
