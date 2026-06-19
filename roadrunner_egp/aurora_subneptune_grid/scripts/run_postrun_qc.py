#!/usr/bin/env python
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, GRID_ROOT.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.qc.triage_app import run_browser_triage


DEFAULT_OUTPUT_ROOT = GRID_ROOT / "data" / "grid_runs"
DEFAULT_QC_SUMMARY = GRID_ROOT / "data" / "qc" / "reports" / "qc_summary.csv"
DEFAULT_QC_JSON = GRID_ROOT / "data" / "qc" / "reports" / "qc_summary.json"
DEFAULT_QC_FLAGS = GRID_ROOT / "data" / "qc" / "reports" / "qc_flags.csv"
DEFAULT_PLOT_ROOT = GRID_ROOT / "data" / "qc" / "plots"
DEFAULT_TRIAGE = GRID_ROOT / "data" / "qc" / "triage_decisions.csv"
DEFAULT_RERUN = GRID_ROOT / "data" / "rerun" / "rerun_manifest.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AURORA post-run QC, plot generation, triage, and rerun-manifest refresh.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Directory containing per-run NetCDF files.")
    parser.add_argument("--grid-manifest", help="Original grid manifest CSV. Required to refresh a rerun manifest.")
    parser.add_argument("--qc-summary", default=str(DEFAULT_QC_SUMMARY), help="Output qc_summary.csv path.")
    parser.add_argument("--qc-json", default=str(DEFAULT_QC_JSON), help="Output qc_summary.json path.")
    parser.add_argument("--qc-flags", default=str(DEFAULT_QC_FLAGS), help="Output qc_flags.csv path.")
    parser.add_argument("--plot-root", default=str(DEFAULT_PLOT_ROOT), help="QC plot root.")
    parser.add_argument("--triage-decisions", default=str(DEFAULT_TRIAGE), help="Browser triage decisions CSV.")
    parser.add_argument("--rerun-out", default=str(DEFAULT_RERUN), help="Output rerun manifest path.")
    parser.add_argument("--no-plots", action="store_true", help="Skip diagnostic/spectrum plot generation.")
    parser.add_argument("--plot-all", action="store_true", help="Generate plots for passing runs too.")
    parser.add_argument("--serve", action="store_true", help="Launch browser triage after validation/plot generation.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for browser triage.")
    parser.add_argument("--port", type=int, default=8765, help="Port for browser triage.")
    parser.add_argument("--no-browser", action="store_true", help="With --serve, print the URL but do not auto-open a browser.")
    parser.add_argument("--allow-empty", action="store_true", help="Exit 0 if no NetCDF files are found.")
    return parser.parse_args()


def _run_validate(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(GRID_ROOT / "scripts" / "validate_grid_outputs.py"),
        "--output-root",
        args.output_root,
        "--out-csv",
        args.qc_summary,
        "--out-json",
        args.qc_json,
        "--out-flags",
        args.qc_flags,
        "--plot-root",
        args.plot_root,
    ]
    if not args.no_plots:
        command.append("--make-plots")
    if args.plot_all:
        command.append("--plot-all")
    if args.allow_empty:
        command.append("--allow-empty")
    return subprocess.run(command, check=False).returncode


def _run_rerun_manifest(args: argparse.Namespace) -> int:
    if not args.grid_manifest:
        return 0
    command = [
        sys.executable,
        str(GRID_ROOT / "scripts" / "make_rerun_manifest_from_qc.py"),
        "--grid-manifest",
        args.grid_manifest,
        "--qc-summary",
        args.qc_summary,
        "--triage-decisions",
        args.triage_decisions,
        "--out",
        args.rerun_out,
    ]
    return subprocess.run(command, check=False).returncode


def main() -> int:
    args = parse_args()
    validation_code = _run_validate(args)

    if args.serve:
        run_browser_triage(
            Path(args.plot_root),
            Path(args.triage_decisions),
            qc_summary=Path(args.qc_summary),
            qc_flags=Path(args.qc_flags),
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )

    rerun_code = _run_rerun_manifest(args)
    if rerun_code:
        return rerun_code
    return validation_code


if __name__ == "__main__":
    raise SystemExit(main())
