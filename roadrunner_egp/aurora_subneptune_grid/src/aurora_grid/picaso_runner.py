from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .naming import picaso_tag_to_cto
from .parameters import ROADRUNNER_ROOT


WAVELENGTH_MIN_UM = 0.3
WAVELENGTH_MAX_UM = 2.5
WAVELENGTH_POINTS = 2201
R_EARTH_TO_R_JUP = 0.0892141056
R_EARTH_AU = 4.263521245e-5


def wavelength_grid_um() -> np.ndarray:
    return np.linspace(WAVELENGTH_MIN_UM, WAVELENGTH_MAX_UM, WAVELENGTH_POINTS)


def _interp_native_to_grid(
    native_wavelength_um: np.ndarray,
    native_values: np.ndarray,
    output_grid_um: np.ndarray,
    *,
    left: float | None = None,
    right: float | None = None,
) -> np.ndarray:
    native_wavelength_um = np.asarray(native_wavelength_um, dtype=float)
    native_values = np.asarray(native_values, dtype=float)
    order = np.argsort(native_wavelength_um)
    sorted_wavelength = native_wavelength_um[order]
    sorted_values = native_values[order]
    if left is None:
        left = float(sorted_values[0])
    if right is None:
        right = float(sorted_values[-1])
    return np.interp(output_grid_um, sorted_wavelength, sorted_values, left=left, right=right)


