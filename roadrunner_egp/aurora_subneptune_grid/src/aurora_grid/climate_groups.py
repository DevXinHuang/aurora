from __future__ import annotations

import hashlib
import json
from typing import Any

# Manifest fields that vary only with viewing geometry or bookkeeping — not climate state.
CLIMATE_GROUP_EXCLUDE = frozenset(
    {
        "run_index",
        "run_id",
        "output_nc",
        "status",
        "phase_deg",
        "cahoy_reference_name",
        "climate_group_index",
        "climate_group_key",
    }
)


def _group_exclude(spectrum_axes: tuple[str, ...]) -> frozenset[str]:
    excluded = set(CLIMATE_GROUP_EXCLUDE)
    excluded.update(spectrum_axes)
    if "planet_radius_rearth" in spectrum_axes:
        excluded.add("planet_mass_mearth")
    return frozenset(excluded)


def climate_group_tuple(
    row: dict[str, Any],
    spectrum_axes: tuple[str, ...] = ("phase_deg",),
) -> tuple[tuple[str, Any], ...]:
    """Hashable key for rows that share one converged PT profile."""
    excluded = _group_exclude(spectrum_axes)
    keys = sorted(key for key in row if key not in excluded)
    return tuple((key, row[key]) for key in keys)


def climate_group_key(
    row: dict[str, Any],
    spectrum_axes: tuple[str, ...] = ("phase_deg",),
) -> str:
    payload = climate_group_tuple(row, spectrum_axes=spectrum_axes)
    encoded = json.dumps(payload, sort_keys=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def assign_climate_group_indices(
    rows: list[dict[str, Any]],
    spectrum_axes: tuple[str, ...] = ("phase_deg",),
) -> list[dict[str, Any]]:
    """Add stable climate indices and identity keys to manifest rows."""
    mapping: dict[tuple[tuple[str, Any], ...], int] = {}
    for row in rows:
        group_tuple = climate_group_tuple(row, spectrum_axes=spectrum_axes)
        if group_tuple not in mapping:
            mapping[group_tuple] = len(mapping)
        row["climate_group_index"] = mapping[group_tuple]
        row["climate_group_key"] = climate_group_key(row, spectrum_axes=spectrum_axes)
    return rows


def count_climate_groups(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    return max(int(row["climate_group_index"]) for row in rows) + 1
