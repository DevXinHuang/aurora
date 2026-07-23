from __future__ import annotations

import inspect
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from aurora_grid.tint.config import (
    EXPECTED_MODEL_COUNT,
    QUENCH_FAMILIES,
    REQUIRED_SPECIES,
    load_experiment,
    manifests,
    wavelength_grid,
)
from aurora_grid.tint.netcdf import build_dataset, validate_dataset


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "params" / "tint_sensitivity_36.yaml"
EQUILIBRIUM_CONFIG = ROOT / "params" / "tint_sensitivity_equilibrium_36.yaml"


def test_exactly_36_unique_models() -> None:
    rows = manifests(load_experiment(CONFIG))
    assert len(rows) == EXPECTED_MODEL_COUNT == 36
    assert len({row["run_id"] for row in rows}) == 36
    assert {row["case_id"] for row in rows} == {
        "k2_18b_observed", "gj_1214b_low", "gj_1214b_observed"
    }
    assert {row["tint_k"] for row in rows} == {25.0, 50.0, 100.0}
    assert {row["cloud_id"] for row in rows} == {"cloud_free", "fully_cloudy_virga"}
    assert {row["metallicity_xsolar"] for row in rows} == {1.0, 100.0}


def test_sensitivity_2_equilibrium_grid_is_separate_and_exact() -> None:
    rows = manifests(load_experiment(EQUILIBRIUM_CONFIG))
    assert len(rows) == EXPECTED_MODEL_COUNT == 36
    assert len({row["run_id"] for row in rows}) == 36
    assert {row["chemistry_mode"] for row in rows} == {"equilibrium_only"}
    assert {row["diseq_chem"] for row in rows} == {False}
    assert {row["self_consistent_kzz"] for row in rows} == {False}
    assert {row["quench"] for row in rows} == {False}
    assert {row["pressure_bottom_bar"] for row in rows} == {10.0 ** 1.5}
    assert {row["pressure_levels"] for row in rows} == {61}
    assert {Path(row["output_directory"]).name for row in rows} == {
        "tint_sensitivity_equilibrium_36"
    }


def test_constant_resolution_grid() -> None:
    row = manifests(load_experiment(CONFIG))[0]
    wave = wavelength_grid(row)
    assert wave[0] == 0.6
    assert wave[-1] == 15.0
    assert np.allclose(1.0 / np.diff(np.log(wave)), 1000.0, rtol=5e-4)


def test_hot_pressure_grids_enclose_quench_domain_at_original_resolution() -> None:
    rows = manifests(load_experiment(CONFIG))
    hot = {row["tint_k"]: row for row in rows if row["case_id"] == "gj_1214b_observed"}
    assert {tint: row["pressure_bottom_bar"] for tint, row in hot.items()} == {
        25.0: 1e6, 50.0: 1e5, 100.0: 1e4,
    }
    assert all(row["pressure_log10_spacing"] == 0.125 for row in rows)
    assert all(row["pressure_levels"] == 61 for row in rows if row["equilibrium_temperature_k"] == 255.0)


def test_runner_has_required_picaso_controls() -> None:
    from aurora_grid.tint import runner

    source = inspect.getsource(runner.run_model)
    assert "chemeq_visscher_2121" in source
    assert "diseq_chem=True" in source
    assert "self_consistent_kzz=False" in source
    assert "quench=True" in source
    assert "diseq_chem=False" in source
    assert "quench=False" in source
    assert "mass_unit=u.M_earth" in source
    assert 'case.inputs["planet"]["gravity"]' in source


