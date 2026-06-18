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
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.qc.plots import failed_check_names, make_qc_plot, make_spectrum_plot
from aurora_grid.qc.report import result_to_row, validate_dataset, write_summary


DEFAULT_OUTPUT_ROOT = GRID_ROOT / "data" / "grid_runs"
DEFAULT_REPORT_CSV = GRID_ROOT / "data" / "qc" / "reports" / "qc_summary.csv"
DEFAULT_REPORT_JSON = GRID_ROOT / "data" / "qc" / "reports" / "qc_summary.json"
DEFAULT_PLOT_ROOT = GRID_ROOT / "data" / "qc" / "plots"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Aurora per-run PICASO NetCDF outputs.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Directory to scan for .nc files.")
    parser.add_argument("--out-csv", default=str(DEFAULT_REPORT_CSV), help="QC summary CSV path.")
    parser.add_argument("--out-json", default=str(DEFAULT_REPORT_JSON), help="QC summary JSON path.")
    parser.add_argument("--plot-root", default=str(DEFAULT_PLOT_ROOT), help="Directory for diagnostic PNGs.")
    parser.add_argument("--make-plots", action="store_true", help="Create plots for warning/failing models.")
    parser.add_argument("--allow-empty", action="store_true", help="Exit 0 if no NetCDF files are found.")
    return parser.parse_args()


def _paths(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.nc") if not path.name.endswith(".tmp.nc"))


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    paths = _paths(output_root)
    if not paths and not args.allow_empty:
        print(f"No NetCDF files found under {output_root}")
        return 1

    rows = []
    plot_root = Path(args.plot_root)
    for path in paths:
        try:
            with xr.open_dataset(path) as ds:
                result = validate_dataset(ds, path)
                rows.append(result_to_row(result, ds))
                if args.make_plots and result.status != "pass":
                    run_id = result.run_id or path.stem
                    for check_name in failed_check_names(result):
                        check_dir = plot_root / f"check_{check_name}"
                        make_qc_plot(ds, result, check_dir / f"{run_id}_diagnostic.png")
                        make_spectrum_plot(ds, result, check_dir / f"{run_id}_spectrum.png")
        except Exception as exc:
            from aurora_grid.qc import QCResult

            result = QCResult(file_path=str(path), storage_level="failed", metrics={"open_error": str(exc)})
            rows.append(result_to_row(result, None))

    write_summary(rows, Path(args.out_csv), Path(args.out_json))
    failed = sum(1 for row in rows if row["status"] in {"fail", "rerun_recommended"})
    warnings = sum(1 for row in rows if row["status"] == "warning")
    print(f"validated_files: {len(rows)}")
    print(f"failed: {failed}")
    print(f"warnings: {warnings}")
    print(f"qc_summary_csv: {args.out_csv}")
    print(f"qc_summary_json: {args.out_json}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
