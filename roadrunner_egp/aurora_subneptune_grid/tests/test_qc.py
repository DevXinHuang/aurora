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

from aurora_grid.io.netcdf_schema import build_aurora_run_dataset
from aurora_grid.qc import EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE, QCResult
from aurora_grid.qc.plots import (
    _diagnostic_title,
    _plot_adiabat,
    _plot_brightness_temperature,
    _plot_flux_balance,
    _plot_pt,
    make_qc_plot,
)
from aurora_grid.qc.report import flags_to_rows, result_to_row, validate_dataset, write_flags, write_summary
from aurora_grid.qc.schema_checks import classify_storage, validate_schema
from aurora_grid.qc.science_checks import validate_science
from aurora_grid.qc.triage_app import (
    discover_models,
    discover_plot_folders,
    load_decisions,
    record_decision,
    safe_plot_path,
    undo_decision,
)


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


def aurora_schema_row() -> dict[str, object]:
    return {
        "run_index": 9,
        "model_name": "schema-qc-test",
        "run_id": "run-schema-qc",
        "star_teff_k": 3500.0,
        "star_radius_rsun": 0.45,
        "stellar_luminosity_lsun": 0.03,
        "planet_radius_rearth": 2.0,
        "gravity_ms2": 10.0,
        "metallicity_xsolar": 10.0,
        "c_to_o_xsolar": 1.0,
        "c_to_o_picaso_tag": "100",
        "kzz_cm2_s": 1.0e9,
        "logkzz": 9.0,
        "cloud_fraction": 1.0,
        "cloud_model": "virga",
        "fsed": 3.0,
        "insolation_searth": 0.7,
        "phase_deg": 60.0,
        "semi_major_au": 0.2,
        "equilibrium_temperature_k": 500.0,
        "picaso_tint_k": 500.0,
        "output_nc": "run.nc",
        "author": "Aurora",
        "contact": "aurora@example.test",
        "project": "Aurora",
        "notes": "test",
        "code": "{}",
        "picaso_tint_mode": "equilibrium",
        "picaso_tint_fixed_k": 1000.0,
        "picaso_tint_floor_k": 100.0,
        "netcdf_optional_variables": "[]",
        "netcdf_strict_optional": False,
        "source_notebook_reference": "notebook.ipynb",
    }


def aurora_model_output(**extra: object) -> dict[str, object]:
    wavelength = np.array([0.5, 0.6, 0.7, 0.8])
    pressure = np.array([1.0e-3, 1.0e-2, 1.0e-1])
    output = {
        "wavelength_um": wavelength,
        "fpfs_reflection": np.array([1.0e-8, 1.2e-8, 1.1e-8, 0.9e-8]),
        "albedo": np.array([0.2, 0.25, 0.22, 0.18]),
        "fpfs_emission": np.array([1.0e-10, 1.1e-10, 1.2e-10, 1.3e-10]),
        "absolute_flux_reflected": np.array([1.0, 1.1, 1.2, 1.3]),
        "absolute_flux_thermal": np.array([0.1, 0.2, 0.3, 0.4]),
        "pt_profile": {
            "pressure": pressure,
            "temperature": np.array([400.0, 450.0, 500.0]),
            "H2": np.array([0.84, 0.84, 0.84]),
            "He": np.array([0.15, 0.15, 0.15]),
            "H2O": np.array([0.01, 0.01, 0.01]),
        },
        "cloud_profile": {
            "wavelength_um": wavelength,
            "opd": np.ones((2, 4)) * 0.2,
            "w0": np.ones((2, 4)) * 0.5,
            "g0": np.ones((2, 4)) * 0.1,
        },
        "picaso_metadata": {"dry_run": True, "cloud_model": "virga"},
    }
    output.update(extra)
    return output


def _new_schema_dataset(**extra: object) -> xr.Dataset:
    return build_aurora_run_dataset(aurora_model_output(**extra), aurora_schema_row())


def _axes():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    return fig, ax, plt


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


def test_new_schema_qc_adiabat_panel_plots_exact_diagnostics():
    ds = _new_schema_dataset(
        qc_adiabat=np.array([1.0, 1.0]),
        qc_dtdp=np.array([0.8, 1.2]),
        qc_adiabat_pressure=np.array([0.01, 0.1]),
    )
    fig, ax, plt = _axes()
    try:
        assert _plot_adiabat(ax, ds)
        assert ax.lines
    finally:
        plt.close(fig)


