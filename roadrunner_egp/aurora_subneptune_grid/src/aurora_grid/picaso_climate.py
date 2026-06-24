from __future__ import annotations

import math
import sys
from typing import Any

import numpy as np

from .naming import picaso_tag_to_cto
from .parameters import ROADRUNNER_ROOT
from .picaso_runner import (
    R_EARTH_TO_R_JUP,
    _dry_run_model,
    _thermal_fpfs,
    wavelength_grid_um,
)
from .stellar_spectrum import configure_picaso_star, resolve_stellar_spectrum_path, stellar_spectrum_attrs


def _fsed_from_row(row: dict[str, Any]) -> float:
    value = row.get("fsed")
    if value in (None, ""):
        return 1.0
    return float(value)


def _climate_row_to_system(row: dict[str, Any], phase_deg: float = 0.0) -> Any:
    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    if "c_to_o_xsolar" in row:
        c_to_o = float(row["c_to_o_xsolar"])
    else:
        c_to_o = picaso_tag_to_cto(str(row.get("c_to_o_picaso_tag", "100")))
    metallicity_xsolar = float(row["metallicity_xsolar"])
    log_mh = math.log10(metallicity_xsolar)

    if str(ROADRUNNER_ROOT) not in sys.path:
        sys.path.insert(0, str(ROADRUNNER_ROOT))

    from roadrunner.system import SystemParams

    return SystemParams(
        teff_k=float(row["picaso_tint_k"]),
        logg_cgs=math.log10(float(row["gravity_ms2"]) * 100.0),
        rj=float(row["planet_radius_rearth"]) * R_EARTH_TO_R_JUP,
        a_au=float(row["semi_major_au"]),
        phase_deg=float(phase_deg),
        tstar_k=float(row["star_teff_k"]),
        rstar_rsun=float(row["star_radius_rsun"]),
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        bond_albedo=0.0,
        chem_c_o=c_to_o,
        chem_log_mh=log_mh,
        kzz_cgs=float(row["kzz_cm2_s"]),
        virga_fsed=_fsed_from_row(row),
    )


def _dry_run_climate(row: dict[str, Any]) -> dict[str, Any]:
    climate_row = dict(row)
    climate_row["phase_deg"] = 0.0
    spec = row.get("stellar_spectrum_filename")
    if spec:
        spectrum_path = resolve_stellar_spectrum_path(str(spec))
        print(f"Using custom stellar spectrum: {spectrum_path}")
    model = _dry_run_model(climate_row)
    wavelength = np.asarray(model["wavelength_um"], dtype=float)
    metadata = {
        "dry_run": True,
        "atmosphere_source": "picaso",
        "thermal_source": "picaso",
        "cloud_model": str(row.get("cloud_model", "none")),
        **stellar_spectrum_attrs(row),
    }
    return {
        "wavelength_um": wavelength,
        "fpfs_emission": model.get("fpfs_emission"),
        "absolute_flux_thermal": model.get("absolute_flux_thermal"),
        "pt_profile": model.get("pt_profile"),
        "cloud_profile": model.get("cloud_profile"),
        "picaso_case": None,
        "picaso_opacity": None,
        "picaso_out_emission": None,
        "picaso_metadata": metadata,
    }


def _run_real_picaso_climate(row: dict[str, Any]) -> dict[str, Any]:
    if str(ROADRUNNER_ROOT) not in sys.path:
        sys.path.insert(0, str(ROADRUNNER_ROOT))

    from astropy import units as u

    from roadrunner.config import HAVE_PICASO, THERMAL_NUM_GANGLE, THERMAL_NUM_TANGLE, jdi
    from roadrunner.runner import configure_picaso_atmosphere, extract_planet_fluxes

    assert HAVE_PICASO, "PICASO is required"

    output_grid = wavelength_grid_um()
    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    system = _climate_row_to_system(row, phase_deg=0.0)
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
    configure_picaso_star(case, opa, row, verbose=True)

    configure_picaso_atmosphere(
        case,
        system,
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        verbose=True,
    )

    case.phase_angle(
        0.0,
        num_gangle=THERMAL_NUM_GANGLE,
        num_tangle=THERMAL_NUM_TANGLE,
    )
    out_em = case.spectrum(opa, calculation="thermal", as_dict=True, full_output=True)
    fpfs_emission = _thermal_fpfs(out_em, output_grid)
    result: dict[str, Any] = {
        "wavelength_um": output_grid,
        "fpfs_emission": fpfs_emission,
        "picaso_out_emission": out_em,
        "picaso_case": case,
        "picaso_opacity": opa,
        "picaso_metadata": {
            "dry_run": False,
            "atmosphere_source": "picaso",
            "thermal_source": "picaso",
            "cloud_model": cloud_model,
            **stellar_spectrum_attrs(row),
        },
    }
    try:
        _, _, fp_thermal_abs = extract_planet_fluxes(
            {"wavenumber": out_em["wavenumber"], "albedo": np.zeros_like(out_em["wavenumber"])},
            out_em,
            output_grid,
            system,
        )
        result["absolute_flux_thermal"] = fp_thermal_abs
    except Exception:
        pass
    return result


def run_picaso_climate(row: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return _dry_run_climate(row)
    return _run_real_picaso_climate(row)
