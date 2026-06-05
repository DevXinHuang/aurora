#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
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


INVENTORY_COLUMNS = [
    "output_nc",
    "model_name",
    "run_id",
    "star_teff_k",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "c_to_o_picaso_tag",
    "kzz_cm2_s",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "phase_deg",
    "semi_major_au",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an inventory CSV from Aurora NetCDF outputs.")
    parser.add_argument("--output-root", required=True, help="Directory to scan for .nc files.")
    parser.add_argument("--out", required=True, help="Output inventory CSV path.")
    return parser.parse_args()


def _load_manifest_row(dataset: xr.Dataset) -> dict[str, Any]:
    raw = dataset.attrs.get("source_manifest_row", "{}")
    try:
        return json.loads(raw)
    except Exception:
        return {}


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    rows = []
    for output_nc in sorted(output_root.rglob("*.nc")):
        if output_nc.name.endswith(".tmp.nc"):
            continue
        with xr.open_dataset(output_nc) as dataset:
            source_row = _load_manifest_row(dataset)
            row = {column: source_row.get(column) for column in INVENTORY_COLUMNS}
            row["output_nc"] = str(output_nc)
            row["model_name"] = row["model_name"] or dataset.attrs.get("model_name")
            row["run_id"] = row["run_id"] or dataset.attrs.get("run_id")
            rows.append(row)

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"output_root: {output_root}")
    print(f"inventory_rows: {len(rows)}")
    print(f"inventory_csv: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
