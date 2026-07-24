from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from .parameters import resolve_repo_path

_MAX_JSON_ARRAY_ELEMS = 64


def _json_safe(value: Any) -> Any:
    """Convert PICASO diagnostics into JSON-serializable Python objects."""
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return []
        if value.size <= _MAX_JSON_ARRAY_ELEMS:
            return np.asarray(value).tolist()
        flat = np.asarray(value, dtype=float).ravel()
        finite = flat[np.isfinite(flat)]
        summary: dict[str, Any] = {"shape": list(value.shape), "dtype": str(value.dtype)}
        if finite.size:
            summary.update(
                {
                    "min": float(np.min(finite)),
                    "max": float(np.max(finite)),
                    "mean": float(np.mean(finite)),
                }
            )
        return summary
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def climate_cache_path(output_root: str | Path, climate_group_index: int) -> Path:
    root = resolve_repo_path(output_root)
    cache_dir = root / "climate_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"climate_{int(climate_group_index):02d}.npz"


def climate_case_path(cache_path: str | Path) -> Path:
    path = Path(cache_path)
    return path.with_name(f"{path.stem}_case.pkl")


def save_climate_cache(
    path: str | Path,
    *,
    climate_group_index: int,
    pressure: np.ndarray,
    temperature: np.ndarray,
    selected_ck_file: str,
    diagnostics: dict[str, Any],
    row: dict[str, Any],
    cl_run: Any | None = None,
) -> Path:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = _json_safe(
        {
            "climate_group_index": int(climate_group_index),
            "climate_group_key": str(row.get("climate_group_key", "")),
            "selected_ck_file": str(selected_ck_file),
            "cahoy_planet_type": row.get("cahoy_planet_type", ""),
            "cahoy_metallicity_label": row.get("cahoy_metallicity_label", ""),
            "semi_major_au": float(row["semi_major_au"]),
            "cahoy_cloud_note": row.get("cahoy_cloud_note", ""),
            "diagnostics": diagnostics,
        }
    )
    np.savez_compressed(
        cache_path,
        pressure=np.asarray(pressure, dtype=float),
        temperature=np.asarray(temperature, dtype=float),
        metadata_json=np.asarray(json.dumps(metadata)),
    )
    if cl_run is not None:
        case_path = climate_case_path(cache_path)
        with case_path.open("wb") as handle:
            pickle.dump(cl_run, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return cache_path


def load_climate_cache(
    path: str | Path,
    *,
    expected_climate_group_key: str | None = None,
) -> dict[str, Any]:
    cache_path = Path(path)
    if not cache_path.exists():
        raise FileNotFoundError(f"Climate cache not found: {cache_path}")

    with np.load(cache_path, allow_pickle=False) as data:
        metadata = json.loads(str(data["metadata_json"]))
        if expected_climate_group_key not in (None, ""):
            actual_key = str(metadata.get("climate_group_key", ""))
            if actual_key != str(expected_climate_group_key):
                raise ValueError(
                    f"Stale climate cache {cache_path}: climate_group_key "
                    f"{actual_key or '<missing>'!r} does not match expected "
                    f"{expected_climate_group_key!r}. Regenerate the cache."
                )
        loaded = {
            "pressure": np.asarray(data["pressure"], dtype=float),
            "temperature": np.asarray(data["temperature"], dtype=float),
            "selected_ck_file": metadata["selected_ck_file"],
            "climate_group_index": int(metadata["climate_group_index"]),
            "metadata": metadata,
        }
    case_path = climate_case_path(cache_path)
    if case_path.exists():
        with case_path.open("rb") as handle:
            loaded["cl_run"] = pickle.load(handle)
    return loaded
