from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.cahoy_climate_cache import load_climate_cache, save_climate_cache


def test_save_climate_cache_serializes_ndarray_diagnostics(tmp_path: Path):
    diagnostics = {
        "climate_converged": True,
        "flux_balance": np.array([0.001, -0.0002]),
        "pressure": np.linspace(1.0, 1.0e-4, 120),
        "qc_dtdp": np.linspace(-0.5, 0.2, 120),
    }
    row = {
        "semi_major_au": 0.8,
        "cahoy_planet_type": "Jupiter",
        "cahoy_metallicity_label": "1x",
        "cahoy_cloud_note": "cloud-free",
    }
    cache_file = tmp_path / "climate_00.npz"
    save_climate_cache(
        cache_file,
        climate_group_index=0,
        pressure=np.linspace(1.0, 1.0e-4, 120),
        temperature=np.linspace(200.0, 1200.0, 120),
        selected_ck_file="/tmp/test.ck",
        diagnostics=diagnostics,
        row=row,
    )
    loaded = load_climate_cache(cache_file)
    assert loaded["pressure"].shape == (120,)
    assert loaded["metadata"]["diagnostics"]["climate_converged"] is True
    assert "shape" in loaded["metadata"]["diagnostics"]["pressure"]
