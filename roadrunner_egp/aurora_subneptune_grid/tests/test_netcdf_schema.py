from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.io.netcdf_schema import (  # noqa: E402
    AuroraNetCDFOptions,
    build_aurora_run_dataset,
    validate_aurora_netcdf_schema,
    write_aurora_run_netcdf,
)
from aurora_grid.naming import make_output_path  # noqa: E402


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
        "netcdf_optional_variables": "[]",
        "netcdf_strict_optional": False,
        "source_notebook_reference": "notebook.ipynb",
    }


@pytest.fixture
def model_output() -> dict[str, object]:
    wavelength = np.array([0.5, 0.6, 0.7, 0.8])
    fpfs_reflection = np.array([1.0e-8, 1.2e-8, 1.1e-8, 0.9e-8])
    fpfs_emission = np.array([1.0e-10, 1.1e-10, 1.2e-10, 1.3e-10])
    pressure = np.array([1.0e-3, 1.0e-2, 1.0e-1])
    temperature = np.array([400.0, 450.0, 500.0])
    return {
        "wavelength_um": wavelength,
        "fpfs_reflection": fpfs_reflection,
        "albedo": np.array([0.2, 0.25, 0.22, 0.18]),
        "fpfs_emission": fpfs_emission,
        "absolute_flux_reflected": np.array([1.0, 1.1, 1.2, 1.3]),
        "absolute_flux_thermal": np.array([0.1, 0.2, 0.3, 0.4]),
        "bond_albedo": np.array([0.3, 0.31, 0.32, 0.33]),
        "pt_profile": {
            "pressure": pressure,
            "temperature": temperature,
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
        "mean_molecular_weight_amu": np.array([2.3, 2.31, 2.32]),
        "picaso_metadata": {"dry_run": True, "cloud_model": "virga"},
    }


def test_build_schema_v1_dataset_has_required_dimensions(model_output, manifest_row):
    dataset = build_aurora_run_dataset(model_output, manifest_row, runtime_seconds=1.25)

    assert dict(dataset.sizes) == {"wavelength": 4, "level": 3, "species": 3, "layer": 2}
    assert set(["wavelength_um", "wavenumber_cm1", "level", "layer", "species"]).issubset(dataset.coords)
    assert dataset.attrs["schema_name"] == "aurora_subneptune_netcdf"
    assert dataset.attrs["schema_version"] == "1.0"
    assert validate_aurora_netcdf_schema(dataset) == []


def test_required_only_default_omits_optional_variables(model_output, manifest_row):
    dataset = build_aurora_run_dataset(model_output, manifest_row)

    for name in [
        "bond_albedo",
        "thermal_planet_star_flux_ratio",
        "total_planet_star_flux_ratio",
        "mean_molecular_weight_amu",
    ]:
        assert name not in dataset.data_vars


def test_enable_each_optional_variable(model_output, manifest_row):
    options = AuroraNetCDFOptions(
        optional_variables=(
            "bond_albedo",
            "thermal_planet_star_flux_ratio",
            "total_planet_star_flux_ratio",
            "mean_molecular_weight_amu",
        )
    )
    dataset = build_aurora_run_dataset(model_output, manifest_row, schema_options=options)

    assert dataset["bond_albedo"].dims == ("wavelength",)
    assert dataset["thermal_planet_star_flux_ratio"].dims == ("wavelength",)
    assert dataset["total_planet_star_flux_ratio"].dims == ("wavelength",)
    assert dataset["mean_molecular_weight_amu"].dims == ("level",)
    np.testing.assert_allclose(
        dataset["total_planet_star_flux_ratio"].values,
        np.asarray(model_output["fpfs_reflection"]) + np.asarray(model_output["fpfs_emission"]),
    )


def test_all_optional_policy(model_output, manifest_row):
    dataset = build_aurora_run_dataset(
        model_output,
        manifest_row,
        schema_options={"optional_variables": ["all"]},
    )

    for name in [
        "bond_albedo",
        "thermal_planet_star_flux_ratio",
        "total_planet_star_flux_ratio",
        "mean_molecular_weight_amu",
    ]:
        assert name in dataset.data_vars


def test_nested_exact_climate_qc_diagnostics_are_written(model_output, manifest_row):
    model_output = dict(model_output)
    model_output["qc_diagnostics"] = {
        "qc_adiabat": np.array([1.0, 1.1, 1.2]),
        "qc_dtdp": np.array([0.8, 0.9, 1.0]),
        "qc_adiabat_pressure": np.array([1.0e-3, 1.0e-2, 1.0e-1]),
        "fnet_irfnet": np.array([1.0e-4, -2.0e-4, 3.0e-4]),
        "qc_brightness_temperature": np.array([350.0, 360.0, 365.0, 370.0]),
        "qc_brightness_wavelength": np.array([0.5, 0.6, 0.7, 0.8]),
        "schema_warnings": ["brightness diagnostic fallback warning"],
    }

    dataset = build_aurora_run_dataset(model_output, manifest_row)

    assert dataset["qc_adiabat"].dims == ("level",)
    assert dataset["qc_dtdp"].dims == ("level",)
    assert dataset["qc_adiabat_pressure"].dims == ("level",)
    assert dataset["fnet_irfnet"].dims == ("level",)
    assert dataset["qc_brightness_temperature"].dims == ("brightness_wavelength_um",)
    assert dataset["qc_brightness_wavelength_um"].dims == ("brightness_wavelength_um",)
    assert dataset["qc_brightness_wavelength"].dims == ("brightness_wavelength_um",)
    assert "brightness diagnostic fallback warning" in dataset.attrs["schema_warnings"]


def test_native_grid_brightness_qc_writes_and_reopens(model_output, manifest_row, tmp_path):
    model_output = dict(model_output)
    brightness_wavelength = np.array([1.0, 1.4, 1.8, 2.2, 2.6, 3.0])
    brightness_temperature = np.array([310.0, 320.0, 330.0, 340.0, 350.0, 360.0])
    model_output["qc_diagnostics"] = {
        "qc_brightness_temperature": brightness_temperature,
        "qc_brightness_wavelength": brightness_wavelength,
    }

    dataset = build_aurora_run_dataset(model_output, manifest_row)

    assert dataset["wavelength_um"].shape == (4,)
    assert dataset["qc_brightness_temperature"].shape == brightness_temperature.shape
    assert dataset["qc_brightness_wavelength_um"].shape == brightness_wavelength.shape
    assert dataset["qc_brightness_temperature"].shape != dataset["wavelength_um"].shape
    assert validate_aurora_netcdf_schema(dataset) == []
    assert "exact brightness-temperature diagnostic does not match schema wavelength grid" not in dataset.attrs.get("schema_warnings", "")

    output_path = tmp_path / "native_brightness.nc"
    status = write_aurora_run_netcdf(dataset, output_path)
    assert status["status"] == "wrote"
    with xr.open_dataset(output_path) as reopened:
        assert "qc_brightness_temperature" in reopened
        assert "qc_brightness_wavelength_um" in reopened or "qc_brightness_wavelength" in reopened
        brightness_wavelength_name = (
            "qc_brightness_wavelength_um"
            if "qc_brightness_wavelength_um" in reopened
            else "qc_brightness_wavelength"
        )
        assert reopened["qc_brightness_temperature"].shape == reopened[brightness_wavelength_name].shape
        assert reopened["qc_brightness_temperature"].shape != reopened["wavelength_um"].shape


def test_missing_enabled_optional_warns_by_default(model_output, manifest_row):
    model_output = dict(model_output)
    model_output.pop("bond_albedo")
    dataset = build_aurora_run_dataset(
        model_output,
        manifest_row,
        schema_options={"optional_variables": ["bond_albedo"]},
    )

    assert "bond_albedo" not in dataset.data_vars
    assert "optional variable bond_albedo requested but unavailable" in dataset.attrs["schema_warnings"]


def test_missing_enabled_optional_fails_when_strict(model_output, manifest_row):
    model_output = dict(model_output)
    model_output.pop("bond_albedo")

    with pytest.raises(ValueError, match="bond_albedo"):
        build_aurora_run_dataset(
            model_output,
            manifest_row,
            schema_options={"optional_variables": ["bond_albedo"], "strict_optional": True},
        )


def test_cloud_profile_is_saved_with_layer_wavelength_dims(model_output, manifest_row):
    dataset = build_aurora_run_dataset(model_output, manifest_row)

    assert dataset["cloud_optical_depth"].dims == ("layer", "wavelength")
    assert dataset["single_scattering_albedo"].dims == ("layer", "wavelength")
    assert dataset["asymmetry_factor"].dims == ("layer", "wavelength")


def test_cloud_profile_is_reordered_to_schema_wavelength(model_output, manifest_row):
    model_output = dict(model_output)
    cloud_profile = dict(model_output["cloud_profile"])
    cloud_profile["wavelength_um"] = np.array([0.8, 0.7, 0.6, 0.5])
    cloud_profile["opd"] = np.tile(np.array([0.4, 0.3, 0.2, 0.1]), (2, 1))
    cloud_profile["w0"] = np.tile(np.array([0.8, 0.7, 0.6, 0.5]), (2, 1))
    cloud_profile["g0"] = np.tile(np.array([0.4, 0.3, 0.2, 0.1]), (2, 1))
    model_output["cloud_profile"] = cloud_profile

    dataset = build_aurora_run_dataset(model_output, manifest_row)

    np.testing.assert_allclose(dataset["cloud_optical_depth"].values[0], [0.1, 0.2, 0.3, 0.4])
    np.testing.assert_allclose(dataset["single_scattering_albedo"].values[0], [0.5, 0.6, 0.7, 0.8])


def test_scalar_params_are_data_variables(model_output, manifest_row):
    dataset = build_aurora_run_dataset(model_output, manifest_row, runtime_seconds=4.0)

    assert "run_index" in dataset.data_vars
    assert "runtime_seconds" in dataset.data_vars
    assert "star_teff_k" in dataset.data_vars
    assert "run_index" not in dataset.attrs
    assert dataset["run_index"].item() == 7


def test_validator_catches_bad_cloud_ranges(model_output, manifest_row):
    model_output = dict(model_output)
    cloud_profile = dict(model_output["cloud_profile"])
    cloud_profile["w0"] = np.ones((2, 4)) * 1.5
    model_output["cloud_profile"] = cloud_profile

    with pytest.raises(ValueError, match="single_scattering_albedo"):
        build_aurora_run_dataset(model_output, manifest_row)


def test_dataset_can_be_written_reopened_and_skipped(tmp_path, model_output, manifest_row):
    output_path = tmp_path / "archive.nc"
    dataset = build_aurora_run_dataset(model_output, manifest_row)

    status = write_aurora_run_netcdf(dataset, output_path)
    assert status["status"] == "wrote"
    with xr.open_dataset(output_path) as reopened:
        assert reopened.attrs["schema_name"] == "aurora_subneptune_netcdf"
        assert "reflected_planet_star_flux_ratio" in reopened.data_vars
        assert "fpfs_reflection" not in reopened.data_vars
        assert "albedo" not in reopened.data_vars

    second = build_aurora_run_dataset(model_output, manifest_row)
    skip_status = write_aurora_run_netcdf(second, output_path)
    second.close()
    assert skip_status["status"] == "skipped_exists"


def test_make_output_path_uses_schema_v1_run_index_filename():
    row = {"run_index": 42}

    assert make_output_path(row, "results") == "results/nc/run_000042.nc"
