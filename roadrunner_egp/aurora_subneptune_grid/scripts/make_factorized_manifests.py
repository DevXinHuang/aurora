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

from aurora_grid.coupled_grid import load_grid_config
from aurora_grid.factorization import create_factorized_manifests, write_factorized_manifests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create factorized Aurora manifests (full, climate, spectrum, map).")
    parser.add_argument("--config", required=True, help="Path to a factorized YAML grid config.")
    parser.add_argument("--out-dir", required=True, help="Output directory for manifest CSV files.")
    parser.add_argument(
        "--prefix",
        help="Filename prefix (default: model_name from config).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_grid_config(args.config)
    manifests = create_factorized_manifests(config)
    prefix = args.prefix or str(config["model_name"])
    paths = write_factorized_manifests(manifests, args.out_dir, prefix)

    print(f"model_name: {config['model_name']}")
    print(f"full_rows: {len(manifests.full)}")
    print(f"climate_rows: {len(manifests.climate)}")
    print(f"spectrum_rows: {len(manifests.spectrum)}")
    print(f"map_rows: {len(manifests.climate_spectrum_map)}")
    for label, path in paths.items():
        print(f"{label}_manifest: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
