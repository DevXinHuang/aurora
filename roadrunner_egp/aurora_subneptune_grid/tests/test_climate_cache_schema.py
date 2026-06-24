from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from aurora_grid.io.climate_cache_schema import (
    CLIMATE_CACHE_SCHEMA_NAME,
    build_climate_cache_dataset,
    load_climate_cache,
    row_from_climate_cache,
)


def _synthetic_model_output():
    pressure = np.geomspace(1e-4, 100.0, 8)
    temperature = np.linspace(800.0, 200.0, pressure.size)
    species = ["H2", "He", "H2O"]
    mole_fraction = np.column_stack(
        [
            np.full(pressure.size, 0.85),
            np.full(pressure.size, 0.10),
            np.full(pressure.size, 0.05),
        ]
    )
    wavelength = np.linspace(0.3, 2.5, 32)
    return {
        "wavelength_um": wavelength,
        "fpfs_emission": np.linspace(1e-8, 1e-7, wavelength.size),
        "absolute_flux_thermal": np.linspace(1e-12, 1e-11, wavelength.size),
        "pt_profile": {
            "pressure": pressure,
            "temperature": temperature,
            "H2": mole_fraction[:, 0],
            "He": mole_fraction[:, 1],
            "H2O": mole_fraction[:, 2],
        },
        "cloud_profile": {
            "wavelength_um": wavelength,
            "opd": np.zeros((pressure.size - 1, wavelength.size)),
            "w0": np.zeros((pressure.size - 1, wavelength.size)),
            "g0": np.zeros((pressure.size - 1, wavelength.size)),
        },
    }


def _synthetic_row():
    return {
        "model_name": "test_cache",
        "climate_key": "abc123",
        "climate_index": 0,
        "planet_class_id": "jupiter_analog",
        "separation_id": "inner_cloudy",
        "star_teff_k": 5772.0,
        "star_radius_rsun": 1.0,
        "planet_radius_rearth": 10.0,
        "gravity_ms2": 25.0,
        "metallicity_xsolar": 1.0,
        "c_to_o_xsolar": 1.0,
        "kzz_cm2_s": 1.0e9,
        "cloud_fraction": 1.0,
        "cloud_model": "virga",
        "fsed": 3.0,
        "insolation_searth": 4.0,
        "semi_major_au": 0.5,
        "equilibrium_temperature_k": 1200.0,
        "picaso_tint_k": 140.0,
    }


def test_climate_cache_round_trip(tmp_path: Path):
    row = _synthetic_row()
    model_output = _synthetic_model_output()
    dataset = build_climate_cache_dataset(model_output, row, runtime_seconds=1.0)
    assert dataset.attrs["schema_name"] == CLIMATE_CACHE_SCHEMA_NAME
    assert "planet_params" in dataset.attrs
    assert "chemistry_params" in dataset.attrs

    output_path = tmp_path / "climate.nc"
    dataset.to_netcdf(output_path)
    dataset.close()

    state = load_climate_cache(output_path)
    assert state.pressure_bar.size == 8
    assert state.species == ["H2", "He", "H2O"]
    assert state.thermal_planet_star_flux_ratio is not None

    reloaded_row = row_from_climate_cache(state)
    assert reloaded_row["planet_radius_rearth"] == 10.0
    assert reloaded_row["climate_key"] == "abc123"

    with xr.open_dataset(output_path) as reopened:
        assert reopened.attrs["model_name"] == "test_cache"
        assert reopened.attrs["climate_index"] == 0