def test_new_schema_flux_balance_panel_plots_exact_diagnostics():
    ds = _new_schema_dataset(fnet_irfnet=np.array([1.0e-4, -2.0e-4, 3.0e-4]))
    fig, ax, plt = _axes()
    try:
        assert _plot_flux_balance(ax, ds)
        assert ax.lines
    finally:
        plt.close(fig)


def test_new_schema_brightness_temperature_panel_plots_exact_diagnostics():
    ds = _new_schema_dataset(
        qc_brightness_temperature=np.array([350.0, 360.0, 365.0, 370.0]),
        qc_brightness_wavelength=np.array([0.5, 0.6, 0.7, 0.8]),
    )
    fig, ax, plt = _axes()
    try:
        assert _plot_brightness_temperature(ax, ds)
        assert ax.lines
    finally:
        plt.close(fig)


def test_new_schema_brightness_temperature_panel_draws_bottom_temperature_line():
    ds = _new_schema_dataset(
        qc_brightness_temperature=np.array([350.0, 360.0, 365.0, 370.0]),
        qc_brightness_wavelength=np.array([0.5, 0.6, 0.7, 0.8]),
    )
    fig, ax, plt = _axes()
    try:
        assert _plot_brightness_temperature(ax, ds)
        assert len(ax.lines) >= 2
    finally:
        plt.close(fig)


def test_new_schema_pressure_bar_temperature_k_panel_plots_pt_profile():
    ds = _new_schema_dataset()
    fig, ax, plt = _axes()
    try:
        assert _plot_pt(ax, ds)
        assert ax.lines
    finally:
        plt.close(fig)


def test_new_schema_without_exact_climate_qc_passes_schema_with_warning():
    ds = _new_schema_dataset()

    schema_flags = validate_schema(ds)
    result = validate_dataset(ds)

    assert not any(flag.severity == "fail" for flag in schema_flags)
    assert not any(flag.severity == "fail" for flag in result.flags)
    assert any(
        flag.check == "picaso_diagnostics"
        and flag.severity == "warning"
        and flag.message == EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE
        for flag in result.flags
    )


def test_exact_adiabat_violation_emits_qc_flag():
    ds = _new_schema_dataset(
        qc_adiabat=np.array([1.0, 1.0]),
        qc_dtdp=np.array([1.1, 0.9]),
        qc_adiabat_pressure=np.array([0.01, 0.1]),
    )

    flags = validate_science(ds)

    assert any(flag.check == "adiabat" and flag.metric == "max_adiabat_ratio" for flag in flags)


def test_exact_upper_atmosphere_flux_balance_emits_qc_flag():
    ds = _new_schema_dataset(fnet_irfnet=np.array([2.0e-3, 5.0e-4, 8.0e-4]))

    flags = validate_science(ds)

    assert any(flag.check == "flux_balance" and flag.severity == "warning" for flag in flags)


def test_exact_brightness_temperature_bottom_visibility_emits_rerun_flag():
    ds = _new_schema_dataset(
        qc_brightness_temperature=np.array([350.0, 505.0, 365.0, 370.0]),
        qc_brightness_wavelength=np.array([0.5, 0.6, 0.7, 0.8]),
    )

    flags = validate_science(ds)

    assert any(flag.check == "brightness_temperature" and flag.severity == "rerun_recommended" for flag in flags)


def test_qc_flags_csv_contains_one_row_per_flag_with_plot_paths(tmp_path: Path):
    ds = _new_schema_dataset(
        qc_adiabat=np.array([1.0, 1.0]),
        qc_dtdp=np.array([1.2, 0.9]),
        qc_adiabat_pressure=np.array([0.01, 0.1]),
    )
    result = validate_dataset(ds, tmp_path / "run.nc")
    summary_path = tmp_path / "qc_summary.csv"
    flags_path = tmp_path / "qc_flags.csv"
    diagnostic_path = tmp_path / "plots" / "check_adiabat" / "run-schema-qc_diagnostic.png"
    spectrum_path = tmp_path / "plots" / "check_adiabat" / "run-schema-qc_spectrum.png"

    write_summary([result_to_row(result, ds)], summary_path)
    rows = flags_to_rows(
        result,
        {
            "adiabat": {
                "diagnostic": str(diagnostic_path),
                "spectrum": str(spectrum_path),
            }
        },
    )
    write_flags(rows, flags_path)

    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    with flags_path.open("r", encoding="utf-8", newline="") as handle:
        flag_rows = list(csv.DictReader(handle))
    assert summary_rows[0]["run_id"] == "run-schema-qc"
    assert any(row["check"] == "adiabat" and row["diagnostic_plot_path"] == str(diagnostic_path) for row in flag_rows)


