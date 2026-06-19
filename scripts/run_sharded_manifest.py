#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
GRID_ROOT = REPO_ROOT / "roadrunner_egp" / "aurora_subneptune_grid"
SRC_ROOT = GRID_ROOT / "src"
ROADRUNNER_ROOT = REPO_ROOT / "roadrunner_egp"

for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.run_one import run_one  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one shard of an Aurora manifest.")
    parser.add_argument("--manifest", required=True, help="Manifest CSV path.")
    parser.add_argument("--output-dir", required=True, help="Directory for per-run NetCDF files.")
    parser.add_argument("--shard-id", type=int, required=True, help="This shard index.")
    parser.add_argument("--n-shards", type=int, required=True, help="Total number of shards.")
    return parser.parse_args()


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "run_index" not in reader.fieldnames:
            raise ValueError(f"Manifest {path} must include a run_index column.")
        return list(reader)


def main() -> int:
    args = parse_args()
    if args.n_shards <= 0:
        raise ValueError("--n-shards must be positive.")
    if args.shard_id < 0 or args.shard_id >= args.n_shards:
        raise ValueError("--shard-id must satisfy 0 <= shard-id < n-shards.")

    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = _read_manifest(manifest_path)
    shard_rows = rows[args.shard_id :: args.n_shards]
    print(
        f"[SHARD] shard_id={args.shard_id} n_shards={args.n_shards} "
        f"assigned_rows={len(shard_rows)} manifest_rows={len(rows)}",
        flush=True,
    )

    failures = 0
    for row in shard_rows:
        run_index = int(row["run_index"])
        output_path = output_dir / f"run_{run_index:07d}.nc"
        row = dict(row)
        row["output_nc"] = str(output_path)

        if output_path.exists():
            print(f"[SKIP] run_index={run_index} output={output_path}", flush=True)
            continue

        print(f"[RUN] run_index={run_index} output={output_path}", flush=True)
        try:
            status = run_one(row, overwrite=False, dry_run=False)
            final_path = Path(status.get("output_nc", output_path))
            if final_path.suffix != ".nc" or not final_path.exists():
                raise RuntimeError(f"Expected .nc output was not created: {final_path}")
            print(f"[DONE] run_index={run_index} output={final_path}", flush=True)
        except Exception as exc:
            failures += 1
            print(f"[FAIL] run_index={run_index} error={exc!r}", flush=True)

    print(f"[SUMMARY] shard_id={args.shard_id} failures={failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
