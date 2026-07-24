from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.climate_groups import assign_climate_group_indices  # noqa: E402
from aurora_grid.parameters import (  # noqa: E402
    climate_spectrum_axes,
    create_manifest_dataframe,
    expected_climate_grid_size,
    expected_grid_size,
    load_config,
    mass_from_gravity_radius_mearth,
    unfiltered_grid_size,
)


V1_CONFIGS = (
    GRID_ROOT / "params" / "aurora_subneptune_v1.yaml",
    GRID_ROOT / "params" / "aurora_subneptune_v1_dhuang.yaml",
)


def _small_v1_config() -> dict:
    config = dict(load_config(V1_CONFIGS[0]))
    config.update(
        {
            "model_name": "test_v1_gravity",
            "output_root": "outputs/test_v1_gravity",
            "stars": [
                {"teff_k": 3500, "radius_rsun": 0.45},
                {"teff_k": 6000, "radius_rsun": 1.0},
            ],
            "gravity_ms2": [5, 25],
            "metallicity_xsolar": [1, 100],
            "c_to_o_xsolar": [1.0, 2.0],
            "kzz_cm2_s": [1.0e9],
            "cloud_fraction": [0.0],
            "fsed": [3],
            "insolation_searth": [0.35, 1.5],
        }
    )
    return config


def test_v1_configs_have_expected_filtered_counts_and_fixed_tint():
    for path in V1_CONFIGS:
        config = load_config(path)
        assert "planet_mass_mearth" not in config
        assert config["gravity_ms2"] == [5, 10, 15, 25, 30]
        assert config["picaso_tint_mode"] == "fixed"
        assert float(config["picaso_tint_fixed_k"]) == 50.0
        assert float(config["climate_reference_radius_rearth"]) == 2.0
        assert climate_spectrum_axes(config) == ("planet_radius_rearth", "phase_deg")
        assert unfiltered_grid_size(config) == 1_080_000
        assert expected_grid_size(config) == 960_000
        assert expected_climate_grid_size(config) == 40_000


def test_progress_snapshot_uses_filtered_spectrum_and_climate_counts():
    spec = importlib.util.spec_from_file_location(
        "progress_snapshot_counts",
        GRID_ROOT / "scripts" / "build_progress_snapshot.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    config = load_config(V1_CONFIGS[0])
    assert module._expected_counts(config) == (960_000, 40_000)


def test_filtered_manifest_is_contiguous_and_fans_each_climate_to_24_spectra():
    config = _small_v1_config()
    manifest = create_manifest_dataframe(config)
    assign_climate_group_indices(manifest.rows, spectrum_axes=climate_spectrum_axes(config))

    assert [row["run_index"] for row in manifest.rows] == list(range(len(manifest.rows)))
    assert not any(
        row["metallicity_xsolar"] == 100.0 and row["c_to_o_xsolar"] == 2.0
        for row in manifest.rows
    )
    group_counts = Counter(int(row["climate_group_index"]) for row in manifest.rows)
    assert set(group_counts.values()) == {24}
    assert sorted(group_counts) == list(range(len(group_counts)))
    assert len(group_counts) == expected_climate_grid_size(config)


def test_radius_phase_and_derived_mass_do_not_change_climate_identity():
    config = _small_v1_config()
    manifest = create_manifest_dataframe(config)
    assign_climate_group_indices(manifest.rows, spectrum_axes=climate_spectrum_axes(config))

    first = manifest.rows[0]
    same_climate = [
        row
        for row in manifest.rows
        if row["climate_group_index"] == first["climate_group_index"]
    ]
    assert {row["planet_radius_rearth"] for row in same_climate} == {1.6, 2.0, 2.5, 3.0}
    assert {row["phase_deg"] for row in same_climate} == {0.0, 30.0, 60.0, 90.0, 120.0, 150.0}
    assert len({row["planet_mass_mearth"] for row in same_climate}) == 4
    assert len({row["climate_group_key"] for row in same_climate}) == 1

    different_gravity = next(
        row
        for row in manifest.rows
        if row["gravity_ms2"] != first["gravity_ms2"]
        and row["planet_radius_rearth"] == first["planet_radius_rearth"]
        and row["phase_deg"] == first["phase_deg"]
    )
    assert different_gravity["climate_group_key"] != first["climate_group_key"]


def test_mass_is_derived_while_tint_and_equilibrium_temperature_are_distinct():
    config = _small_v1_config()
    manifest = create_manifest_dataframe(config)

    assert {row["picaso_tint_k"] for row in manifest.rows} == {50.0}
    assert len({round(row["equilibrium_temperature_k"], 6) for row in manifest.rows}) > 1
    for row in manifest.rows:
        expected_mass = mass_from_gravity_radius_mearth(
            row["gravity_ms2"], row["planet_radius_rearth"]
        )
        assert np.isclose(row["planet_mass_mearth"], expected_mass)


def test_existing_output_identity_check(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "spectrum_cache_chunk_identity",
        GRID_ROOT / "scripts" / "run_spectrum_from_cache_chunk.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    output = tmp_path / "run.nc"
    xr.Dataset(attrs={"run_id": "expected"}).to_netcdf(output)
    assert module.existing_output_matches_run_id(output, "expected") is True
    assert module.existing_output_matches_run_id(output, "different") is False
