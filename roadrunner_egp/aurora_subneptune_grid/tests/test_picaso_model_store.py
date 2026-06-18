from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest
import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.storage.picaso_model_store import (  # noqa: E402
    add_aurora_spectral_aliases,
    build_picaso_model_dataset,
    save_picaso_model_dataset,
)


@pytest.fixture
def manifest_row(tmp_path: Path) -> dict[str, object]:
    return {
        "run_index": 7,
        "model_name": "test_model",
        "run_id": "run-0007",
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
        "output_nc": str(tmp_path / "run.nc"),
        "author": "Aurora",
        "contact": "aurora@example.test",
        "project": "Aurora",
        "notes": "test",
        "code": "{}",
        "picaso_tint_mode": "equilibrium",
        "picaso_tint_fixed_k": 1000.0,
        "picaso_tint_floor_k": 100.0,
        "source_notebook_reference": "notebook.ipynb",
    }


@pytest.fixture
def model_output() -> dict[str, object]:
    wavelength = np.array([0.5, 0.6, 0.7, 0.8])
    fpfs_reflection = np.array([1.0e-8, 1.2e-8, 1.1e-8, 0.9e-8])
    fpfs_emission = np.array([1.0e-10, 1.1e-10, 1.2e-10, 1.3e-10])
    return {
        "wavelength_um": wavelength,
        "fpfs_reflection": fpfs_reflection,
        "albedo": np.array([0.2, 0.25, 0.22, 0.18]),
        "fpfs_emission": fpfs_emission,
        "reflected_fraction": fpfs_reflection / (fpfs_reflection + fpfs_emission),
        "absolute_flux_reflected": np.array([1.0, 1.1, 1.2, 1.3]),
        "absolute_flux_thermal": np.array([0.1, 0.2, 0.3, 0.4]),
        "picaso_metadata": {"dry_run": True},
    }


def test_fallback_dataset_uses_v1_schema(model_output, manifest_row):
    dataset = build_picaso_model_dataset(model_output, manifest_row)

    assert "wavelength" in dataset.coords
    assert "wavelength_um" not in dataset.coords
    assert "wavelength_um" not in dataset.dims
    assert dataset["wavelength"].attrs["units"] == "micron"
    assert "albedo" in dataset.data_vars
    assert "fpfs_reflected" in dataset.data_vars
    assert "fpfs_reflection" in dataset.data_vars
    assert "flux_emission" in dataset.data_vars
    assert "aurora_reflected_fraction" in dataset.data_vars
    assert "aurora_flux_reflected" in dataset.data_vars
    assert dataset.attrs["aurora_schema_version"] == "picaso_model_store_v1"
    assert dataset.attrs["run_index"] == 7
    for attr in [
        "author",
        "contact",
        "code",
        "model_name",
        "run_id",
        "created_utc",
        "git_commit",
        "picaso_version",
        "planet_params",
        "stellar_params",
        "orbit_params",
        "cld_params",
        "grid_params",
        "source_manifest_row",
    ]:
        assert attr in dataset.attrs


def test_dataset_can_be_written_reopened_and_skipped(tmp_path, model_output, manifest_row):
    output_path = tmp_path / "archive.nc"
    dataset = build_picaso_model_dataset(model_output, manifest_row)

    status = save_picaso_model_dataset(dataset, output_path)
    assert status["status"] == "wrote"
    with xr.open_dataset(output_path) as reopened:
        assert "wavelength" in reopened.coords
        assert "fpfs_reflection" in reopened.data_vars
        assert "fpfs_reflected" in reopened.data_vars
        assert "albedo" in reopened.data_vars

    second = build_picaso_model_dataset(model_output, manifest_row)
    skip_status = save_picaso_model_dataset(second, output_path)
    second.close()
    assert skip_status["status"] == "skipped_exists"


def test_picaso_output_xarray_path_is_augmented(monkeypatch, model_output, manifest_row):
    picaso_dataset = xr.Dataset(
        data_vars={
            "temperature": (("pressure",), np.array([400.0, 500.0])),
            "H2O": (("pressure",), np.array([1.0e-3, 2.0e-3])),
            "opd": (("pressure_layer", "wavenumber_layer"), np.ones((1, 2))),
            "ssa": (("pressure_layer", "wavenumber_layer"), np.ones((1, 2)) * 0.5),
            "asy": (("pressure_layer", "wavenumber_layer"), np.ones((1, 2)) * 0.2),
        },
        coords={
            "pressure": ("pressure", np.array([1.0, 0.1])),
            "pressure_layer": ("pressure_layer", np.array([0.5])),
            "wavenumber_layer": ("wavenumber_layer", np.array([1000.0, 1100.0])),
        },
    )
    fake_jdi = types.SimpleNamespace(output_xarray=lambda out_ref, case, add_output, savefile: picaso_dataset)
    fake_picaso = types.SimpleNamespace(justdoit=fake_jdi, __version__="test")
    monkeypatch.setitem(sys.modules, "picaso", fake_picaso)

    enriched_output = dict(model_output)
    enriched_output["picaso_out_reflected"] = {"wavenumber": np.array([1000.0])}
    enriched_output["picaso_case"] = object()

    dataset = build_picaso_model_dataset(enriched_output, manifest_row)
    assert "pressure" in dataset.coords
    assert "temperature" in dataset.data_vars
    assert "H2O" in dataset.data_vars
    assert "opd" in dataset.data_vars
    assert dataset["pressure"].attrs["units"] == "bar"
    assert dataset["wavenumber_layer"].attrs["units"] == "cm^-1"
    assert "wavelength" in dataset.coords
    assert "fpfs_reflected" in dataset.data_vars
    assert "fpfs_reflection" in dataset.data_vars
    assert dataset.attrs["storage_level"] == "aurora_extended"


def test_native_picaso_wavelength_is_preserved_when_aurora_grid_differs(model_output):
    native = xr.Dataset(
        data_vars={"native_albedo": (("wavelength",), np.array([0.1, 0.2]))},
        coords={"wavelength": ("wavelength", np.array([0.45, 0.55]))},
    )
    dataset = add_aurora_spectral_aliases(native, model_output)

    assert "picaso_wavelength" in dataset.coords
    assert "wavelength" in dataset.coords
    assert dataset.sizes["wavelength"] == 4
    assert dataset.sizes["picaso_wavelength"] == 2
    assert "fpfs_reflected" in dataset.data_vars
    assert "fpfs_reflection" in dataset.data_vars
