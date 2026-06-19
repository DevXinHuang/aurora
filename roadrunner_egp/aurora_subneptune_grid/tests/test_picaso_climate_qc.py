from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid import picaso_runner  # noqa: E402
from roadrunner.runner import configure_climate_inputs, select_picaso4_preweighted_ck_file  # noqa: E402
from roadrunner.system import SystemParams  # noqa: E402


def _system(metallicity_xsolar: float, c_to_o_xsolar: float) -> SystemParams:
    return SystemParams(
        teff_k=500.0,
        logg_cgs=3.0,
        rj=0.2,
        a_au=0.1,
        phase_deg=0.0,
        tstar_k=5000.0,
        rstar_rsun=0.8,
        atmosphere_source="picaso",
        cloud_model="virga",
        chem_c_o=c_to_o_xsolar,
        chem_log_mh=math.log10(metallicity_xsolar),
    )


@pytest.mark.parametrize(
    ("metallicity_xsolar", "c_to_o_xsolar", "expected"),
    [
        (1.0, 1.0, "sonora_2121grid_feh0.0_co0.55.hdf5"),
        (10.0, 1.0, "sonora_2121grid_feh1.0_co0.55.hdf5"),
        (100.0, 1.0, "sonora_2121grid_feh2.0_co0.55.hdf5"),
        (1.0, 0.5, "sonora_2121grid_feh0.0_co0.27.hdf5"),
        (1.0, 2.0, "sonora_2121grid_feh0.0_co1.10.hdf5"),
    ],
)
def test_select_picaso4_preweighted_ck_file_nearest_grid(
    tmp_path: Path,
    metallicity_xsolar: float,
    c_to_o_xsolar: float,
    expected: str,
):
    nested_root = tmp_path / "opacities" / "preweighted"
    nested_root.mkdir(parents=True)
    expected_path = nested_root / expected
    expected_path.touch()

    selected = select_picaso4_preweighted_ck_file(
        _system(metallicity_xsolar, c_to_o_xsolar),
        ck_root=tmp_path,
    )

    assert selected == expected_path


def test_select_picaso4_preweighted_ck_file_missing_error_names_expected_file(tmp_path: Path):
    root = tmp_path / "empty_opacities"
    root.mkdir()

    with pytest.raises(FileNotFoundError) as excinfo:
        select_picaso4_preweighted_ck_file(_system(100.0, 1.0), ck_root=root)

    message = str(excinfo.value)
    assert "sonora_2121grid_feh2.0_co0.55.hdf5" in message
    assert str(root) in message


def test_configure_climate_inputs_sets_teff_and_initial_guess():
    class FakeClimateRun:
        def __init__(self):
            self.inputs = {
                "planet": {},
                "atmosphere": {
                    "profile": {
                        "pressure": np.geomspace(1.0e-4, 100.0, 12),
                        "temperature": np.linspace(300.0, 600.0, 12),
                    }
                },
            }
            self.climate_kwargs = None

        def effective_temp(self, teff):
            self.inputs["planet"]["T_eff"] = teff

        def inputs_climate(self, temp_guess, pressure, rfacv, moistgrad, rfaci, rcb_guess):
            self.climate_kwargs = {
                "temp_guess": temp_guess,
                "pressure": pressure,
                "rfacv": rfacv,
                "moistgrad": moistgrad,
                "rfaci": rfaci,
                "rcb_guess": rcb_guess,
            }

    cl_run = FakeClimateRun()
    system = _system(10.0, 1.0)
    system.teff_k = 425.0

    summary = configure_climate_inputs(cl_run, system)

    assert cl_run.inputs["planet"]["T_eff"] == 425.0
    assert summary["pressure"].shape == (12,)
    assert summary["temp_guess"].shape == (12,)
    assert summary["rcb_guess"] == 5
    assert cl_run.climate_kwargs["rcb_guess"] == 5
    assert cl_run.climate_kwargs["rfacv"] == 0.5
    assert cl_run.climate_kwargs["rfaci"] == 1.0
    assert cl_run.climate_kwargs["moistgrad"] is False


def test_run_real_picaso_model_default_does_not_run_exact_climate_qc(monkeypatch):
    output_grid = picaso_runner.wavelength_grid_um()
    out_ref = {
        "wavenumber": 1.0e4 / output_grid,
        "albedo": np.full(output_grid.size, 0.2),
        "fpfs_reflected": np.full(output_grid.size, 1.0e-8),
    }
    out_em = {
        "wavenumber": 1.0e4 / output_grid,
        "thermal": np.full(output_grid.size, 1.0e-6),
        "fpfs_thermal": np.full(output_grid.size, 1.0e-10),
    }

    import roadrunner.runner as runner

    def fake_run_picaso_once(*args, **kwargs):
        return out_ref, out_em, object(), object()

    def fake_extract_planet_fluxes(out_reflected, out_emission, grid, system):
        return grid, np.full(grid.size, 1.0), np.full(grid.size, 0.1)

    def fail_climate_qc(*args, **kwargs):
        raise AssertionError("exact climate QC should be opt-in")

    monkeypatch.setattr(runner, "run_picaso_once", fake_run_picaso_once)
    monkeypatch.setattr(runner, "extract_planet_fluxes", fake_extract_planet_fluxes)
    monkeypatch.setattr(runner, "run_picaso_climate_diagnostics_once", fail_climate_qc)

    row = {
        "picaso_tint_k": 500.0,
        "gravity_ms2": 10.0,
        "planet_radius_rearth": 2.0,
        "semi_major_au": 0.2,
        "phase_deg": 60.0,
        "star_teff_k": 3500.0,
        "star_radius_rsun": 0.45,
        "cloud_model": "virga",
        "cloud_fraction": 1.0,
        "c_to_o_picaso_tag": "100",
        "metallicity_xsolar": 10.0,
        "kzz_cm2_s": 1.0e9,
        "fsed": 3.0,
    }

    result = picaso_runner._run_real_picaso_model(row)

    assert "qc_diagnostics" not in result
    assert result["wavelength_um"].shape == output_grid.shape
    np.testing.assert_allclose(result["fpfs_reflection"], 1.0e-8)
