from __future__ import annotations

import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid import picaso_runner  # noqa: E402
from aurora_grid.io.netcdf_schema import build_aurora_run_dataset  # noqa: E402
from roadrunner import runner as runner_module  # noqa: E402
from roadrunner.runner import (  # noqa: E402
    _patch_virga_calc_optics_sublayer_guard,
    configure_climate_inputs,
    reflected_phase_angle_rad,
    select_picaso4_preweighted_ck_file,
)
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


def test_reflected_phase_angle_rad_clamps_exact_180():
    clamped = reflected_phase_angle_rad(180.0)
    assert clamped < np.pi
    assert np.isclose(clamped, np.nextafter(np.pi, 0.0))
    assert np.isclose(reflected_phase_angle_rad(179.0), np.deg2rad(179.0))
    assert np.isclose(reflected_phase_angle_rad(0.0), 0.0)


def test_patch_virga_calc_optics_sublayer_guard(monkeypatch):
    fake_virga_pkg = types.ModuleType("virga")
    fake_justdoit = types.ModuleType("virga.justdoit")
    fake_justdoit.np = np

    # Intentionally mirrors the buggy guard string from Virga.
    source = """
def calc_optics(nwave, qc, qt, rg, reff, ndz, radius, dr, qext, qscat, cos_qscat, sig, rmin, rmax, verbose=False):
    nz = qc.shape[0]
    ngas = qc.shape[1]
    opd_layer = np.zeros((nz, ngas))
    for igas in range(ngas):
        ibot = nz - 3
        if ibot >= nz -2:
            pass
        else:
            opd_layer[ibot+3,igas] = opd_layer[ibot,igas] * 0.01
    return opd_layer, None, None, None
"""
    exec(source, fake_justdoit.__dict__)

    fake_virga_pkg.justdoit = fake_justdoit
    monkeypatch.setitem(sys.modules, "virga", fake_virga_pkg)
    monkeypatch.setitem(sys.modules, "virga.justdoit", fake_justdoit)
    monkeypatch.setattr(runner_module.inspect, "getsource", lambda fn: source)
    monkeypatch.setattr(runner_module, "_VIRGA_SUBLAYER_PATCH_APPLIED", False)

    assert _patch_virga_calc_optics_sublayer_guard(verbose=False) is True

    qc = np.zeros((60, 1), dtype=float)
    qt = np.zeros_like(qc)
    rg = np.zeros_like(qc)
    reff = np.zeros_like(qc)
    ndz = np.zeros_like(qc)
    radius = np.array([1.0], dtype=float)
    dr = np.array([1.0], dtype=float)
    qext = np.zeros((1, 1, 1), dtype=float)
    qscat = np.zeros_like(qext)
    cos_qscat = np.zeros_like(qext)

    opd_layer, _w0, _g0, _opd_gas = fake_justdoit.calc_optics(
        1, qc, qt, rg, reff, ndz, radius, dr, qext, qscat, cos_qscat, 2.0, 1.0e-8, 1.0
    )
    assert opd_layer.shape == (60, 1)


