from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .naming import picaso_tag_to_cto
from .parameters import ROADRUNNER_ROOT


LEGACY_WAVELENGTH_MIN_UM = 0.3
LEGACY_WAVELENGTH_MAX_UM = 2.5
LEGACY_WAVELENGTH_POINTS = 2201
PICASO_MAX_WAVELENGTH_MIN_UM = 0.3
PICASO_MAX_WAVELENGTH_MAX_UM = 15.0
PICASO_MAX_RESOLUTION = 15000.0
R_EARTH_TO_R_JUP = 0.0892141056
R_EARTH_AU = 4.263521245e-5


def _row_value(row: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    value = row.get(key, default)
    if value in (None, ""):
        return default
    return value


def _env_or_row(row: dict[str, Any] | None, key: str, env_name: str, default: Any = None) -> Any:
    env_value = os.environ.get(env_name)
    if env_value not in (None, ""):
        return env_value
    return _row_value(row, key, default)


def _constant_resolution_grid(min_um: float, max_um: float, resolution: float) -> np.ndarray:
    if min_um <= 0.0:
        raise ValueError(f"wavelength_min_um must be positive for constant-resolution grids; got {min_um!r}.")
    if max_um <= min_um:
        raise ValueError(f"wavelength_max_um must exceed wavelength_min_um; got {min_um!r}, {max_um!r}.")
    if resolution <= 0.0:
        raise ValueError(f"wavelength_resolution must be positive; got {resolution!r}.")
    n_points = int(math.ceil(math.log(max_um / min_um) * resolution)) + 1
    return np.geomspace(min_um, max_um, n_points)


def wavelength_grid_um(row: dict[str, Any] | None = None) -> np.ndarray:
    """Return the configured output wavelength grid in microns.

    The legacy fallback matches older Aurora manifests. New manifests can set
    ``wavelength_grid_mode=constant_resolution`` with ``wavelength_resolution``
    to use the PICASO resampled-opacity maximum grid.
    """
    mode = str(
        _env_or_row(row, "wavelength_grid_mode", "AURORA_WAVELENGTH_GRID_MODE", "uniform_wavelength")
    ).strip().lower()
    if mode in {"picaso_max", "picaso_resampled_max", "max"}:
        mode = "constant_resolution"
        default_min = PICASO_MAX_WAVELENGTH_MIN_UM
        default_max = PICASO_MAX_WAVELENGTH_MAX_UM
        default_resolution = PICASO_MAX_RESOLUTION
    else:
        default_min = LEGACY_WAVELENGTH_MIN_UM
        default_max = LEGACY_WAVELENGTH_MAX_UM
        default_resolution = PICASO_MAX_RESOLUTION

    min_um = float(_env_or_row(row, "wavelength_min_um", "AURORA_WAVELENGTH_MIN_UM", default_min))
    max_um = float(_env_or_row(row, "wavelength_max_um", "AURORA_WAVELENGTH_MAX_UM", default_max))
    if mode == "constant_resolution":
        resolution = float(
            _env_or_row(row, "wavelength_resolution", "AURORA_WAVELENGTH_RESOLUTION", default_resolution)
        )
        return _constant_resolution_grid(min_um, max_um, resolution)

    if mode in {"uniform_wavelength", "linear", "legacy"}:
        points = int(_env_or_row(row, "wavelength_points", "AURORA_WAVELENGTH_POINTS", LEGACY_WAVELENGTH_POINTS))
        if points < 2:
            raise ValueError(f"wavelength_points must be at least 2; got {points!r}.")
        if max_um <= min_um:
            raise ValueError(f"wavelength_max_um must exceed wavelength_min_um; got {min_um!r}, {max_um!r}.")
        return np.linspace(min_um, max_um, points)

    raise ValueError(
        f"Unsupported wavelength_grid_mode {mode!r}; choose 'uniform_wavelength', "
        "'constant_resolution', or 'picaso_max'."
    )


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


def _profile_value(profile: Any, key: str) -> np.ndarray | None:
    try:
        value = profile[key]
    except Exception:
        return None
    if hasattr(value, "values"):
        value = value.values
    try:
        return np.asarray(value, dtype=float)
    except Exception:
        return None


def _profile_columns(profile: Any) -> list[str]:
    if hasattr(profile, "columns"):
        return [str(column) for column in profile.columns]
    if isinstance(profile, dict):
        return [str(column) for column in profile]
    return []


def _climate_pt_profile(case: Any, climate_out: dict[str, Any]) -> dict[str, np.ndarray]:
    profile = case.inputs["atmosphere"]["profile"]
    pressure = np.asarray(climate_out["pressure"], dtype=float)
    temperature = np.asarray(climate_out["temperature"], dtype=float)
    pt_profile: dict[str, np.ndarray] = {
        "pressure": pressure,
        "temperature": temperature,
    }
    ignored = {"pressure", "temperature", "kz", "kzz", "e-", "lvl", "wv", "sigma"}
    for column in _profile_columns(profile):
        if column.strip().lower() in ignored:
            continue
        values = _profile_value(profile, column)
        if values is not None and values.ndim == 1 and values.size == pressure.size:
            pt_profile[column] = values
    return pt_profile


def _as_bool_scalar(value: Any) -> bool:
    try:
        array = np.asarray(value)
        if array.shape == ():
            return bool(array.item())
    except Exception:
        pass
    return bool(value)


def _dry_run_model(row: dict[str, Any]) -> dict[str, Any]:
    wavelength = wavelength_grid_um(row)
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
            "virga_condensates": str(row.get("virga_condensates", "")),
            "wavelength_points": int(wavelength.size),
        },
    }


