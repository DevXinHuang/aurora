#!/usr/bin/env python3
"""Extract one invariant parameter row per selected climate group from a grid manifest."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


PARAMETER_COLUMNS = [
    "climate_group_index",
    "climate_group_key",
    "star_teff_k",
    "star_radius_rsun",
    "climate_reference_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_model",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "semi_major_au",
    "equilibrium_temperature_k",
    "picaso_tint_k",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--indices", type=Path, required=True, help="One climate_group_index per line.")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    wanted = {int(line) for line in args.indices.read_text(encoding="utf-8").splitlines() if line.strip()}
    selected: dict[int, dict[str, str]] = {}
    with args.manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(PARAMETER_COLUMNS).difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"manifest is missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            index = int(row["climate_group_index"])
            if index not in wanted:
                continue
            compact = {column: row[column] for column in PARAMETER_COLUMNS}
            previous = selected.get(index)
            if previous is None:
                selected[index] = compact
            elif previous != compact:
                changed = [column for column in PARAMETER_COLUMNS if previous[column] != compact[column]]
                raise ValueError(f"climate {index} has phase-dependent parameter values: {changed}")
    missing_indices = sorted(wanted.difference(selected))
    if missing_indices:
        raise ValueError(f"manifest lacks {len(missing_indices)} requested climates; sample={missing_indices[:10]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PARAMETER_COLUMNS)
        writer.writeheader()
        writer.writerows(selected[index] for index in sorted(selected))
    print(f"parameter_rows: {len(selected)}")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
