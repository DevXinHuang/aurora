from __future__ import annotations

from pathlib import Path

from aurora_grid.factorization import make_climate_key
from aurora_grid.parameters import _metadata_columns, load_config
from roadrunner.config import DEFAULT_PICASO_VIRGA_CONDENSATES
from roadrunner.runner import _virga_condensates


GRID_ROOT = Path(__file__).resolve().parents[1]
SUBNEPTUNE_CONFIGS = (
    "aurora_subneptune_v0.yaml",
    "aurora_subneptune_v1.yaml",
    "aurora_subneptune_v1_dhuang.yaml",
    "hpc_validation.yaml",
    "smoke_test.yaml",
)
EXPECTED_CONDENSATES = "H2O,CH4,NH3"
EXPECTED_CONDENSATE_LIST = ["H2O", "CH4", "NH3"]


def test_roadrunner_default_condensates_are_subneptune_volatiles():
    assert DEFAULT_PICASO_VIRGA_CONDENSATES == EXPECTED_CONDENSATES
    assert _virga_condensates(None) == EXPECTED_CONDENSATE_LIST
    assert _virga_condensates("") == EXPECTED_CONDENSATE_LIST


def test_subneptune_configs_define_candidate_condensates_explicitly():
    for filename in SUBNEPTUNE_CONFIGS:
        config = load_config(GRID_ROOT / "params" / filename)
        assert config["virga_condensates"] == EXPECTED_CONDENSATES
        assert _metadata_columns(config)["virga_condensates"] == EXPECTED_CONDENSATES


def test_condensate_candidates_change_climate_cache_key():
    row = {
        "model_name": "test_subneptune",
        "cloud_model": "virga",
        "virga_condensates": EXPECTED_CONDENSATES,
    }
    volatile_key = make_climate_key(row)
    refractory_key = make_climate_key(
        {
            **row,
            "virga_condensates": "MgSiO3,Mg2SiO4",
        }
    )
    assert volatile_key != refractory_key