def _run_real_picaso_climate_model(
    row: dict[str, Any],
    *,
    system: Any,
    output_grid: np.ndarray,
    cloud_model: str,
    ck_root: str | Path | None,
    run_picaso_climate_model_once: Any,
    extract_planet_fluxes: Any,
) -> dict[str, Any]:
    out_ref, out_em, climate_out, qc_diagnostics, case, opacity = run_picaso_climate_model_once(
        system,
        output_grid,
        ck_root=ck_root,
        cloud_model=cloud_model,
        verbose=True,
        return_case=True,
        return_opacity=True,
    )
    albedo, fpfs_reflection = _reflected_observables(out_ref, system, output_grid)
    fpfs_emission = _thermal_fpfs(out_em, output_grid)
    pt_profile = _climate_pt_profile(case, climate_out)

    result: dict[str, Any] = {
        "wavelength_um": output_grid,
        "fpfs_reflection": fpfs_reflection,
        "albedo": albedo,
        "pt_profile": pt_profile,
        "picaso_out_reflected": out_ref,
        "picaso_out_emission": out_em,
        "picaso_climate_out": climate_out,
        "picaso_case": case,
        "picaso_opacity": opacity,
        "qc_diagnostics": qc_diagnostics,
        "picaso_metadata": {
            "dry_run": False,
            "atmosphere_source": "picaso_climate",
            "thermal_source": "picaso_climate_spectrum_output",
            "cloud_model": cloud_model,
            "cloud_fraction": system.cloud_fraction,
            "cloud_hole_fraction": system.cloud_hole_fraction,
            "virga_condensates": system.virga_condensates,
            "native_patchy_cloud_api": "virga(do_holes=True, fhole=cloud_hole_fraction)",
            "chem_log_mh": system.chem_log_mh,
            "chem_c_o_from_picaso_tag": system.chem_c_o,
            "c_to_o_picaso_tag": str(row["c_to_o_picaso_tag"]).zfill(3),
            "picaso_tint_k": float(row["picaso_tint_k"]),
            "climate_converged": _as_bool_scalar(qc_diagnostics.get("climate_converged", False)),
            "climate_opacity_method": "preweighted",
            "selected_ck_file": str(qc_diagnostics.get("selected_ck_file", "")),
            "has_exact_climate_qc": True,
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

    try:
        _, fp_reflected_abs, fp_thermal_abs = extract_planet_fluxes(out_ref, out_em, output_grid, system)
        result["picaso_metadata"]["has_absolute_flux_diagnostics"] = True
        result["absolute_flux_reflected"] = fp_reflected_abs
        result["absolute_flux_thermal"] = fp_thermal_abs
    except Exception as exc:
        result["picaso_metadata"]["absolute_flux_diagnostics_error"] = str(exc)
        result["absolute_flux_reflected"] = np.zeros(output_grid.size, dtype=float)
        result["absolute_flux_thermal"] = np.zeros(output_grid.size, dtype=float)

    return result


def _run_real_picaso_model(
    row: dict[str, Any],
    *,
    run_exact_climate_qc: bool = False,
    ck_root: str | Path | None = None,
    atmosphere_source: str = "picaso_guillot",
) -> dict[str, Any]:
    if str(ROADRUNNER_ROOT) not in sys.path:
        sys.path.insert(0, str(ROADRUNNER_ROOT))

    from roadrunner.runner import (
        extract_planet_fluxes,
        normalize_atmosphere_source,
        run_picaso_climate_model_once,
        run_picaso_climate_diagnostics_once,
        run_picaso_once,
    )
    from roadrunner.system import SystemParams

    output_grid = wavelength_grid_um(row)
    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    c_to_o = picaso_tag_to_cto(str(row["c_to_o_picaso_tag"]))
    metallicity_xsolar = float(row["metallicity_xsolar"])
    log_mh = math.log10(metallicity_xsolar)

    source = normalize_atmosphere_source(atmosphere_source)
    cloud_fraction = float(row.get("cloud_fraction", 1.0))
    cloud_hole_fraction = float(row.get("cloud_hole_fraction", 1.0 - cloud_fraction))
    virga_condensates = str(row.get("virga_condensates") or "").strip()
    if not virga_condensates:
        from roadrunner.config import PICASO_VIRGA_CONDENSATES
        virga_condensates = PICASO_VIRGA_CONDENSATES
    system = SystemParams(
        teff_k=float(row["picaso_tint_k"]),
        logg_cgs=math.log10(float(row["gravity_ms2"]) * 100.0),
        rj=float(row["planet_radius_rearth"]) * R_EARTH_TO_R_JUP,
        a_au=float(row["semi_major_au"]),
        phase_deg=float(row["phase_deg"]),
        tstar_k=float(row["star_teff_k"]),
        rstar_rsun=float(row["star_radius_rsun"]),
        atmosphere_source=source,
        cloud_model=cloud_model,
        cloud_fraction=cloud_fraction,
        cloud_hole_fraction=cloud_hole_fraction,
        bond_albedo=0.0,
        chem_c_o=c_to_o,
        chem_log_mh=log_mh,
        kzz_cgs=float(row["kzz_cm2_s"]),
        virga_fsed=float(row["fsed"]),
        virga_condensates=virga_condensates,
    )

    if source == "picaso_climate":
        return _run_real_picaso_climate_model(
            row,
            system=system,
            output_grid=output_grid,
            cloud_model=cloud_model,
            ck_root=ck_root,
            run_picaso_climate_model_once=run_picaso_climate_model_once,
            extract_planet_fluxes=extract_planet_fluxes,
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
            "virga_condensates": system.virga_condensates,
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


def _system_from_row(row: dict[str, Any], *, atmosphere_source: str = "picaso_climate") -> Any:
    from roadrunner.runner import normalize_atmosphere_source
    from roadrunner.system import SystemParams

    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    c_to_o = picaso_tag_to_cto(str(row["c_to_o_picaso_tag"]))
    metallicity_xsolar = float(row["metallicity_xsolar"])
    log_mh = math.log10(metallicity_xsolar)
    cloud_fraction = float(row.get("cloud_fraction", 1.0))
    cloud_hole_fraction = float(row.get("cloud_hole_fraction", 1.0 - cloud_fraction))
    virga_condensates = str(row.get("virga_condensates") or "").strip()
    if not virga_condensates:
        from roadrunner.config import PICASO_VIRGA_CONDENSATES

        virga_condensates = PICASO_VIRGA_CONDENSATES
    source = normalize_atmosphere_source(atmosphere_source)
    return SystemParams(
        teff_k=float(row["picaso_tint_k"]),
        logg_cgs=math.log10(float(row["gravity_ms2"]) * 100.0),
        rj=float(row["planet_radius_rearth"]) * R_EARTH_TO_R_JUP,
        a_au=float(row["semi_major_au"]),
        phase_deg=float(row["phase_deg"]),
        tstar_k=float(row["star_teff_k"]),
        rstar_rsun=float(row["star_radius_rsun"]),
        atmosphere_source=source,
        cloud_model=cloud_model,
        cloud_fraction=cloud_fraction,
        cloud_hole_fraction=cloud_hole_fraction,
        bond_albedo=0.0,
        chem_c_o=c_to_o,
        chem_log_mh=log_mh,
        kzz_cgs=float(row["kzz_cm2_s"]),
        virga_fsed=float(row["fsed"]),
        virga_condensates=virga_condensates,
    )


def run_picaso_model_from_climate_cache(
    row: dict[str, Any],
    climate_cache: dict[str, Any],
    *,
    ck_root: str | Path | None = None,
) -> dict[str, Any]:
    """Spectrum-only PICASO run using a pre-converged climate PT profile."""
    if str(ROADRUNNER_ROOT) not in sys.path:
        sys.path.insert(0, str(ROADRUNNER_ROOT))

    from roadrunner.runner import (
        extract_planet_fluxes,
        run_picaso_reflected_spectrum_from_climate_profile,
        run_picaso_reflected_spectrum_from_converged_case,
    )

    output_grid = wavelength_grid_um(row)
    system = _system_from_row(row)
    cloud_model = str(row.get("cloud_model") or ("none" if float(row["cloud_fraction"]) == 0.0 else "virga"))
    cache_meta = climate_cache.get("metadata", {})
    diagnostics = cache_meta.get("diagnostics", {})

    if climate_cache.get("cl_run") is not None:
        out_ref = run_picaso_reflected_spectrum_from_converged_case(
            climate_cache["cl_run"],
            system,
            output_grid,
            climate_cache["selected_ck_file"],
        )
    else:
        out_ref = run_picaso_reflected_spectrum_from_climate_profile(
            system,
            output_grid,
            climate_cache["pressure"],
            climate_cache["temperature"],
            ck_root=ck_root,
            selected_ck_file=climate_cache["selected_ck_file"],
            cloud_model=cloud_model,
            verbose=False,
        )
    albedo, fpfs_reflection = _reflected_observables(out_ref, system, output_grid)
    pressure = np.asarray(climate_cache["pressure"], dtype=float)
    temperature = np.asarray(climate_cache["temperature"], dtype=float)
    climate_out_dict = {"pressure": pressure, "temperature": temperature}
    if climate_cache.get("cl_run") is not None:
        pt_profile = _climate_pt_profile(climate_cache["cl_run"], climate_out_dict)
    else:
        pt_profile = {"pressure": pressure, "temperature": temperature}

    result: dict[str, Any] = {
        "wavelength_um": output_grid,
        "fpfs_reflection": fpfs_reflection,
        "albedo": albedo,
        "pt_profile": pt_profile,
        "picaso_out_reflected": out_ref,
        "picaso_metadata": {
            "dry_run": False,
            "atmosphere_source": "picaso_climate_cached",
            "thermal_source": "skipped_spectrum_stage",
            "cloud_model": cloud_model,
            "virga_condensates": system.virga_condensates,
            "climate_group_index": int(row.get("climate_group_index", -1)),
            "climate_cache_stage": True,
            "climate_converged": _as_bool_scalar(diagnostics.get("climate_converged", False)),
            "selected_ck_file": str(climate_cache["selected_ck_file"]),
            "cahoy_reference_name": row.get("cahoy_reference_name", ""),
        },
        "qc_diagnostics": diagnostics,
    }
    if climate_cache.get("cl_run") is not None:
        result["picaso_case"] = climate_cache["cl_run"]
    try:
        _, fp_reflected_abs, fp_thermal_abs = extract_planet_fluxes(out_ref, {}, output_grid, system)
        result["picaso_metadata"]["has_absolute_flux_diagnostics"] = True
        result["absolute_flux_reflected"] = fp_reflected_abs
        result["absolute_flux_thermal"] = fp_thermal_abs
    except Exception as exc:
        result["picaso_metadata"]["absolute_flux_diagnostics_error"] = str(exc)
        result["absolute_flux_reflected"] = np.zeros(output_grid.size, dtype=float)
        result["absolute_flux_thermal"] = np.zeros(output_grid.size, dtype=float)
    return result


def run_picaso_model(
    row: dict[str, Any],
    dry_run: bool = False,
    *,
    run_exact_climate_qc: bool = False,
    ck_root: str | Path | None = None,
    atmosphere_source: str | None = None,
) -> dict[str, Any]:
    """Run one Aurora model row, or return a valid toy spectrum for plumbing tests."""
    if dry_run:
        return _dry_run_model(row)
    selected_source = str(atmosphere_source or row.get("atmosphere_source") or "picaso_guillot")
    return _run_real_picaso_model(
        row,
        run_exact_climate_qc=run_exact_climate_qc,
        ck_root=ck_root,
        atmosphere_source=selected_source,
    )