def _reflected_observables(out_reflected: dict[str, Any], sys_params: Any, output_grid_um: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    native_wavelength_um = 1.0e4 / np.asarray(out_reflected["wavenumber"], dtype=float)
    native_albedo = np.asarray(out_reflected["albedo"], dtype=float)

    fpfs_data = out_reflected.get("fpfs_reflected")
    if isinstance(fpfs_data, np.ndarray):
        native_fpfs = np.asarray(fpfs_data, dtype=float)
    else:
        from astropy.constants import R_jup, au

        rp_m = float(sys_params.rj) * R_jup.value
        a_m = float(sys_params.a_au) * au.value
        native_fpfs = native_albedo * (rp_m / a_m) ** 2

    albedo = _interp_native_to_grid(native_wavelength_um, native_albedo, output_grid_um)
    fpfs_reflection = _interp_native_to_grid(
        native_wavelength_um,
        native_fpfs,
        output_grid_um,
        left=0.0,
        right=0.0,
    )
    return np.nan_to_num(albedo), np.nan_to_num(fpfs_reflection)


def _thermal_fpfs(out_emission: dict[str, Any], output_grid_um: np.ndarray) -> np.ndarray | None:
    fpfs_data = out_emission.get("fpfs_thermal")
    if not isinstance(fpfs_data, np.ndarray):
        return None
    native_wavelength_um = 1.0e4 / np.asarray(out_emission["wavenumber"], dtype=float)
    return np.nan_to_num(
        _interp_native_to_grid(
            native_wavelength_um,
            np.asarray(fpfs_data, dtype=float),
            output_grid_um,
            left=0.0,
            right=0.0,
        )
    )


def _dry_run_model(row: dict[str, Any]) -> dict[str, Any]:
    wavelength = np.linspace(WAVELENGTH_MIN_UM, WAVELENGTH_MAX_UM, 128)
    radius_au = float(row["planet_radius_rearth"]) * R_EARTH_AU
    semi_major_au = float(row["semi_major_au"])
    cloud_boost = 1.0 + 0.45 * float(row["cloud_fraction"])
    metallicity_damping = 1.0 / (1.0 + 0.08 * math.log10(float(row["metallicity_xsolar"])))
    phase_scale = max(0.02, math.cos(math.radians(float(row["phase_deg"]) / 2.0)) ** 2)

    blue_slope = 0.07 * (0.5 / wavelength) ** 1.5
    water_feature = 0.025 * np.exp(-0.5 * ((wavelength - 1.4) / 0.08) ** 2)
    methane_feature = 0.018 * np.exp(-0.5 * ((wavelength - 1.7) / 0.09) ** 2)
    albedo = np.clip(cloud_boost * metallicity_damping * (0.16 + blue_slope - water_feature - methane_feature), 0.01, 0.85)
    fpfs_reflection = albedo * (radius_au / semi_major_au) ** 2 * phase_scale
    fpfs_emission = 2.5e-9 * (float(row["picaso_tint_k"]) / 300.0) ** 4 * np.exp(-((wavelength - 2.2) / 1.2) ** 2)
    reflected_fraction = np.divide(
        fpfs_reflection,
        fpfs_reflection + fpfs_emission,
        out=np.zeros_like(fpfs_reflection),
        where=(fpfs_reflection + fpfs_emission) > 0,
    )
    pressure = np.geomspace(1.0e-4, 300.0, 12)
    temperature = np.linspace(0.7, 1.25, pressure.size) * float(row["picaso_tint_k"])
    h2o = np.full(pressure.size, min(5.0e-2, 1.0e-3 * float(row["metallicity_xsolar"])))
    ch4 = np.full(pressure.size, min(2.0e-2, 5.0e-4 * float(row["metallicity_xsolar"])))
    he = np.full(pressure.size, 0.15)
    h2 = np.clip(1.0 - he - h2o - ch4, 0.0, 1.0)
    nlayer = pressure.size - 1
    layer_shape = (nlayer, wavelength.size)
    if float(row["cloud_fraction"]) == 0.0:
        opd = np.zeros(layer_shape)
        w0 = np.zeros(layer_shape)
        g0 = np.zeros(layer_shape)
    else:
        layer_scale = np.exp(-0.5 * ((np.arange(nlayer) - 0.45 * nlayer) / max(1.0, 0.2 * nlayer)) ** 2)
        spectral_scale = 0.4 + 0.6 * np.exp(-0.5 * ((wavelength - 0.65) / 0.28) ** 2)
        opd = 0.08 * float(row["cloud_fraction"]) * layer_scale[:, None] * spectral_scale[None, :]
        w0 = np.clip(0.72 + 0.12 * np.cos(2.0 * np.pi * (wavelength - wavelength.min()) / np.ptp(wavelength)), 0.0, 1.0)
        w0 = np.broadcast_to(w0, layer_shape).copy()
        g0 = np.broadcast_to(np.full(wavelength.size, 0.35), layer_shape).copy()
    absolute_flux_reflected = fpfs_reflection * 1.0e-6
    absolute_flux_thermal = fpfs_emission * 1.0e-6

    return {
        "wavelength_um": wavelength,
        "fpfs_reflection": fpfs_reflection,
        "albedo": albedo,
        "fpfs_emission": fpfs_emission,
        "reflected_fraction": reflected_fraction,
        "absolute_flux_reflected": absolute_flux_reflected,
        "absolute_flux_thermal": absolute_flux_thermal,
        "pt_profile": {
            "pressure": pressure,
            "temperature": temperature,
            "H2": h2,
            "He": he,
            "H2O": h2o,
            "CH4": ch4,
        },
        "cloud_profile": {
            "wavelength_um": wavelength,
            "opd": opd,
            "w0": w0,
            "g0": g0,
        },
        "mean_molecular_weight_amu": np.full(pressure.size, 2.33),
        "picaso_metadata": {
            "dry_run": True,
            "spectrum_source": "toy spectrum",
            "cloud_model": str(row.get("cloud_model", "none")),
            "wavelength_points": int(wavelength.size),
        },
    }


def _run_real_picaso_model(
    row: dict[str, Any],
    *,
    run_exact_climate_qc: bool = False,
    ck_root: str | Path | None = None,
) -> dict[str, Any]:
    if str(ROADRUNNER_ROOT) not in sys.path:
        sys.path.insert(0, str(ROADRUNNER_ROOT))

    from roadrunner.runner import (
        extract_planet_fluxes,
        run_picaso_climate_diagnostics_once,
        run_picaso_once,
    )
    from roadrunner.system import SystemParams

    output_grid = wavelength_grid_um()
    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    c_to_o = picaso_tag_to_cto(str(row["c_to_o_picaso_tag"]))
    metallicity_xsolar = float(row["metallicity_xsolar"])
    log_mh = math.log10(metallicity_xsolar)

    system = SystemParams(
        teff_k=float(row["picaso_tint_k"]),
        logg_cgs=math.log10(float(row["gravity_ms2"]) * 100.0),
        rj=float(row["planet_radius_rearth"]) * R_EARTH_TO_R_JUP,
        a_au=float(row["semi_major_au"]),
        phase_deg=float(row["phase_deg"]),
        tstar_k=float(row["star_teff_k"]),
        rstar_rsun=float(row["star_radius_rsun"]),
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        bond_albedo=0.0,
        chem_c_o=c_to_o,
        chem_log_mh=log_mh,
        kzz_cgs=float(row["kzz_cm2_s"]),
        virga_fsed=float(row["fsed"]),
    )

    out_ref, out_em, case, opacity = run_picaso_once(
        system,
        output_grid,
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        verbose=True,
        return_case=True,
        return_opacity=True,
    )
    albedo, fpfs_reflection = _reflected_observables(out_ref, system, output_grid)
    fpfs_emission = _thermal_fpfs(out_em, output_grid)

    result: dict[str, Any] = {
        "wavelength_um": output_grid,
        "fpfs_reflection": fpfs_reflection,
        "albedo": albedo,
        "picaso_out_reflected": out_ref,
        "picaso_out_emission": out_em,
        "picaso_case": case,
        "picaso_opacity": opacity,
        "picaso_metadata": {
            "dry_run": False,
            "atmosphere_source": "picaso",
            "thermal_source": "picaso",
            "cloud_model": cloud_model,
            "chem_log_mh": log_mh,
            "chem_c_o_from_picaso_tag": c_to_o,
            "c_to_o_picaso_tag": str(row["c_to_o_picaso_tag"]).zfill(3),
            "picaso_tint_k": float(row["picaso_tint_k"]),
        },
    }
    if fpfs_emission is not None:
        result["fpfs_emission"] = fpfs_emission
        denominator = fpfs_reflection + fpfs_emission
        result["reflected_fraction"] = np.divide(
            fpfs_reflection,
            denominator,
            out=np.zeros_like(fpfs_reflection),
            where=denominator > 0,
        )

    # Keep absolute planet fluxes available for later diagnostics without making
    # them the primary PICASO-style fpfs output variables.
    try:
        _, fp_reflected_abs, fp_thermal_abs = extract_planet_fluxes(out_ref, out_em, output_grid, system)
        result["picaso_metadata"]["has_absolute_flux_diagnostics"] = True
        result["absolute_flux_reflected"] = fp_reflected_abs
        result["absolute_flux_thermal"] = fp_thermal_abs
    except Exception as exc:
        result["picaso_metadata"]["absolute_flux_diagnostics_error"] = str(exc)

    if run_exact_climate_qc:
        try:
            result["qc_diagnostics"] = run_picaso_climate_diagnostics_once(
                system,
                output_grid,
                ck_root=ck_root,
                cloud_model=cloud_model,
                verbose=True,
            )
            result["picaso_metadata"]["has_exact_climate_qc"] = True
        except Exception as exc:
            result["qc_diagnostics"] = {"schema_warnings": [f"exact climate QC failed: {exc}"]}
            result["picaso_metadata"]["exact_climate_qc_error"] = str(exc)

    return result


def run_picaso_model(
    row: dict[str, Any],
    dry_run: bool = False,
    *,
    run_exact_climate_qc: bool = False,
    ck_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run one Aurora model row, or return a valid toy spectrum for plumbing tests."""
    if dry_run:
        return _dry_run_model(row)
    return _run_real_picaso_model(
        row,
        run_exact_climate_qc=run_exact_climate_qc,
        ck_root=ck_root,
    )
