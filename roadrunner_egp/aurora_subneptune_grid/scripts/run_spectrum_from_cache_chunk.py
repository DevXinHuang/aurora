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

from aurora_grid.factorization import read_factorized_manifest_csv
from aurora_grid.run_spectrum_one import run_spectrum_one


DISPLAY_COLUMNS = [
    "spectrum_index",
    "spectrum_run_id",
    "climate_index",
    "climate_key",
    "phase_deg",
    "planet_class_id",
    "separation_id",
    "climate_cache_nc",
    "output_nc",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one factorized spectrum row from a cached climate.")
    parser.add_argument("--manifest", required=True, help="Spectrum manifest CSV path.")
    parser.add_argument("--array-index", type=int, help="Run exactly the row with this spectrum_index.")
    parser.add_argument("--model-name", help="Expected model_name for selected rows.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing spectrum NetCDF files.")
    parser.add_argument("--dry-run", action="store_true", help="Use toy spectrum output instead of PICASO.")
    parser.add_argument("--start-index", type=int, help="Inclusive spectrum_index start.")
    parser.add_argument("--end-index", type=int, help="Exclusive spectrum_index end.")
    parser.add_argument("--limit", type=int, help="Run only the first N rows after selection.")
    return parser.parse_args()


def _select_rows(dataframe, args: argparse.Namespace):
    if args.array_index is not None and (args.start_index is not None or args.end_index is not None):
        raise ValueError("--array-index cannot be combined with --start-index/--end-index.")

    rows = dataframe.rows
    if args.array_index is not None:
        selected = [row for row in rows if int(row.get("spectrum_index", row.get("run_index", -1))) == int(args.array_index)]
        if not selected:
            raise ValueError(f"No row found for spectrum_index={args.array_index}.")
    else:
        selected = rows
        if args.start_index is not None:
            selected = [
                row
                for row in selected
                if int(row.get("spectrum_index", row.get("run_index", -1))) >= int(args.start_index)
            ]
        if args.end_index is not None:
            selected = [
                row
                for row in selected
                if int(row.get("spectrum_index", row.get("run_index", -1))) < int(args.end_index)
            ]

    if args.limit is not None:
        selected = selected[: int(args.limit)]
    if not selected:
        raise ValueError("Selection produced no rows.")
    return selected


def main() -> int:
    args = parse_args()
    dataframe = read_factorized_manifest_csv(args.manifest, kind="spectrum")
    selected = _select_rows(dataframe, args)

    if args.model_name:
        mismatched = [row for row in selected if str(row["model_name"]) != args.model_name]
        if mismatched:
            bad = [{"spectrum_index": row.get("spectrum_index"), "model_name": row["model_name"]} for row in mismatched[:5]]
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
        result = run_spectrum_one(row_dict, overwrite=args.overwrite, dry_run=args.dry_run)
        statuses.append(result)
        print("final_status:")
        print(result)

    failed = [status for status in statuses if str(status.get("status", "")).startswith("error")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
