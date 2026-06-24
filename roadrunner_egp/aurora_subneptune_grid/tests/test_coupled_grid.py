from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora_grid.coupled_grid import expand_coupled_climates, expand_coupled_full_manifest
from aurora_grid.factorization import make_climate_key


MINIMAL_COUPLED_CONFIG = {
    "model_name": "test_coupled",
    "output_root": "roadrunner_egp/aurora_subneptune_grid/outputs/test_coupled",
    "star": {"teff_k": 5772, "radius_rsun": 1.0},
    "planet_classes": [
        {
            "id": "jupiter_analog",
            "planet_radius_rearth": 10.0,
            "gravity_ms2": 25.0,
            "picaso_tint_mode": "fixed",
            "picaso_tint_k": 140.0,
            "metallicity_xsolar": [1, 10],
            "c_to_o_xsolar": 1.0,
            "kzz_cm2_s": 1.0e9,
        },
        {
            "id": "neptune_analog",
            "planet_radius_rearth": 4.0,
            "gravity_ms2": 11.0,
            "picaso_tint_mode": "fixed",
            "picaso_tint_k": 60.0,
            "metallicity_xsolar": [1, 10],
            "c_to_o_xsolar": 1.0,
            "kzz_cm2_s": 1.0e9,
        },
    ],
    "separations": [
        {
            "id": "inner_cloudy",
            "semi_major_au": 0.5,
            "cloud_fraction": 1.0,
            "cloud_model": "virga",
            "fsed": 3,
        },
        {
            "id": "outer_clear",
            "semi_major_au": 5.0,
            "cloud_fraction": 0.0,
            "cloud_model": "none",
            "fsed": 3,
        },
    ],
    "phase_deg": [0, 90],
    "author": "",
    "contact": "",
    "project": "",
    "notes": "",
}


def test_coupled_climate_count():
    climates = expand_coupled_climates(MINIMAL_COUPLED_CONFIG)
    assert len(climates) == 8


def test_coupled_full_manifest_phase_product():
    manifest = expand_coupled_full_manifest(MINIMAL_COUPLED_CONFIG)
    assert len(manifest) == 16


def test_planet_class_parameters_do_not_mix():
    climates = expand_coupled_climates(MINIMAL_COUPLED_CONFIG)
    jupiter = [row for row in climates if row["planet_class_id"] == "jupiter_analog"]
    neptune = [row for row in climates if row["planet_class_id"] == "neptune_analog"]
    assert all(row["planet_radius_rearth"] == 10.0 for row in jupiter)
    assert all(row["gravity_ms2"] == 25.0 for row in jupiter)
    assert all(row["picaso_tint_k"] == 140.0 for row in jupiter)
    assert all(row["planet_radius_rearth"] == 4.0 for row in neptune)
    assert all(row["gravity_ms2"] == 11.0 for row in neptune)
    assert all(row["picaso_tint_k"] == 60.0 for row in neptune)


def test_separation_controls_cloud_regime():
    climates = expand_coupled_climates(MINIMAL_COUPLED_CONFIG)
    inner = [row for row in climates if row["separation_id"] == "inner_cloudy"]
    outer = [row for row in climates if row["separation_id"] == "outer_clear"]
    assert all(row["cloud_fraction"] == 1.0 and row["cloud_model"] == "virga" for row in inner)
    assert all(row["cloud_fraction"] == 0.0 and row["cloud_model"] == "none" for row in outer)


def test_climate_key_invariant_under_phase():
    manifest = expand_coupled_full_manifest(MINIMAL_COUPLED_CONFIG)
    keys_by_class_sep_mh = {}
    for row in manifest.rows:
        base_key = make_climate_key(row)
        group = (
            row["planet_class_id"],
            row["separation_id"],
            row["metallicity_xsolar"],
        )
        keys_by_class_sep_mh.setdefault(group, set()).add(base_key)
    for group, keys in keys_by_class_sep_mh.items():
        assert len(keys) == 1, f"phase changed climate key for {group}"