def test_hot_quench_domain_retry_uses_picaso_deep_extension() -> None:
    from aurora_grid.tint.runner import _install_quench_domain_extension

    atmosphere_type = namedtuple(
        "Atmosphere", "dtdp mmw_layer nlevel t_level p_level condensables "
        "condensable_abundances condensable_weights scale_height"
    )
    atmosphere = atmosphere_type(
        np.full(4, 0.2), np.full(4, 2.3), 5, np.linspace(500.0, 800.0, 5),
        np.geomspace(1e-6, 31.6, 5), (), (), (), np.ones(5),
    )
    seen_pressure_maxima = []

    def fake_quench(candidate, kz, grav, mh_linear, **kwargs):
        seen_pressure_maxima.append(float(candidate.p_level[-1]))
        if candidate.p_level[-1] < 1e6:
            raise Exception("CO/H2O/CH4 mixing across Pressure Ranges, Start with deeper Pressure Grid")
        return {"CO-CH4-H2O": candidate.nlevel - 2}, np.ones(candidate.nlevel)

    climate = SimpleNamespace(get_quench_levels=fake_quench)
    tracker = _install_quench_domain_extension(climate)
    levels, _ = climate.get_quench_levels(atmosphere, np.full(5, 1e10), 1065.0, 1.0)
    assert seen_pressure_maxima == [31.6, 1e6]
    assert levels["CO-CH4-H2O"] >= atmosphere.nlevel
    assert tracker["applied"] is True
    assert tracker["retry_count"] == 1
    assert tracker["maximum_pressure_bar"] == 1e6
    assert tracker["levels"]["CO-CH4-H2O"] == levels["CO-CH4-H2O"]
    assert 31.6 < tracker["pressures_bar"]["CO-CH4-H2O"] < 1e6


def test_cold_picaso_internal_extension_maps_quench_indices_to_deep_pressure() -> None:
    from aurora_grid.tint.runner import _install_quench_domain_extension

    atmosphere_type = namedtuple(
        "Atmosphere", "dtdp mmw_layer nlevel t_level p_level condensables "
        "condensable_abundances condensable_weights scale_height"
    )
    atmosphere = atmosphere_type(
        np.full(4, 0.2), np.full(4, 2.3), 5, np.linspace(200.0, 800.0, 5),
        np.geomspace(1e-6, 31.6, 5), (), (), (), np.ones(5),
    )

    def fake_quench(candidate, kz, grav, mh_linear, **kwargs):
        return {"CO-CH4-H2O": candidate.nlevel + 3}, np.ones(candidate.nlevel + 10)

    climate = SimpleNamespace(get_quench_levels=fake_quench)
    tracker = _install_quench_domain_extension(climate)
    climate.get_quench_levels(atmosphere, np.full(5, 1e10), 1065.0, 1.0)
    assert tracker["levels"]["CO-CH4-H2O"] == 8
    assert 31.6 < tracker["pressures_bar"]["CO-CH4-H2O"] < 1e6


def test_thermal_ratio_correction_restores_matching_flux_density_units() -> None:
    from aurora_grid.tint.runner import _correct_thermal_flux_ratio

    row = manifests(load_experiment(CONFIG))[0]
    wavenumber = np.array([1000.0, 900.0, 800.0])
    wavelength_cm = 1.0 / wavenumber
    widths = np.array([
        abs(wavelength_cm[1] - wavelength_cm[0]),
        abs(wavelength_cm[2] - wavelength_cm[1]),
        abs(wavelength_cm[2] - wavelength_cm[1]),
    ])
    output = {
        "wavenumber": wavenumber,
        "fpfs_thermal": np.array([2.0, 3.0, 4.0]),
        "thermal": np.array([10.0, 20.0, 30.0]),
        "full_output": {"star": {"flux": widths * 2.0e5}},
    }
    corrected, diagnostics = _correct_thermal_flux_ratio(output, row)
    expected = output["thermal"] / 2.0e5 * diagnostics["planet_star_radius_ratio_squared"]
    assert np.allclose(corrected["fpfs_thermal"], expected)
    assert diagnostics["maximum_corrected_ratio"] == np.max(corrected["fpfs_thermal"])