def test_missing_exact_picaso_diagnostics_message_reaches_qc_csvs(tmp_path: Path):
    ds = _new_schema_dataset()
    result = validate_dataset(ds, tmp_path / "run.nc")
    summary_path = tmp_path / "qc_summary.csv"
    flags_path = tmp_path / "qc_flags.csv"

    write_summary([result_to_row(result, ds)], summary_path)
    write_flags(flags_to_rows(result), flags_path)

    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    with flags_path.open("r", encoding="utf-8", newline="") as handle:
        flag_rows = list(csv.DictReader(handle))

    assert summary_rows[0]["warning_reasons"] == EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE
    assert any(
        row["check"] == "picaso_diagnostics"
        and row["severity"] == "warning"
        and row["message"] == EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE
        for row in flag_rows
    )


def test_diagnostic_title_distinguishes_qc_categories():
    ds = _new_schema_dataset()
    result = validate_dataset(ds)

    title = _diagnostic_title(ds, result)

    assert "Schema QC: pass" in title
    assert "PT/spectrum/cloud QC: pass" in title
    assert "Exact PICASO climate diagnostics: unavailable" in title
    assert EXACT_PICASO_CLIMATE_DIAGNOSTICS_MESSAGE in title


def test_browser_triage_discovers_only_safe_plot_paths(tmp_path: Path):
    plot_root = tmp_path / "plots"
    check_dir = plot_root / "check_adiabat"
    check_dir.mkdir(parents=True)
    (check_dir / "run-1_diagnostic.png").write_bytes(b"png")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")

    assert discover_plot_folders(plot_root) == ["check_adiabat"]
    assert safe_plot_path(plot_root, "../outside.png") is None
    models = discover_models(plot_root, "check_adiabat", {})
    assert len(models) == 1
    assert models[0]["diagnostic_plot_path"] == "check_adiabat/run-1_diagnostic.png"


def test_browser_triage_decisions_persist_and_undo(tmp_path: Path):
    plot_root = tmp_path / "plots"
    check_dir = plot_root / "check_flux_balance"
    check_dir.mkdir(parents=True)
    (check_dir / "run-2_diagnostic.png").write_bytes(b"png")
    decisions_path = tmp_path / "triage_decisions.csv"
    decisions = {}

    row = record_decision(
        plot_root,
        decisions_path,
        decisions,
        "check_flux_balance/run-2_diagnostic.png",
        "bad",
        "needs rerun",
    )
    loaded = load_decisions(decisions_path)
    assert row["rerun_recommended"] == "True"
    assert loaded["check_flux_balance/run-2_diagnostic.png"]["decision"] == "bad"

    undo_decision(plot_root, decisions_path, decisions, "check_flux_balance/run-2_diagnostic.png")
    assert load_decisions(decisions_path) == {}


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


def test_rerun_manifest_includes_browser_triage_bad_decision(tmp_path: Path):
    manifest = tmp_path / "grid_manifest.csv"
    qc = tmp_path / "qc_summary.csv"
    triage = tmp_path / "triage_decisions.csv"
    out = tmp_path / "rerun_manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_index", "run_id", "output_nc"])
        writer.writeheader()
        writer.writerow({"run_index": "8", "run_id": "run-0008", "output_nc": "run.nc"})
    with qc.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_index", "run_id", "rerun_recommended", "fail_reasons", "warning_reasons"])
        writer.writeheader()
    with triage.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["plot_path", "decision", "rerun_recommended", "notes", "timestamp", "run_id", "check"])
        writer.writeheader()
        writer.writerow(
            {
                "plot_path": "check_flux_balance/run-0008_diagnostic.png",
                "decision": "bad",
                "rerun_recommended": "True",
                "notes": "human marked bad",
                "timestamp": "2026-01-01T00:00:00Z",
                "run_id": "run-0008",
                "check": "check_flux_balance",
            }
        )

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
    assert rows[0]["run_id"] == "run-0008"
    assert rows[0]["qc_rerun_reasons"] == "human marked bad"
