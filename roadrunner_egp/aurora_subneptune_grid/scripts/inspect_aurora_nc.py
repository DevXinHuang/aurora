#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.io.netcdf_schema import validate_aurora_netcdf_schema  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect one AURORA schema v1 NetCDF output.")
    parser.add_argument("output_nc", help="Path to a NetCDF file.")
    return parser.parse_args()


def _numeric_min_max(data_array: xr.DataArray) -> tuple[float, float] | None:
    try:
        values = np.asarray(data_array.values, dtype=float)
    except Exception:
        return None
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.nanmin(finite)), float(np.nanmax(finite))


def _print_mapping(title: str, values) -> None:
    print(f"{title}:")
    if isinstance(values, dict):
        for key, value in values.items():
            print(f"  {key}: {value}")
    else:
        for item in values:
            print(f"  {item}")


def main() -> int:
    args = parse_args()
    path = Path(args.output_nc)
    with xr.open_dataset(path) as dataset:
        print(f"file: {path}")
        _print_mapping("dimensions", dict(dataset.sizes))
        _print_mapping("coordinates", list(dataset.coords))
        _print_mapping("data_variables", list(dataset.data_vars))
        _print_mapping("attributes", dataset.attrs)

        raw_warnings = dataset.attrs.get("schema_warnings", "[]")
        try:
            warnings = json.loads(str(raw_warnings))
        except Exception:
            warnings = [str(raw_warnings)] if raw_warnings else []
        _print_mapping("schema_warnings", warnings)

        issues = validate_aurora_netcdf_schema(dataset)
        _print_mapping("schema_validation", issues or ["passed"])

        print("numeric_min_max:")
        for name in list(dataset.coords) + list(dataset.data_vars):
            stats = _numeric_min_max(dataset[name])
            if stats is None:
                continue
            print(f"  {name}: min={stats[0]} max={stats[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
