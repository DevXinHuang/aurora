from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .parameters import REPO_ROOT, resolve_repo_path


def climate_cache_path(output_root: str | Path, climate_group_index: int) -> Path:
    root = resolve_repo_path(output_root)
    cache_dir = root / "climate_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"climate_{int(climate_group_index):02d}.npz"


def save_climate_cache(
    path: str | Path,
    *,
    climate_group_index: int,
    pressure: np.ndarray,
    temperature: np.ndarray,
    selected_ck_file: str,
    diagnostics: dict[str, Any],
    row: dict[str, Any],
) -> Path:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "climate_group_index": int(climate_group_index),
        "selected_ck_file": str(selected_ck_file),
        "cahoy_planet_type": row.get("cahoy_planet_type", ""),
        "cahoy_metallicity_label": row.get("cahoy_metallicity_label", ""),
        "semi_major_au": float(row["semi_major_au"]),
        "cahoy_cloud_note": row.get("cahoy_cloud_note", ""),
        "diagnostics": diagnostics,
    }
    np.savez_compressed(
        cache_path,
        pressure=np.asarray(pressure, dtype=float),
        temperature=np.asarray(temperature, dtype=float),
        metadata_json=np.asarray(json.dumps(metadata)),
    )
    return cache_path


def load_climate_cache(path: str | Path) -> dict[str, Any]:
    cache_path = Path(path)
    if not cache_path.exists():
        raise FileNotFoundError(f"Climate cache not found: {cache_path}")

    with np.load(cache_path, allow_pickle=False) as data:
        metadata = json.loads(str(data["metadata_json"]))
        return {
            "pressure": np.asarray(data["pressure"], dtype=float),
            "temperature": np.asarray(data["temperature"], dtype=float),
            "selected_ck_file": metadata["selected_ck_file"],
            "climate_group_index": int(metadata["climate_group_index"]),
            "metadata": metadata,
        }
