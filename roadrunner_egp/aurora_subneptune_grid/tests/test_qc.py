from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.qc import QCResult
from aurora_grid.qc.plots import make_qc_plot
from aurora_grid.qc.schema_checks import classify_storage, validate_schema
from aurora_grid.qc.science_checks import validate_science


def toy_dataset() -> xr.Dataset:
    wavelength = np.array([0.5, 0.6, 0.7, 0.8])
    ds = xr.Dataset(
        data_vars={
            "albedo": (("wavelength",), np.array([0.2, 0.25, 0.22, 0.18])),
            "fpfs_reflected": (("wavelength",), np.array([1.0e-8, 1.2e-8, 1.1e-8, 0.9e-8])),
            "fpfs_reflection": (("wavelength",), np.array([1.0e-8, 1.2e-8, 1.1e-8, 0.9e-8])),
        },
        coords={"wavelength": ("wavelength", wavelength, {"units": "micron"})},
        attrs={
            "author": "Aurora",
            "contact": "aurora@example.test",
            "code": "{}",
            "model_name": "toy",
            "run_id": "run-toy",
            "run_index": 1,
            "created_utc": "2026-01-01T00:00:00Z",
            "git_commit": "test",
            "planet_params": "{}",
            "stellar_params": "{}",
            "orbit_params": "{}",
            "cld_params": "{}",
            "grid_params": "{}",
        },
    )
    return ds


def test_schema_validator_catches_missing_wavelength():
    ds = toy_dataset().drop_vars("wavelength")
    flags = validate_schema(ds)
    assert any(flag.severity == "fail" and "missing wavelength" in flag.message for flag in flags)


def test_schema_validator_accepts_spectrum_only_files():
    ds = toy_dataset()
    flags = validate_schema(ds)
    assert not any(flag.severity == "fail" for flag in flags)
    assert classify_storage(ds, flags) == "spectrum_only"


def test_science_validator_catches_nans():
    ds = toy_dataset()
    ds["fpfs_reflected"] = (("wavelength",), np.array([1.0e-8, np.nan, 1.1e-8, 0.9e-8]))
    flags = validate_science(ds)
    assert any(flag.severity == "fail" and "nonfinite" in flag.message for flag in flags)


def test_science_validator_catches_albedo_out_of_range():
    ds = toy_dataset()
    ds["albedo"] = (("wavelength",), np.array([1.2, 1.3, 1.4, 1.5]))
    flags = validate_science(ds)
    assert any(flag.severity == "warning" and "albedo" in flag.message for flag in flags)


def test_pt_validator_catches_nonpositive_pressure():
    ds = toy_dataset()
    ds = ds.assign_coords(pressure=("pressure", np.array([1.0, 0.0, 0.01])))
    ds["temperature"] = (("pressure",), np.array([400.0, 450.0, 500.0]))
    flags = validate_science(ds)
    assert any(flag.severity == "fail" and "nonpositive pressure" in flag.message for flag in flags)


def test_plot_maker_creates_png_for_toy_failed_dataset(tmp_path: Path):
    ds = toy_dataset()
    ds = ds.assign_coords(pressure=("pressure", np.array([1.0, 0.1, 0.01])))
    ds["temperature"] = (("pressure",), np.array([400.0, 450.0, 500.0]))
    ds["qc_adiabat"] = (("pressure",), np.array([1.0, 1.0, 1.0]))
    ds["qc_dtdp"] = (("pressure",), np.array([0.8, 1.2, 0.7]))
    ds["qc_adiabat_pressure"] = (("pressure",), np.array([1.0, 0.1, 0.01]))
    result = QCResult(run_id="run-toy", storage_level="spectrum_only")
    out = make_qc_plot(ds, result, tmp_path / "diagnostic.png")
    assert out.exists()
    assert out.stat().st_size > 0


def test_rerun_manifest_joins_qc_summary_back_to_grid_manifest(tmp_path: Path):
    manifest = tmp_path / "grid_manifest.csv"
    qc = tmp_path / "qc_summary.csv"
    triage = tmp_path / "triage_decisions.csv"
    out = tmp_path / "rerun_manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_index", "run_id", "output_nc"])
        writer.writeheader()
        writer.writerow({"run_index": "7", "run_id": "run-0007", "output_nc": "run.nc"})
    with qc.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_index", "run_id", "rerun_recommended", "fail_reasons", "warning_reasons"])
        writer.writeheader()
        writer.writerow({"run_index": "7", "run_id": "run-0007", "rerun_recommended": "True", "fail_reasons": "bad spectrum", "warning_reasons": ""})
    with triage.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["plot_path", "decision", "rerun_recommended", "notes"])
        writer.writeheader()

    subprocess.check_call(
        [
            sys.executable,
            str(GRID_ROOT / "scripts" / "make_rerun_manifest_from_qc.py"),
            "--grid-manifest",
            str(manifest),
            "--qc-summary",
            str(qc),
            "--triage-decisions",
            str(triage),
            "--out",
            str(out),
        ]
    )
    with out.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-0007"
    assert rows[0]["qc_rerun_reasons"] == "bad spectrum"
