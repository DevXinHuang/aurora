from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora_grid.coupled_grid import expand_coupled_climates, load_grid_config
from aurora_grid.factorization import create_factorized_manifests, load_factorization_config, make_climate_key


GRID_ROOT = Path(__file__).resolve().parents[1]
CAHOY_CONFIG = GRID_ROOT / "params" / "aurora_cahoy_exact_304_factorized.yaml"

EXPECTED_PHASES = [float(phase) for phase in range(0, 181, 10)]
JUPITER_RADIUS = 11.209
JUPITER_GRAVITY = 25.0
JUPITER_TINT = 100.0
JUPITER_MH = {1.0, 3.16}
NEPTUNE_RADIUS = 3.883
NEPTUNE_GRAVITY = 10.0
NEPTUNE_TINT = 50.0
NEPTUNE_MH = {10.0, 31.6}
SEPARATIONS_AU = {0.8, 2.0, 5.0, 10.0}


@pytest.fixture(scope="module")
def cahoy_config():
    return load_grid_config(CAHOY_CONFIG)


@pytest.fixture(scope="module")
def cahoy_manifests(cahoy_config):
    return create_factorized_manifests(cahoy_config)


@pytest.fixture(scope="module")
def factorization(cahoy_config):
    config = load_factorization_config(cahoy_config)
    assert config is not None
    return config


def test_cahoy_manifest_counts(cahoy_manifests):
    assert len(cahoy_manifests.full) == 304
    assert len(cahoy_manifests.climate) == 16
    assert len(cahoy_manifests.spectrum) == 304
    assert len(cahoy_manifests.climate_spectrum_map) == 16


def test_cahoy_jupiter_climate_parameters(cahoy_manifests):
    jupiter = [row for row in cahoy_manifests.climate.rows if row["planet_class_id"] == "jupiter_analog"]
    assert len(jupiter) == 8
    assert {float(row["planet_radius_rearth"]) for row in jupiter} == {JUPITER_RADIUS}
    assert {float(row["gravity_ms2"]) for row in jupiter} == {JUPITER_GRAVITY}
    assert {float(row["picaso_tint_k"]) for row in jupiter} == {JUPITER_TINT}
    assert {float(row["metallicity_xsolar"]) for row in jupiter} == JUPITER_MH


def test_cahoy_neptune_climate_parameters(cahoy_manifests):
    neptune = [row for row in cahoy_manifests.climate.rows if row["planet_class_id"] == "neptune_analog"]
    assert len(neptune) == 8
    assert {float(row["planet_radius_rearth"]) for row in neptune} == {NEPTUNE_RADIUS}
    assert {float(row["gravity_ms2"]) for row in neptune} == {NEPTUNE_GRAVITY}
    assert {float(row["picaso_tint_k"]) for row in neptune} == {NEPTUNE_TINT}
    assert {float(row["metallicity_xsolar"]) for row in neptune} == NEPTUNE_MH


def test_cahoy_separations_and_cloud_mapping(cahoy_manifests):
    climates = cahoy_manifests.climate.rows
    assert {float(row["semi_major_au"]) for row in climates} == SEPARATIONS_AU

    clear = [row for row in climates if float(row["semi_major_au"]) == 0.8]
    assert all(float(row["cloud_fraction"]) == 0.0 for row in clear)
    assert all(row["cloud_model"] == "none" for row in clear)
    assert all(row.get("fsed") in ("", None) for row in clear)

    cloudy_2au = [row for row in climates if float(row["semi_major_au"]) == 2.0]
    assert all(float(row["cloud_fraction"]) == 1.0 for row in cloudy_2au)
    assert all(row["cloud_model"] == "virga" for row in cloudy_2au)
    assert all(float(row["fsed"]) == 6.0 for row in cloudy_2au)

    cloudy_outer = [row for row in climates if float(row["semi_major_au"]) in {5.0, 10.0}]
    assert all(float(row["cloud_fraction"]) == 1.0 for row in cloudy_outer)
    assert all(row["cloud_model"] == "virga" for row in cloudy_outer)
    assert all(float(row["fsed"]) == 10.0 for row in cloudy_outer)


def test_cahoy_stellar_spectrum_on_all_climates(cahoy_manifests):
    expected = "roadrunner_egp/aurora_subneptune_grid/data/stellar_spectra/SOLARSPECTRUM.DAT"
    for row in cahoy_manifests.climate.rows:
        assert row["stellar_spectrum_filename"] == expected
        assert row["stellar_spectrum_w_unit"] == "AA"
        assert "erg" in str(row["stellar_spectrum_f_unit"])


def test_cahoy_phase_coverage_exact(cahoy_manifests):
    phases = sorted({float(row["phase_deg"]) for row in cahoy_manifests.spectrum.rows})
    assert phases == EXPECTED_PHASES

    by_climate = {}
    for row in cahoy_manifests.spectrum.rows:
        by_climate.setdefault(row["climate_key"], []).append(float(row["phase_deg"]))
    for climate_key, values in by_climate.items():
        assert sorted(values) == EXPECTED_PHASES, climate_key


def test_climate_key_invariant_under_phase(cahoy_manifests, factorization):
    sample = cahoy_manifests.full.rows[0]
    key_a = make_climate_key(sample, factorization.climate_axes)
    sample_other_phase = dict(sample)
    sample_other_phase["phase_deg"] = 180.0
    key_b = make_climate_key(sample_other_phase, factorization.climate_axes)
    assert key_a == key_b


def test_climate_key_changes_with_stellar_spectrum_filename(cahoy_manifests, factorization):
    sample = dict(cahoy_manifests.climate.rows[0])
    base_key = make_climate_key(sample, factorization.climate_axes)
    sample["stellar_spectrum_filename"] = "roadrunner_egp/aurora_subneptune_grid/data/stellar_spectra/OTHER.DAT"
    changed_key = make_climate_key(sample, factorization.climate_axes)
    assert changed_key != base_key


def test_map_manifest_links(cahoy_manifests):
    for row in cahoy_manifests.climate_spectrum_map.rows:
        indices = json.loads(row["spectrum_indices"])
        phases = json.loads(row["phase_deg_values"])
        assert int(row["n_spectra"]) == 19
        assert len(indices) == 19
        assert [float(phase) for phase in phases] == EXPECTED_PHASES


def test_coupled_climate_expansion_count(cahoy_config):
    climates = expand_coupled_climates(cahoy_config)
    assert len(climates) == 16
