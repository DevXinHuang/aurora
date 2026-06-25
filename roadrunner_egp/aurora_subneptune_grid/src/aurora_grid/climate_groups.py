from __future__ import annotations

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
    }
)


def climate_group_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
    """Hashable key for rows that share one converged PT profile."""
    keys = sorted(key for key in row if key not in CLIMATE_GROUP_EXCLUDE)
    return tuple(row[key] for key in keys)


def assign_climate_group_indices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add ``climate_group_index`` to each manifest row in stable order."""
    mapping: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = climate_group_tuple(row)
        if key not in mapping:
            mapping[key] = len(mapping)
        row["climate_group_index"] = mapping[key]
    return rows


def count_climate_groups(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    return max(int(row["climate_group_index"]) for row in rows) + 1
