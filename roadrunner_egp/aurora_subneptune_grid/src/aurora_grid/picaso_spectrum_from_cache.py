from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .io.climate_cache_schema import apply_climate_cache_to_case, load_climate_cache, row_from_climate_cache
from .naming import picaso_tag_to_cto
from .parameters import ROADRUNNER_ROOT
from .picaso_climate import _climate_row_to_system
from .picaso_runner import (
    _dry_run_model,
    _reflected_observables,
    wavelength_grid_um,
)
from .stellar_spectrum import configure_picaso_star, stellar_spectrum_attrs


def _merge_row(spectrum_row: dict[str, Any], climate_row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(climate_row)
    merged.update(spectrum_row)
    merged["run_index"] = int(spectrum_row.get("spectrum_index", spectrum_row.get("run_index", 0)))
    merged["run_id"] = str(spectrum_row.get("spectrum_run_id", spectrum_row.get("run_id", "")))
    merged["phase_deg"] = float(spectrum_row["phase_deg"])
    merged["output_nc"] = str(spectrum_row["output_nc"])
    return merged


def _dry_run_spectrum_from_cache(spectrum_row: dict[str, Any], climate_cache_path: str | Path) -> dict[str, Any]:
    state = load_climate_cache(climate_cache_path)
    climate_row = row_from_climate_cache(state)
    merged = _merge_row(spectrum_row, climate_row)
    model = _dry_run_model(merged)
    if state.thermal_planet_star_flux_ratio is not None:
        model["fpfs_emission"] = state.thermal_planet_star_flux_ratio
    if state.thermal_flux is not None:
        model["absolute_flux_thermal"] = state.thermal_flux
    model["wavelength_um"] = np.asarray(model.get("wavelength_um", state.wavelength_um), dtype=float)
    model.setdefault("picaso_metadata", {})["climate_cache_nc"] = str(climate_cache_path)
    return model


def _run_real_spectrum_from_cache(spectrum_row: dict[str, Any], climate_cache_path: str | Path) -> dict[str, Any]:
    if str(ROADRUNNER_ROOT) not in sys.path:
        sys.path.insert(0, str(ROADRUNNER_ROOT))

    from astropy import units as u

    from roadrunner.config import HAVE_PICASO, REFLECT_NUM_GANGLE, REFLECT_NUM_TANGLE, jdi
    from roadrunner.runner import extract_planet_fluxes

    assert HAVE_PICASO, "PICASO is required"

    state = load_climate_cache(climate_cache_path)
    climate_row = row_from_climate_cache(state)
    merged = _merge_row(spectrum_row, climate_row)
    system = _climate_row_to_system(merged, phase_deg=float(spectrum_row["phase_deg"]))
    output_grid = wavelength_grid_um()
    wave_range = [float(np.nanmin(output_grid)), float(np.nanmax(output_grid))]
    opa = jdi.opannection(wave_range=wave_range)

    case = jdi.inputs()
    g_cgs = 10 ** system.logg_cgs
    case.gravity(
        gravity=g_cgs,
        gravity_unit=u.cm / u.s**2,
        radius=system.rj,
        radius_unit=u.R_jup,
    )
    configure_picaso_star(case, opa, merged, verbose=True)
    apply_climate_cache_to_case(case, state, verbose=True)

    case.phase_angle(
        np.deg2rad(system.phase_deg),
        num_gangle=REFLECT_NUM_GANGLE,
        num_tangle=REFLECT_NUM_TANGLE,
    )
    out_ref = case.spectrum(opa, calculation="reflected", as_dict=True, full_output=True)
    albedo, fpfs_reflection = _reflected_observables(out_ref, system, output_grid)

    result: dict[str, Any] = {
        "wavelength_um": output_grid,
        "fpfs_reflection": fpfs_reflection,
        "albedo": albedo,
        "picaso_out_reflected": out_ref,
        "picaso_case": case,
        "picaso_opacity": opa,
        "picaso_metadata": {
            "dry_run": False,
            "climate_cache_nc": str(climate_cache_path),
            "climate_key": str(spectrum_row.get("climate_key", state.attrs.get("climate_key", ""))),
            "atmosphere_source": "cached",
            "thermal_source": "cached",
            **stellar_spectrum_attrs(merged),
        },
    }
    if state.thermal_planet_star_flux_ratio is not None:
        result["fpfs_emission"] = state.thermal_planet_star_flux_ratio
    if state.thermal_flux is not None:
        result["absolute_flux_thermal"] = state.thermal_flux

    if result.get("fpfs_emission") is not None:
        denominator = fpfs_reflection + result["fpfs_emission"]
        result["reflected_fraction"] = np.divide(
            fpfs_reflection,
            denominator,
            out=np.zeros_like(fpfs_reflection),
            where=denominator > 0,
        )

    try:
        out_em = {"wavenumber": out_ref["wavenumber"], "thermal": np.zeros_like(out_ref["wavenumber"])}
        if state.thermal_flux is not None:
            _, fp_reflected_abs, _ = extract_planet_fluxes(out_ref, out_em, output_grid, system)
            result["absolute_flux_reflected"] = fp_reflected_abs
    except Exception:
        pass

    if "pt_profile" not in result and case is not None:
        try:
            result["pt_profile"] = case.inputs["atmosphere"]["profile"]
        except Exception:
            pass

    return result


def run_picaso_spectrum_from_cache(
    spectrum_row: dict[str, Any],
    climate_cache_path: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        return _dry_run_spectrum_from_cache(spectrum_row, climate_cache_path)
    return _run_real_spectrum_from_cache(spectrum_row, climate_cache_path)