def test_virga_particle_guard_clamps_only_below_floor_roots() -> None:
    from aurora_grid.tint.runner import _install_virga_minimum_particle_guard

    def residual(radius, *args, **kwargs):
        return 2.0 if radius <= 1e-8 else -3.0

    virga = SimpleNamespace(vfall_find_root=residual)
    tracker = _install_virga_minimum_particle_guard(virga)
    assert virga.vfall_find_root(1e-8) == 0.0
    assert virga.vfall_find_root(1e-7) == -3.0
    assert tracker["clamp_count"] == 1


def test_zero_cloud_convergence_guard_only_changes_zero_tolerance() -> None:
    from aurora_grid.tint.runner import _install_zero_cloud_convergence_guard

    def update_clouds(*args, **kwargs):
        return "cloud", "frame", 0.0, 0.0, "profiles", "parameters"

    climate = SimpleNamespace(update_clouds=update_clouds)
    tracker = _install_zero_cloud_convergence_guard(climate)
    result = climate.update_clouds()
    assert result[2] == 0.0
    assert result[3] > 0.0
    assert tracker["adjustment_count"] == 1

    def nonzero_clouds(*args, **kwargs):
        return "cloud", "frame", 0.2, 0.3, "profiles", "parameters"

    climate = SimpleNamespace(update_clouds=nonzero_clouds)
    tracker = _install_zero_cloud_convergence_guard(climate)
    result = climate.update_clouds()
    assert result[2:4] == (0.2, 0.3)
    assert tracker["adjustment_count"] == 0


def test_self_contained_netcdf_schema() -> None:
    row = manifests(load_experiment(CONFIG))[0]
    wave = wavelength_grid(row)
    nlevel = 5
    result = {
        "wavelength_um": wave,
        "pressure_bar": np.geomspace(1e-6, 100.0, nlevel),
        "temperature_k": np.linspace(200.0, 700.0, nlevel),
        "kzz_cm2_s_profile": np.full(nlevel, 1e10),
        "mole_fraction": np.full((nlevel, len(REQUIRED_SPECIES)), 1e-8),
        "equilibrium_mole_fraction": np.full((nlevel, len(REQUIRED_SPECIES)), 2e-8),
        "quench_pressures_bar": {name: 1.0 for name in QUENCH_FAMILIES},
        "transmission_depth": np.full(wave.size, 1e-3),
        "thermal_planet_star_flux_ratio": np.full(wave.size, 1e-7),
        "reflected_planet_star_flux_ratio": np.full(wave.size, 1e-8),
        "geometric_albedo": np.full(wave.size, 0.2),
        "climate_converged": True,
        "quench_enabled": True,
        "quench_applied": True,
        "quench_profile_differs_from_equilibrium": True,
        "diseq_chem": True,
        "self_consistent_kzz": False,
        "max_quench_log10_difference": 1.0,
        "selected_opacity_file": "test.hdf5",
        "runtime_seconds": 1.0,
        "thermal_flux_ratio_correction": {
            "minimum_native_bin_width_cm": 1e-8,
            "maximum_native_bin_width_cm": 1e-6,
        },
    }
    ds = build_dataset(result, row)
    assert validate_dataset(ds, row) == []
    assert tuple(ds["species"].values) == REQUIRED_SPECIES
    assert tuple(ds["quench_family"].values) == QUENCH_FAMILIES
    ds["climate_converged"] = np.int8(0)
    assert "climate solution is not converged" in validate_dataset(ds, row)


