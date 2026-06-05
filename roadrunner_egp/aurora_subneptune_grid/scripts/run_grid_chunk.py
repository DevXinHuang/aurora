#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.parameters import read_manifest_csv
from aurora_grid.run_one import run_one


DISPLAY_COLUMNS = [
    "run_index",
    "model_name",
    "run_id",
    "star_teff_k",
    "star_radius_rsun",
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
    "picaso_tint_k",
    "output_nc",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Aurora grid row or a selected chunk.")
    parser.add_argument("--manifest", required=True, help="Manifest CSV path.")
    parser.add_argument("--array-index", type=int, help="Run exactly the row with this run_index.")
    parser.add_argument("--model-name", help="Expected model_name for selected rows.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing NetCDF outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Use a toy spectrum instead of running PICASO.")
    parser.add_argument("--start-index", type=int, help="Inclusive run_index start.")
    parser.add_argument("--end-index", type=int, help="Exclusive run_index end.")
    parser.add_argument("--limit", type=int, help="Run only the first N rows after selection.")
    return parser.parse_args()


def _select_rows(dataframe, args: argparse.Namespace):
    if args.array_index is not None and (args.start_index is not None or args.end_index is not None):
        raise ValueError("--array-index cannot be combined with --start-index/--end-index.")

    rows = dataframe.rows
    if args.array_index is not None:
        selected = [row for row in rows if int(row["run_index"]) == int(args.array_index)]
        if not selected:
            raise ValueError(f"No row found for run_index={args.array_index}.")
    else:
        selected = rows
        if args.start_index is not None:
            selected = [row for row in selected if int(row["run_index"]) >= int(args.start_index)]
        if args.end_index is not None:
            selected = [row for row in selected if int(row["run_index"]) < int(args.end_index)]

    if args.limit is not None:
        selected = selected[: int(args.limit)]
    if not selected:
        raise ValueError("Selection produced no rows.")
    return selected


def main() -> int:
    args = parse_args()
    dataframe = read_manifest_csv(args.manifest)
    selected = _select_rows(dataframe, args)

    if args.model_name:
        mismatched = [row for row in selected if str(row["model_name"]) != args.model_name]
        if mismatched:
            bad = [
                {"run_index": row["run_index"], "model_name": row["model_name"]}
                for row in mismatched[:5]
            ]
            raise ValueError(f"Selected rows do not match --model-name={args.model_name!r}: {bad}")

    print(f"manifest: {args.manifest}")
    print(f"selected_rows: {len(selected)}")
    print(f"dry_run: {args.dry_run}")
    print(f"overwrite: {args.overwrite}")

    statuses = []
    for row_dict in selected:
        print("selected_row:")
        for column in DISPLAY_COLUMNS:
            print(f"{column}: {row_dict.get(column)}")
        result = run_one(row_dict, overwrite=args.overwrite, dry_run=args.dry_run)
        statuses.append(result)
        print("final_status:")
        print(result)

    failed = [status for status in statuses if str(status.get("status", "")).startswith("error")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
