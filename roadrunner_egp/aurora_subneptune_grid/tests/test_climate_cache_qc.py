from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

from aurora_grid.qc.climate_cache import (
    CACHE_SUMMARY_COLUMNS,
    discover_cache_files,
    validate_cache_file,
    write_cache_reports,
)


def _write_cache(path: Path, *, converged: bool = True, with_pickle: bool = True) -> None:
    pressure = np.logspace(-6, 1, 6)
    temperature = np.linspace(250.0, 800.0, 6)
    diagnostics = {
        "climate_converged": converged,
        "qc_dtdp": [0.1] * 5,
        "qc_adiabat": [0.2] * 5,
        "fnet_irfnet": [0.0] * 6,
        "schema_warnings": [],
    }
    metadata = {
        "climate_group_index": int(path.stem.split("_")[-1]),
        "selected_ck_file": "test.hdf5",
        "diagnostics": diagnostics,
    }
    np.savez_compressed(
        path,
        pressure=pressure,
        temperature=temperature,
        metadata_json=np.asarray(json.dumps(metadata)),
    )
    if with_pickle:
        with path.with_name(f"{path.stem}_case.pkl").open("wb") as handle:
            pickle.dump({"case": "test"}, handle)


def test_cache_qc_passes_complete_pair(tmp_path: Path) -> None:
    path = tmp_path / "climate_7.npz"
    _write_cache(path)
    result, row = validate_cache_file(path, unpickle=True)
    assert result.status == "pass"
    assert row["pkl_exists"] is True
    assert row["pkl_unpickle_ok"] is True
    assert row["climate_group_index"] == 7


def test_cache_qc_marks_missing_pickle_and_nonconvergence(tmp_path: Path) -> None:
    path = tmp_path / "climate_8.npz"
    _write_cache(path, converged=False, with_pickle=False)
    result, row = validate_cache_file(path)
    assert result.rerun_recommended is True
    assert row["status"] == "rerun_recommended"
    assert "matching PICASO case pickle is missing" in row["fail_reasons"]
    assert "PICASO climate did not converge" in row["fail_reasons"]


def test_discovery_reports_orphan_pickle(tmp_path: Path) -> None:
    _write_cache(tmp_path / "climate_2.npz")
    with (tmp_path / "climate_99_case.pkl").open("wb") as handle:
        pickle.dump({}, handle)
    inventory = discover_cache_files(tmp_path)
    assert [path.name for path in inventory.npz_paths] == ["climate_2.npz"]
    assert [path.name for path in inventory.orphan_pkl_paths] == ["climate_99_case.pkl"]


def test_reports_write_rerun_index_map(tmp_path: Path) -> None:
    summaries = [
        {"climate_group_index": 8, "rerun_recommended": True},
        {"climate_group_index": 2, "rerun_recommended": False},
        {"climate_group_index": 5, "rerun_recommended": True},
    ]
    complete = [
        {column: row.get(column, "") for column in CACHE_SUMMARY_COLUMNS}
        for row in summaries
    ]
    write_cache_reports(complete, [], tmp_path)
    assert (tmp_path / "rerun_climate_group_indices.txt").read_text(encoding="utf-8") == "5\n8\n"
