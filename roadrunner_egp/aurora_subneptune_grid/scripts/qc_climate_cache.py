#!/usr/bin/env python
"""Run cache-native QC on Stage 1 PICASO climate .npz/.pkl pairs."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = GRID_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from aurora_grid.qc.climate_cache import (
    climate_group_index,
    discover_cache_files,
    validate_cache_paths,
    write_cache_reports,
)


DEFAULT_CACHE_DIR = GRID_ROOT / "outputs" / "aurora_subneptune_v1_dhuang" / "climate_cache"

# Unpickling a PICASO inputs object imports PICASO, which requires its local
# reference-data paths even though the cache QC itself does not use opacities.
REPO_ROOT = GRID_ROOT.parents[1]
LOCAL_REFDATA = REPO_ROOT / "picaso4_reference"
if LOCAL_REFDATA.is_dir():
    os.environ.setdefault("picaso_refdata", str(LOCAL_REFDATA))
    os.environ.setdefault("PYSYN_CDBS", str(LOCAL_REFDATA / "stellar_grids"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, help="Default: CACHE_DIR/qc")
    parser.add_argument("--limit", type=int, help="Validate only the first N .npz files (smoke testing).")
    parser.add_argument(
        "--unpickle-sample",
        type=int,
        default=0,
        help="Actually load N evenly spaced .pkl files. Pair existence is always checked.",
    )
    parser.add_argument("--fail-on-qc", action="store_true", help="Exit nonzero if any cache fails or recommends rerun.")
    return parser.parse_args()


def _sample_indices(paths: list[Path], count: int) -> set[int]:
    if count <= 0 or not paths:
        return set()
    count = min(count, len(paths))
    positions = {round(i * (len(paths) - 1) / max(1, count - 1)) for i in range(count)}
    return {index for pos in positions if (index := climate_group_index(paths[pos])) is not None}


def main() -> int:
    args = parse_args()
    inventory = discover_cache_files(args.cache_dir, limit=args.limit)
    if not inventory.npz_paths:
        raise FileNotFoundError(f"No climate_*.npz files found in {args.cache_dir}")
    output_dir = args.output_dir or args.cache_dir / "qc"
    unpickle_indices = _sample_indices(inventory.npz_paths, args.unpickle_sample)
    summaries, flags = validate_cache_paths(inventory.npz_paths, unpickle_indices=unpickle_indices)
    summary_csv, flags_csv, summary_json = write_cache_reports(summaries, flags, output_dir)

    counts = Counter(str(row["status"]) for row in summaries)
    print(f"cache_dir: {args.cache_dir}")
    print(f"npz_validated: {len(summaries)}")
    print(f"orphan_pickles: {len(inventory.orphan_pkl_paths)}")
    print("status_counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"summary_csv: {summary_csv}")
    print(f"flags_csv: {flags_csv}")
    print(f"summary_json: {summary_json}")
    print(f"rerun_indices: {output_dir / 'rerun_climate_group_indices.txt'}")
    failed = sum(bool(row["rerun_recommended"]) for row in summaries)
    if args.fail_on_qc and (failed or inventory.orphan_pkl_paths):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
