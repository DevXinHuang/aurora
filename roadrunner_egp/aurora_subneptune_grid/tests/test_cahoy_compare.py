from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.cahoy_compare import (
    compare_spectrum_pair,
    interpolate_aurora_to_cahoy_grid,
    load_aurora_albedo_spectrum,
)
from aurora_grid.cahoy_reference import load_cahoy_reference_spectrum, resolve_reference_root


def test_interpolate_aurora_to_cahoy_grid():
    wave = np.linspace(0.35, 1.0, 50)
    aurora = 0.2 + 0.1 * wave
    cahoy_wave = np.linspace(0.4, 0.9, 20)
    out = interpolate_aurora_to_cahoy_grid(wave, aurora, cahoy_wave)
    assert out.shape == cahoy_wave.shape
    assert np.allclose(out, 0.2 + 0.1 * cahoy_wave)


def test_compare_identical_spectra():
    wave = np.linspace(0.35, 1.0, 100)
    albedo = 0.15 + 0.2 * np.sin(6.0 * wave)
    cahoy = {"wavelength_um": wave, "albedo": albedo}
    aurora = {"wavelength_um": wave + 0.001, "albedo": albedo}
    metrics, arrays = compare_spectrum_pair(
        cahoy,
        aurora,
        cahoy_reference_name="Jupiter_1x_0.8AU_0deg.dat",
        run_index=0,
        output_nc="run_000000.nc",
        phase_deg=0.0,
    )
    assert metrics.rmse < 0.02
    assert arrays["residual"].shape == wave.shape


def test_load_aurora_albedo_spectrum_hdf5_fallback(tmp_path, monkeypatch):
    h5py = pytest.importorskip("h5py")
    path = tmp_path / "run_000123.nc"
    source_row = {"run_index": 123, "cahoy_reference_name": "Jupiter_1x_0.8AU_30deg.dat"}
    with h5py.File(path, "w") as handle:
        handle.create_dataset("wavelength_um", data=np.array([0.4, 0.5, 0.6]))
        handle.create_dataset("geometric_albedo", data=np.array([0.1, 0.2, 0.3]))
        handle.create_dataset("phase_angle_deg", data=30.0)
        handle.create_dataset("run_index", data=123)
        handle.attrs["source_manifest_row"] = json.dumps(source_row)

    def broken_open_dataset(*_args, **_kwargs):
        raise ValueError("found the following matches with the input file in xarray's IO backends: ['netcdf4', 'h5netcdf']")

    monkeypatch.setattr("aurora_grid.cahoy_compare.xr.open_dataset", broken_open_dataset)

    spectrum = load_aurora_albedo_spectrum(path)

    assert spectrum["run_index"] == 123
    assert spectrum["phase_deg"] == 30.0
    assert spectrum["cahoy_reference_name"] == "Jupiter_1x_0.8AU_30deg.dat"
    assert np.allclose(spectrum["albedo"], [0.1, 0.2, 0.3])


@pytest.mark.skipif(
    not resolve_reference_root().exists(),
    reason="Cahoy reference archive not installed",
)
def test_load_official_reference_sample():
    root = resolve_reference_root()
    sample = load_cahoy_reference_spectrum("Jupiter_1x_0.8AU_0deg.dat", reference_root=root)
    assert sample["wavelength_um"].min() >= 0.34
    assert sample["wavelength_um"].max() <= 1.01
    assert np.all(sample["albedo"] >= 0.0)
