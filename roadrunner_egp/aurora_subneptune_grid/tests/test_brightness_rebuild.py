from __future__ import annotations

import csv
import json
import pickle
from pathlib import Path

import numpy as np

from aurora_grid.qc.brightness_rebuild import (
    EXPECTED_BRIGHTNESS_POINTS,
    attach_qc_metadata,
    create_survival_reports,
    load_parameter_records,
    validate_brightness_case,
    validate_sidecar,
)


def _signature(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _write_source_pair(tmp_path: Path, index: int = 7) -> tuple[Path, Path]:
    npz = tmp_path / f"climate_{index}.npz"
    np.savez_compressed(npz, pressure=np.arange(2), temperature=np.arange(2), metadata_json=np.asarray("{}"))
    pkl = tmp_path / f"climate_{index}_case.pkl"
    with pkl.open("wb") as handle:
        pickle.dump({"case": index}, handle)
    return npz, pkl


def _write_sidecar(path: Path, source_npz: Path, source_pkl: Path, *, max_brightness: float = 500.0) -> None:
    pressure = np.logspace(-6, 2, 6)
    temperature = np.linspace(250.0, 800.0, 6)
    brightness = np.linspace(200.0, max_brightness, EXPECTED_BRIGHTNESS_POINTS)
    metadata = {
        "sidecar_schema_version": 1,
        "climate_group_index": 7,
        "climate_converged": True,
        "opacity_filename": "test.hdf5",
        "picaso_version": "4.0.1",
        "source_npz": _signature(source_npz),
        "source_pkl": _signature(source_pkl),
        "original_schema_warnings": [],
    }
    np.savez_compressed(
        path,
        pressure=pressure,
        temperature=temperature,
        qc_dtdp=np.full(5, 0.1),
        qc_adiabat=np.full(5, 0.2),
        qc_adiabat_pressure=np.sqrt(pressure[:-1] * pressure[1:]),
        fnet_irfnet=np.zeros(6),
        brightness_wavelength_um=np.geomspace(0.3, 15.0, EXPECTED_BRIGHTNESS_POINTS),
        brightness_temperature_k=brightness,
        metadata_json=np.asarray(json.dumps(metadata)),
    )


def test_sidecar_validation_and_brightness_depth_qc(tmp_path: Path) -> None:
    source_npz, source_pkl = _write_source_pair(tmp_path)
    sidecar = tmp_path / "climate_000007_diagnostics.npz"
    _write_sidecar(sidecar, source_npz, source_pkl)
    assert validate_sidecar(sidecar, source_npz=source_npz, source_pkl=source_pkl).valid
    result, row, flags = validate_brightness_case(sidecar, source_npz=source_npz, source_pkl=source_pkl)
    assert result.status == "pass"
    assert row["n_brightness_points"] == EXPECTED_BRIGHTNESS_POINTS
    assert not flags
    assert not validate_sidecar(sidecar, source_npz=source_npz, source_pkl=source_pkl, require_qc=True).valid
    attach_qc_metadata(sidecar, result)
    assert validate_sidecar(sidecar, source_npz=source_npz, source_pkl=source_pkl, require_qc=True).valid

    _write_sidecar(sidecar, source_npz, source_pkl, max_brightness=800.0)
    result, row, flags = validate_brightness_case(sidecar, source_npz=source_npz, source_pkl=source_pkl)
    assert result.status == "rerun_recommended"
    assert row["brightness_depth_rerun"] is True
    assert any(flag["check"] == "brightness_temperature" for flag in flags)


def test_sidecar_rejects_nonfinite_brightness(tmp_path: Path) -> None:
    source_npz, source_pkl = _write_source_pair(tmp_path)
    sidecar = tmp_path / "climate_000007_diagnostics.npz"
    _write_sidecar(sidecar, source_npz, source_pkl)
    with np.load(sidecar, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    arrays["brightness_temperature_k"] = np.asarray(arrays["brightness_temperature_k"], dtype=float)
    arrays["brightness_temperature_k"][5] = np.nan
    np.savez_compressed(sidecar, **arrays)
    validation = validate_sidecar(sidecar, source_npz=source_npz, source_pkl=source_pkl)
    assert not validation.valid
    assert "nonfinite" in validation.message


def test_parameter_records_require_one_row_per_climate(tmp_path: Path) -> None:
    path = tmp_path / "parameters.csv"
    columns = [
        "climate_group_index",
        "star_teff_k",
        "star_radius_rsun",
        "planet_radius_rearth",
        "planet_mass_mearth",
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
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({column: 7 if column == "climate_group_index" else "1.5" for column in columns})
    records = load_parameter_records(path)
    assert set(records) == {7}
    assert records[7]["star_teff_k"] == 1.5


def test_survival_reports_transition_and_brightness_downgrade(tmp_path: Path) -> None:
    old = [
        {"climate_group_index": 1, "status": "pass"},
        {"climate_group_index": 2, "status": "warning"},
    ]
    new = [
        {"climate_group_index": 1, "status": "rerun_recommended"},
        {"climate_group_index": 2, "status": "warning"},
    ]
    flags = [
        {
            "climate_group_index": 1,
            "check": "brightness_temperature",
            "severity": "rerun_recommended",
        }
    ]
    report = create_survival_reports(old, new, flags, tmp_path)
    assert report["newly_downgraded_by_brightness_count"] == 1
    strict = report["survival"][0]
    assert strict["before_count"] == 1
    assert strict["after_count"] == 0
    assert (tmp_path / "old_to_new_status_transition.csv").is_file()