def test_equilibrium_only_netcdf_has_explicit_false_quench_provenance() -> None:
    row = manifests(load_experiment(EQUILIBRIUM_CONFIG))[0]
    wave = wavelength_grid(row)
    nlevel = 5
    abundances = np.full((nlevel, len(REQUIRED_SPECIES)), 1e-8)
    result = {
        "wavelength_um": wave,
        "pressure_bar": np.geomspace(1e-6, 10.0 ** 1.5, nlevel),
        "temperature_k": np.linspace(200.0, 700.0, nlevel),
        "kzz_cm2_s_profile": np.full(nlevel, 1e10),
        "mole_fraction": abundances,
        "equilibrium_mole_fraction": abundances.copy(),
        "quench_pressures_bar": {},
        "transmission_depth": np.full(wave.size, 1e-3),
        "thermal_planet_star_flux_ratio": np.full(wave.size, 1e-7),
        "reflected_planet_star_flux_ratio": np.full(wave.size, 1e-8),
        "geometric_albedo": np.full(wave.size, 0.2),
        "climate_converged": True,
        "chemistry_mode": "equilibrium_only",
        "quench_enabled": False,
        "quench_applied": False,
        "quench_profile_differs_from_equilibrium": False,
        "diseq_chem": False,
        "self_consistent_kzz": False,
        "max_quench_log10_difference": 0.0,
        "max_equilibrium_consistency_log10_difference": 3.8e-4,
        "equilibrium_consistency_tolerance_dex": 1e-2,
        "selected_opacity_file": "test.hdf5",
        "runtime_seconds": 1.0,
        "thermal_flux_ratio_correction": {
            "minimum_native_bin_width_cm": 1e-8,
            "maximum_native_bin_width_cm": 1e-6,
        },
    }
    ds = build_dataset(result, row)
    assert validate_dataset(ds, row) == []
    assert ds.attrs["chemistry_mode"] == "equilibrium_only"
    assert ds.attrs["kzz_role"] == "virga_only_not_chemistry"
    assert int(ds["diseq_chem"].item()) == 0
    assert int(ds["quench_enabled"].item()) == 0
    assert np.all(np.isnan(ds["quench_pressure_bar"].values))


def test_analysis_contract_has_31_png_pdf_figure_designs() -> None:
    from aurora_grid.tint.analysis import expected_figure_stems

    stems = expected_figure_stems()
    assert len(stems) == 31
    assert len(set(stems)) == 31
    assert len(stems) * 2 == 62
    assert sum(stem.startswith("pt_") for stem in stems) == 3
    assert sum(stem.startswith("spectra_") for stem in stems) == 9
    assert sum(stem.startswith("abundance_") for stem in stems) == 12


def test_analysis_summary_retains_all_36_manifest_rows() -> None:
    from aurora_grid.tint.analysis import build_summary_table

    rows = manifests(load_experiment(CONFIG))
    table = build_summary_table(rows, [])
    assert len(table) == 36
    assert table["run_index"].tolist() == list(range(36))
    for species in REQUIRED_SPECIES:
        assert f"{species}_mole_fraction_at_1mbar" in table


def test_analysis_pairs_all_tint_25_and_100_endpoints() -> None:
    from aurora_grid.tint.analysis import tint_endpoint_pairs

    rows = manifests(load_experiment(CONFIG))
    models = [
        SimpleNamespace(key=(row["case_id"], row["cloud_id"], row["metallicity_xsolar"], row["tint_k"]))
        for row in rows
    ]
    pairs = tint_endpoint_pairs(models)
    assert len(pairs) == 12
    assert all(low.key[-1] == 25.0 and high.key[-1] == 100.0 for low, high in pairs.values())


def test_pressure_axis_is_logarithmic_and_increases_downward() -> None:
    import matplotlib.pyplot as plt
    from aurora_grid.tint.analysis import _set_pressure_axis

    fig, ax = plt.subplots()
    _set_pressure_axis(ax)
    assert ax.get_yscale() == "log"
    assert ax.yaxis_inverted()
    plt.close(fig)


def test_static_figure_export_writes_png_and_pdf(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt
    from aurora_grid.tint.analysis import _save_figure

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    stem = tmp_path / "example"
    _save_figure(fig, stem, "partial", 1)
    assert stem.with_suffix(".png").is_file()
    assert stem.with_suffix(".pdf").is_file()