def _real_row() -> dict[str, object]:
    return {
        "run_index": 3,
        "model_name": "test",
        "run_id": "run-000003",
        "picaso_tint_k": 500.0,
        "gravity_ms2": 10.0,
        "planet_radius_rearth": 2.0,
        "semi_major_au": 0.2,
        "phase_deg": 60.0,
        "star_teff_k": 3500.0,
        "star_radius_rsun": 0.45,
        "stellar_luminosity_lsun": 0.03,
        "insolation_searth": 0.7,
        "equilibrium_temperature_k": 500.0,
        "cloud_model": "virga",
        "cloud_fraction": 1.0,
        "c_to_o_xsolar": 1.0,
        "c_to_o_picaso_tag": "100",
        "metallicity_xsolar": 10.0,
        "kzz_cm2_s": 1.0e9,
        "logkzz": 9.0,
        "fsed": 3.0,
        "output_nc": "run.nc",
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


def test_picaso_climate_mode_uses_converged_pt_and_saves_schema(monkeypatch):
    output_grid = picaso_runner.wavelength_grid_um()
    climate_pressure = np.array([1.0e-4, 1.0e-3, 1.0e-2, 1.0e-1])
    climate_temperature = np.array([410.0, 430.0, 455.0, 480.0])
    out_ref = {
        "wavenumber": 1.0e4 / output_grid,
        "albedo": np.full(output_grid.size, 0.2),
        "fpfs_reflected": np.full(output_grid.size, 1.0e-8),
        "full_output": {
            "layer": {
                "cloud": {
                    "opd": np.ones((3, output_grid.size)) * 0.1,
                    "w0": np.ones((3, output_grid.size)) * 0.5,
                    "g0": np.ones((3, output_grid.size)) * 0.2,
                }
            }
        },
    }
    out_em = {
        "wavenumber": 1.0e4 / output_grid,
        "thermal": np.full(output_grid.size, 1.0e-6),
        "fpfs_thermal": np.full(output_grid.size, 1.0e-10),
    }
    climate_out = {
        "pressure": climate_pressure,
        "temperature": climate_temperature,
        "converged": True,
    }
    qc_diagnostics = {
        "climate_converged": True,
        "climate_opacity_method": "preweighted",
        "selected_ck_file": "/fake/sonora_2121grid_feh1.0_co0.55.hdf5",
        "qc_dtdp": np.array([0.1, 0.2, 0.3, 0.4]),
        "fnet_irfnet": np.array([1.0e-4, 2.0e-4, 3.0e-4, 4.0e-4]),
        "flux_balance": np.array([1.0e-5, 2.0e-5, 3.0e-5, 4.0e-5]),
        "qc_brightness_temperature": np.full(output_grid.size + 2, 350.0),
        "qc_brightness_wavelength": np.linspace(1.0, 5.0, output_grid.size + 2),
    }

    class FakeCase:
        def __init__(self):
            self.inputs = {
                "atmosphere": {
                    "profile": {
                        "pressure": np.array([9.0, 8.0, 7.0, 6.0]),
                        "temperature": np.array([900.0, 800.0, 700.0, 600.0]),
                        "H2": np.full(4, 0.84),
                        "He": np.full(4, 0.15),
                        "H2O": np.full(4, 0.01),
                    }
                }
            }

    def fake_climate_model_once(*args, **kwargs):
        return out_ref, out_em, climate_out, qc_diagnostics, FakeCase(), object()

    import roadrunner.runner as runner

    monkeypatch.setattr(runner, "run_picaso_climate_model_once", fake_climate_model_once)
    monkeypatch.setattr(
        runner,
        "extract_planet_fluxes",
        lambda out_reflected, out_emission, grid, system: (
            grid,
            np.full(grid.size, 1.0),
            np.full(grid.size, 0.1),
        ),
    )

    row = _real_row()
    result = picaso_runner._run_real_picaso_model(row, atmosphere_source="picaso_climate")
    dataset = build_aurora_run_dataset(result, row)

    np.testing.assert_allclose(result["pt_profile"]["pressure"], climate_pressure)
    np.testing.assert_allclose(result["pt_profile"]["temperature"], climate_temperature)
    np.testing.assert_allclose(dataset["pressure_bar"].values, climate_pressure)
    np.testing.assert_allclose(dataset["temperature_k"].values, climate_temperature)
    assert "reflected_planet_star_flux_ratio" in dataset
    assert "thermal_flux" in dataset
    assert "fnet_irfnet" in dataset
    assert "qc_dtdp" in dataset
    assert "flux_balance" in dataset
    assert "qc_brightness_temperature" in dataset
    assert "qc_brightness_wavelength_um" in dataset
    assert dataset["qc_brightness_temperature"].shape == dataset["qc_brightness_wavelength_um"].shape
    assert dataset["qc_brightness_temperature"].shape != dataset["wavelength_um"].shape
    assert dataset.attrs["climate_converged"] == 1
    assert dataset.attrs["climate_opacity_method"] == "preweighted"
    assert dataset.attrs["selected_ck_file"].endswith("sonora_2121grid_feh1.0_co0.55.hdf5")


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
