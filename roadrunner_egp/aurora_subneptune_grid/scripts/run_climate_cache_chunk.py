#!/usr/bin/env python
"""Converge one climate group and write a reusable PT cache (stage 1)."""

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

from aurora_grid.cahoy_climate_cache import climate_cache_path, save_climate_cache
from aurora_grid.parameters import read_manifest_csv
from aurora_grid.picaso_runner import _system_from_row, wavelength_grid_um


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 1: converge PICASO climate for one climate_group_index.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--climate-group-index", type=int)
    parser.add_argument("--climate-index-map")
    parser.add_argument("--array-task-id", type=int)
    parser.add_argument("--ck-root", default=None)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_climate_group_index(
    climate_group_index: int | None,
    climate_index_map: str | None,
    array_task_id: int | None,
) -> int:
    if climate_index_map:
        if array_task_id is None:
            raise ValueError("--array-task-id is required with --climate-index-map")
        indices = [line.strip() for line in Path(climate_index_map).read_text(encoding="utf-8").splitlines() if line.strip()]
        if array_task_id < 0 or array_task_id >= len(indices):
            raise IndexError(f"Array task ID {array_task_id} is outside index map with {len(indices)} entries")
        return int(indices[array_task_id])
    if climate_group_index is None:
        raise ValueError("Provide --climate-group-index or --climate-index-map with --array-task-id")
    return int(climate_group_index)


def main() -> int:
    args = parse_args()
    from roadrunner.runner import run_picaso_climate_converge_only

    climate_group_index = resolve_climate_group_index(
        args.climate_group_index,
        args.climate_index_map,
        args.array_task_id,
    )

    table = read_manifest_csv(args.manifest)
    matches = [row for row in table.rows if int(row["climate_group_index"]) == climate_group_index]
    if not matches:
        raise ValueError(f"No manifest rows for climate_group_index={climate_group_index}")

    row = dict(matches[0])
    row["phase_deg"] = float(min(float(r["phase_deg"]) for r in matches))
    output_root = str(Path(row["output_nc"]).parent.parent)
    cache_file = climate_cache_path(output_root, climate_group_index)
    if cache_file.exists() and not args.overwrite:
        print(f"skipped_exists: {cache_file}")
        return 0

    system = _system_from_row(row)
    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    climate_out, diagnostics, selected_ck_file, cl_run = run_picaso_climate_converge_only(
        system,
        wavelength_grid_um(row),
        ck_root=args.ck_root,
        cloud_model=cloud_model,
        verbose=True,
    )
    pressure = climate_out.get("pressure")
    temperature = climate_out.get("temperature")
    if pressure is None or temperature is None:
        raise RuntimeError("Climate output missing pressure/temperature for cache.")

    save_climate_cache(
        cache_file,
        climate_group_index=climate_group_index,
        pressure=pressure,
        temperature=temperature,
        selected_ck_file=str(selected_ck_file),
        diagnostics=diagnostics,
        row=row,
        cl_run=cl_run,
    )
    print(f"wrote: {cache_file}")
    print(f"climate_group_index: {climate_group_index}")
    print(f"rows_in_group: {len(matches)}")
    print(f"climate_converged: {diagnostics.get('climate_converged')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
