from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora_grid.coupled_grid import load_grid_config
from aurora_grid.factorization import create_factorized_manifests, make_climate_key


GRID_ROOT = Path(__file__).resolve().parents[1]
CAHOY_CONFIG = GRID_ROOT / "params" / "aurora_cahoy_exact_304_factorized.yaml"


@pytest.fixture(scope="module")
def cahoy_config():
    return load_grid_config(CAHOY_CONFIG)


@pytest.fixture(scope="module")
def cahoy_manifests(cahoy_config):
    return create_factorized_manifests(cahoy_config)


def test_cahoy_manifest_counts(cahoy_manifests):
    assert len(cahoy_manifests.full) == 304
    assert len(cahoy_manifests.climate) == 16
    assert len(cahoy_manifests.spectrum) == 304


def test_cahoy_unique_climate_keys(cahoy_manifests):
    keys = {row["climate_key"] for row in cahoy_manifests.climate.rows}
    assert len(keys) == 16


def test_cahoy_phase_coverage(cahoy_manifests):
    phases = sorted({float(row["phase_deg"]) for row in cahoy_manifests.spectrum.rows})
    assert len(phases) == 19
    assert phases[0] == 0.0
    assert phases[-1] == 180.0

    by_climate = {}
    for row in cahoy_manifests.spectrum.rows:
        by_climate.setdefault(row["climate_key"], []).append(float(row["phase_deg"]))
    assert all(len(values) == 19 for values in by_climate.values())


def test_cahoy_eight_climates_per_planet_class(cahoy_manifests):
    by_class = {}
    for row in cahoy_manifests.climate.rows:
        by_class.setdefault(row["planet_class_id"], []).append(row)
    assert len(by_class["jupiter_analog"]) == 8
    assert len(by_class["neptune_analog"]) == 8


def test_climate_key_stable_across_phase(cahoy_manifests):
    sample = cahoy_manifests.full.rows[0]
    key_a = make_climate_key(sample)
    sample_other_phase = dict(sample)
    sample_other_phase["phase_deg"] = 180.0
    key_b = make_climate_key(sample_other_phase)
    assert key_a == key_b


def test_map_manifest_links(cahoy_manifests):
    for row in cahoy_manifests.climate_spectrum_map.rows:
        indices = json.loads(row["spectrum_indices"])
        phases = json.loads(row["phase_deg_values"])
        assert int(row["n_spectra"]) == 19
        assert len(indices) == 19
        assert len(phases) == 19
