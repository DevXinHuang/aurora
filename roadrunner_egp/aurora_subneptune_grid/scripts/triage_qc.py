#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, GRID_ROOT.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.qc.triage_app import run_browser_triage


DEFAULT_PLOT_ROOT = GRID_ROOT / "data" / "qc" / "plots"
DEFAULT_DECISIONS = GRID_ROOT / "data" / "qc" / "triage_decisions.csv"
DEFAULT_QC_SUMMARY = GRID_ROOT / "data" / "qc" / "reports" / "qc_summary.csv"
DEFAULT_QC_FLAGS = GRID_ROOT / "data" / "qc" / "reports" / "qc_flags.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Human triage UI for Aurora QC diagnostic plots.")
    parser.add_argument("--plot-root", default=str(DEFAULT_PLOT_ROOT), help="Root containing check_* PNG directories.")
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS), help="Decision CSV path.")
    parser.add_argument("--qc-summary", default=str(DEFAULT_QC_SUMMARY), help="QC summary CSV linked from the browser UI.")
    parser.add_argument("--qc-flags", default=str(DEFAULT_QC_FLAGS), help="QC flags CSV linked from the browser UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for the browser triage server.")
    parser.add_argument("--port", type=int, default=8765, help="Port for the browser triage server.")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL but do not auto-open a browser.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    qc_summary = Path(args.qc_summary)
    qc_flags = Path(args.qc_flags)
    return run_browser_triage(
        Path(args.plot_root),
        Path(args.decisions),
        qc_summary=qc_summary if qc_summary.exists() else None,
        qc_flags=qc_flags if qc_flags.exists() else None,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
