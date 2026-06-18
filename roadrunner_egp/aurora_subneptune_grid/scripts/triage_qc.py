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

from aurora_grid.qc.triage_app import run_tk_triage


DEFAULT_PLOT_ROOT = GRID_ROOT / "data" / "qc" / "plots"
DEFAULT_DECISIONS = GRID_ROOT / "data" / "qc" / "triage_decisions.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Human triage UI for Aurora QC diagnostic plots.")
    parser.add_argument("--plot-root", default=str(DEFAULT_PLOT_ROOT), help="Root containing check_* PNG directories.")
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS), help="Decision CSV path.")
    parser.add_argument("--move-bad", action="store_true", help="Move bad plots to quarantine. Default is non-destructive.")
    parser.add_argument("--quarantine-dir", help="Optional quarantine directory for --move-bad.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_tk_triage(
        Path(args.plot_root),
        Path(args.decisions),
        move_bad=args.move_bad,
        quarantine_dir=Path(args.quarantine_dir) if args.quarantine_dir else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
