#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
REPO_ROOT = ROADRUNNER_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.parameters import create_manifest_dataframe, expected_grid_size, load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the Aurora sub-Neptune grid manifest.")
    parser.add_argument("--config", required=True, help="Path to a YAML grid config.")
    parser.add_argument("--out", required=True, help="Output manifest CSV path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    manifest = create_manifest_dataframe(config)

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(output_path, index=False)

    print(f"model_name: {config['model_name']}")
    print(f"total_rows: {len(manifest)}")
    print(f"expected_rows: {expected_grid_size(config)}")
    print(f"output_root: {config['output_root']}")
    print(f"manifest: {output_path}")
    print(f"duplicate_run_id: {manifest.has_duplicate('run_id')}")
    print(f"duplicate_output_nc: {manifest.has_duplicate('output_nc')}")
    print("first_5_rows:")
    print(manifest.head(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
