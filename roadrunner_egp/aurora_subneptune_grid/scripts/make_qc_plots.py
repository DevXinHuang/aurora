#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import xarray as xr

from aurora_grid.qc.plots import failed_check_names, make_qc_plot, make_spectrum_plot
from aurora_grid.qc.report import validate_dataset


DEFAULT_SUMMARY = GRID_ROOT / "data" / "qc" / "reports" / "qc_summary.csv"
DEFAULT_PLOT_ROOT = GRID_ROOT / "data" / "qc" / "plots"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Aurora QC diagnostic plots from qc_summary.csv.")
    parser.add_argument("--qc-summary", default=str(DEFAULT_SUMMARY), help="QC summary CSV path.")
    parser.add_argument("--plot-root", default=str(DEFAULT_PLOT_ROOT), help="Directory for plots.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with Path(args.qc_summary).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    made = 0
    for row in rows:
        if row.get("status") == "pass":
            continue
        path = Path(row["file_path"])
        if not path.exists():
            continue
        with xr.open_dataset(path) as ds:
            result = validate_dataset(ds, path)
            run_id = result.run_id or path.stem
            for check_name in failed_check_names(result):
                check_dir = Path(args.plot_root) / f"check_{check_name}"
                make_qc_plot(ds, result, check_dir / f"{run_id}_diagnostic.png")
                make_spectrum_plot(ds, result, check_dir / f"{run_id}_spectrum.png")
                made += 2
    print(f"plots_created: {made}")
    print(f"plot_root: {args.plot_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
