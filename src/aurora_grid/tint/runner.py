from __future__ import annotations

import math
import os
import time
from functools import wraps
from pathlib import Path
from typing import Any

import numpy as np

from .config import REQUIRED_SPECIES, wavelength_grid


def _install_quench_domain_extension(climate_module: Any | None = None) -> dict[str, Any]:
    """Retry PICASO quench-level searches on its standard deep extension.

    PICASO 4 extends profiles to 1e6 bar for this purpose when their minimum
    temperature is <=250 K.  Irradiated profiles can require the same extension,
    but the installed implementation raises before applying it.  This wrapper
    preserves PICASO's quench calculation and its own 10-level extrapolation;
    only the domain supplied to the retry is enlarged.  PICASO subsequently
    extends equilibrium chemistry to the returned quench level and drops the
    temporary levels in ``adjust_quench_chemistry``.
    """
    if climate_module is None:
        import picaso.climate as climate
    else:
        climate = climate_module

    original = climate.get_quench_levels
    tracker: dict[str, Any] = {
        "applied": False,
        "retry_count": 0,
        "maximum_pressure_bar": None,
        "levels": {},
        "pressures_bar": {},
    }

    def record(result: Any, atmosphere: Any) -> Any:
        levels = dict(result[0])
        pressure = np.asarray(atmosphere.p_level, dtype=float)
        maximum_level = max((int(level) for level in levels.values()), default=-1)
        if maximum_level >= pressure.size:
            temperature = np.asarray(atmosphere.t_level, dtype=float)
            if float(np.min(temperature)) <= 250.0 and pressure[-1] < 1.0e6:
                pressure = np.append(
                    pressure,
                    np.logspace(np.log10(pressure[-1] + 100.0), 6.0, 10),
                )
            if maximum_level >= pressure.size:
                raise RuntimeError(
                    f"PICASO quench index {maximum_level} cannot be mapped onto {pressure.size} pressure levels"
                )
        tracker["levels"] = {str(name): int(level) for name, level in levels.items()}
        tracker["pressures_bar"] = {
            str(name): float(pressure[int(level)])
            for name, level in levels.items()
        }
        return result

    @wraps(original)
    def with_deep_retry(atmosphere: Any, kz: Any, grav: float, mh_linear: float, **kwargs: Any):
        try:
            return record(
                original(atmosphere, kz, grav, mh_linear, **kwargs),
                atmosphere,
            )
        except Exception as exc:
            if "Start with deeper Pressure Grid" not in str(exc):
                raise
            pressure = np.asarray(atmosphere.p_level, dtype=float)
            temperature = np.asarray(atmosphere.t_level, dtype=float)
            if pressure[-1] >= 1.0e6 or not hasattr(atmosphere, "_replace"):
                raise

            # Match the temporary extension in picaso.deq_chem.get_quench_levels.
            extended_pressure = np.logspace(np.log10(pressure[-1] + 100.0), 6.0, 10)
            extended_temperature = temperature.copy()
            deep_gradient = float(np.asarray(atmosphere.dtdp, dtype=float)[-1])
            previous_pressure = pressure[-1]
            for next_pressure in extended_pressure:
                next_temperature = np.exp(
                    np.log(extended_temperature[-1])
                    + deep_gradient * (np.log(next_pressure) - np.log(previous_pressure))
                )
                extended_temperature = np.append(extended_temperature, next_temperature)
                previous_pressure = next_pressure

            retry_atmosphere = atmosphere._replace(
                t_level=extended_temperature,
                p_level=np.append(pressure, extended_pressure),
                nlevel=extended_temperature.size,
            )
            tracker["applied"] = True
            tracker["retry_count"] += 1
            tracker["maximum_pressure_bar"] = float(extended_pressure[-1])
            return record(
                original(retry_atmosphere, kz, grav, mh_linear, **kwargs),
                retry_atmosphere,
            )

    climate.get_quench_levels = with_deep_retry
    return tracker


def _install_virga_minimum_particle_guard(virga_module: Any | None = None) -> dict[str, int]:
    """Clamp unresolved Virga fall-speed roots to its 0.1-nm radius floor.

    Virga 2 refuses to search below 1e-8 cm because such particles would be
    smaller than gas atoms.  At very low settling speeds both Brent endpoints
    can therefore be positive.  Returning zero exactly at that documented
    lower endpoint makes Brent select the physical floor, without changing the
    required Kzz or any fall-speed calculation above the floor.
    """
    if virga_module is None:
        import virga.justdoit as virga_jdi
    else:
        virga_jdi = virga_module

    existing = getattr(virga_jdi.vfall_find_root, "_aurora_minimum_particle_tracker", None)
    if existing is not None:
        return existing

    original = virga_jdi.vfall_find_root
    tracker = {"clamp_count": 0}

    @wraps(original)
    def bounded_at_atomic_scale(radius: float, *args: Any, **kwargs: Any) -> float:
        residual = float(original(radius, *args, **kwargs))
        if float(radius) <= 1.0e-8 and np.isfinite(residual) and residual > 0.0:
            tracker["clamp_count"] += 1
            return 0.0
        return residual

    setattr(bounded_at_atomic_scale, "_aurora_minimum_particle_tracker", tracker)
    virga_jdi.vfall_find_root = bounded_at_atomic_scale
    return tracker


def _install_zero_cloud_convergence_guard(climate_module: Any | None = None) -> dict[str, int]:
    """Make PICASO's exact-zero cloud-change criterion satisfiable.

    PICASO tests ``taudif < taudif_tol``. For a genuinely zero-opacity cloud
    deck both values are exactly zero, so an otherwise stationary P-T profile
    can never be marked converged. Replacing only that zero tolerance with the
    smallest positive float preserves the criterion and makes ``0 < tol`` true.
    """
    if climate_module is None:
        import picaso.climate as climate
    else:
        climate = climate_module
    existing = getattr(climate.update_clouds, "_aurora_zero_cloud_tracker", None)
    if existing is not None:
        return existing
    original = climate.update_clouds
    tracker = {"adjustment_count": 0}

    @wraps(original)
    def guarded(*args: Any, **kwargs: Any):
        result = list(original(*args, **kwargs))
        taudif = float(result[2])
        tolerance = float(result[3])
        if taudif == 0.0 and tolerance == 0.0:
            result[3] = float(np.nextafter(0.0, 1.0))
            tracker["adjustment_count"] += 1
        return tuple(result)

    guarded._aurora_zero_cloud_tracker = tracker  # type: ignore[attr-defined]
    climate.update_clouds = guarded
    return tracker


def _opacity_file(row: dict[str, Any]) -> Path:
    log_mh = math.log10(float(row["metallicity_xsolar"]))
    filename = f"sonora_2121grid_feh{log_mh:.1f}_co{float(row['c_to_o_absolute']):.2f}.hdf5"
    path = Path(row["opacity_directory"]) / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required preweighted PICASO opacity file is missing: {path}")
    return path


def _interpolate_output(
    output: dict[str, Any],
    key: str,
    target_wave: np.ndarray,
    diagnostics: dict[str, int],
) -> np.ndarray:
    native_wave = 1.0e4 / np.asarray(output["wavenumber"], dtype=float)
    values = output.get(key)
    if not isinstance(values, np.ndarray):
        raise RuntimeError(f"PICASO output {key!r} is unavailable: {values!r}")
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(native_wave) & np.isfinite(values)
    diagnostics[f"{key}_native_samples"] = int(values.size)
    diagnostics[f"{key}_nonfinite_samples_removed"] = int(values.size - np.count_nonzero(finite))
    if np.count_nonzero(finite) < 2:
        raise RuntimeError(
            f"PICASO output {key!r} has fewer than two finite native samples "
            f"({np.count_nonzero(finite)}/{values.size})"
        )
    native_wave = native_wave[finite]
    values = values[finite]
    order = np.argsort(native_wave)
    result = np.interp(target_wave, native_wave[order], values[order])
    if not np.all(np.isfinite(result)):
        raise RuntimeError(f"Interpolated PICASO output {key!r} contains non-finite values")
    return result


def _profile_column(profile: Any, name: str) -> np.ndarray:
    if name not in profile:
        raise RuntimeError(f"Final PICASO atmosphere is missing required column {name!r}")
    values = profile[name]
    if hasattr(values, "values"):
        values = values.values
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise RuntimeError(f"Final PICASO atmosphere column {name!r} is invalid")
    return values


def _equilibrium_comparison(
    jdi: Any, profile: Any, row: dict[str, Any]
) -> tuple[np.ndarray, bool, float]:
    equilibrium = jdi.inputs()
    equilibrium.add_pt(
        _profile_column(profile, "temperature"),
        _profile_column(profile, "pressure"),
    )
    equilibrium.chemeq_visscher_2121(
        cto_absolute=float(row["c_to_o_absolute"]),
        log_mh=math.log10(float(row["metallicity_xsolar"])),
    )
    eq_profile = equilibrium.inputs["atmosphere"]["profile"]
    equilibrium_abundances = []
    largest = 0.0
    for species in REQUIRED_SPECIES:
        final = np.maximum(_profile_column(profile, species), 1.0e-300)
        eq = np.maximum(_profile_column(eq_profile, species), 1.0e-300)
        equilibrium_abundances.append(eq)
        largest = max(largest, float(np.max(np.abs(np.log10(final) - np.log10(eq)))))
    return np.column_stack(equilibrium_abundances), largest > 1.0e-6, largest


def _correct_thermal_flux_ratio(
    output: dict[str, Any], row: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, float | int]]:
    """Put the climate thermal planet/star ratio on a dimensionless basis.

    PICASO's climate stellar path stores its stellar denominator integrated
    over each native wavelength bin, while ``thermal`` remains a flux density
    per cm. Multiplying PICASO's raw ratio by the corresponding wavelength-bin
    width converts that denominator back to a mean stellar flux density.
    """
    wavenumber = np.asarray(output["wavenumber"], dtype=float)
    raw_ratio = np.asarray(output["fpfs_thermal"], dtype=float)
    planet_flux_density = np.asarray(output["thermal"], dtype=float)
    try:
        stellar_bin_integral = np.asarray(output["full_output"]["star"]["flux"], dtype=float)
    except (KeyError, TypeError) as exc:
        raise RuntimeError("PICASO thermal output omitted the native stellar bin integrals") from exc
    if (
        wavenumber.ndim != 1
        or raw_ratio.shape != wavenumber.shape
        or planet_flux_density.shape != wavenumber.shape
        or stellar_bin_integral.shape != wavenumber.shape
        or wavenumber.size < 2
    ):
        raise RuntimeError("PICASO thermal output has incompatible native arrays")
    wavelength_cm = 1.0 / wavenumber
    bin_width_cm = np.empty_like(wavelength_cm)
    bin_width_cm[:-1] = np.abs(np.diff(wavelength_cm))
    bin_width_cm[-1] = bin_width_cm[-2]
    if not np.all(np.isfinite(bin_width_cm)) or np.any(bin_width_cm <= 0.0):
        raise RuntimeError("Cannot recover positive finite stellar wavelength-bin widths")
    stellar_flux_density = stellar_bin_integral / bin_width_cm
    positive_stellar = np.isfinite(stellar_flux_density) & (stellar_flux_density > 0.0)
    repaired_stellar_bins = int(np.sum(~positive_stellar))
    if np.sum(positive_stellar) < 2:
        raise RuntimeError("Too few positive stellar bins to recover a stellar flux density")
    if repaired_stellar_bins:
        positive_order = np.argsort(wavenumber[positive_stellar])
        stellar_flux_density[~positive_stellar] = 10.0 ** np.interp(
            np.log10(wavenumber[~positive_stellar]),
            np.log10(wavenumber[positive_stellar][positive_order]),
            np.log10(stellar_flux_density[positive_stellar][positive_order]),
        )
    planet_tolerance = max(float(np.max(np.abs(planet_flux_density))) * 1.0e-12, 1.0e-300)
    if float(np.min(planet_flux_density)) < -planet_tolerance:
        raise RuntimeError(
            "Planet thermal flux density contains materially negative samples: "
            f"minimum={float(np.min(planet_flux_density)):.6g}, tolerance={planet_tolerance:.6g}"
        )
    clipped_planet_bins = int(np.sum(planet_flux_density < 0.0))
    planet_flux_density = np.maximum(planet_flux_density, 0.0)
    earth_radius_cm = 6.3781e8
    solar_radius_cm = 6.957e10
    radius_ratio_squared = (
        float(row["planet_radius_rearth"]) * earth_radius_cm
        / (float(row["star_radius_rsun"]) * solar_radius_cm)
    ) ** 2
    corrected = planet_flux_density / stellar_flux_density * radius_ratio_squared
    if not np.all(np.isfinite(corrected)) or np.any(corrected < 0.0):
        raise RuntimeError("Corrected thermal planet/star flux ratio is invalid")
    result = dict(output)
    result["fpfs_thermal"] = corrected
    diagnostics = {
        "minimum_native_bin_width_cm": float(np.min(bin_width_cm)),
        "maximum_native_bin_width_cm": float(np.max(bin_width_cm)),
        "maximum_raw_ratio": float(np.max(raw_ratio)),
        "maximum_corrected_ratio": float(np.max(corrected)),
        "repaired_nonpositive_stellar_bins": repaired_stellar_bins,
        "clipped_roundoff_planet_bins": clipped_planet_bins,
        "planet_star_radius_ratio_squared": radius_ratio_squared,
    }
    return result, diagnostics


def _assert_required_runtime(row: dict[str, Any]) -> None:
    if os.environ.get("picaso_refdata") != row["reference_data"]:
        raise RuntimeError(
            "picaso_refdata must point to the manifest reference_data directory before PICASO import; "
            f"expected {row['reference_data']!r}, got {os.environ.get('picaso_refdata')!r}"
        )
    if not Path(row["virga_directory"]).is_dir():
        raise FileNotFoundError(f"Virga directory is missing: {row['virga_directory']}")
    for condensate in row["virga_condensates"]:
        path = Path(row["virga_directory"]) / f"{condensate}.mieff"
        if not path.is_file():
            raise FileNotFoundError(f"Virga condensate optical data are missing: {path}")
    chemistry_mode = row.get("chemistry_mode", "disequilibrium_quench")
    required = {
        "disequilibrium_quench": (True, False, True),
        "equilibrium_only": (False, False, False),
    }
    if chemistry_mode not in required:
        raise ValueError(f"Unsupported chemistry mode {chemistry_mode!r}")
    actual = (row["diseq_chem"], row["self_consistent_kzz"], row["quench"])
    if actual != required[chemistry_mode]:
        raise ValueError(
            f"Chemistry controls {actual!r} do not match mode {chemistry_mode!r}: "
            f"expected {required[chemistry_mode]!r}"
        )


def run_model(row: dict[str, Any], *, verbose: bool = True) -> dict[str, Any]:
    """Run one full climate + transmission + thermal + phase-0 reflected model."""
    _assert_required_runtime(row)
    started = time.monotonic()

    from astropy import units as u
    import picaso.justdoit as jdi

    target_wave = wavelength_grid(row)
    selected_opacity = _opacity_file(row)
    opacity = jdi.opannection(
        ck_db=str(selected_opacity),
        wave_range=[float(target_wave[0]), float(target_wave[-1])],
        method="preweighted",
    )
    case = jdi.inputs(calculation="planet", climate=True)
    case.gravity(
        # PICASO only stores radius when both mass and radius are supplied. Its
        # gravity-only branch silently discards a simultaneous radius argument.
        mass=float(row["planet_mass_mearth"]),
        mass_unit=u.M_earth,
        radius=float(row["planet_radius_rearth"]),
        radius_unit=u.R_earth,
    )
    # Preserve the explicitly specified coupled-case gravity rather than the
    # slightly different value recomputed from rounded observed M and R.
    case.inputs["planet"]["gravity"] = float(row["gravity_ms2"]) * 100.0
    case.inputs["planet"]["gravity_unit"] = "cm/(s**2)"
    case.star(
        opacity,
        temp=float(row["star_teff_k"]),
        metal=0.0,
        logg=4.44,
        radius=float(row["star_radius_rsun"]),
        radius_unit=u.R_sun,
        semi_major=float(row["semi_major_axis_au"]),
        semi_major_unit=u.AU,
    )
    case.guillot_pt(
        Teq=float(row["equilibrium_temperature_k"]),
        T_int=float(row["tint_k"]),
        nlevel=int(row["pressure_levels"]),
        p_top=math.log10(float(row["pressure_top_bar"])),
        p_bottom=math.log10(float(row["pressure_bottom_bar"])),
    )

    # Explicit equilibrium initialization from the requested PICASO 2121 tables.
    profile = case.inputs["atmosphere"]["profile"]
    profile["kz"] = float(row["kzz_cm2_s"])
    case.chemeq_visscher_2121(
        cto_absolute=float(row["c_to_o_absolute"]),
        log_mh=math.log10(float(row["metallicity_xsolar"])),
    )
    chemistry_mode = str(row.get("chemistry_mode", "disequilibrium_quench"))
    # Register the same Visscher chemistry with the climate handler. Sensitivity
    # 1 uses PICASO's quench approximation; Sensitivity 2.0 deliberately follows
    # the v1 equilibrium-only path and leaves the quench flag disabled.
    if chemistry_mode == "disequilibrium_quench":
        case.atmosphere(
            df=case.inputs["atmosphere"]["profile"].copy(),
            mh=float(row["metallicity_xsolar"]),
            cto_absolute=float(row["c_to_o_absolute"]),
            chem_method="visscher",
            quench=True,
        )
    else:
        case.atmosphere(
            df=case.inputs["atmosphere"]["profile"].copy(),
            mh=float(row["metallicity_xsolar"]),
            cto_absolute=float(row["c_to_o_absolute"]),
            chem_method="visscher",
            quench=False,
        )
    case.inputs["atmosphere"]["profile"]["kz"] = float(row["kzz_cm2_s"])

    virga_particle_guard = {"clamp_count": 0}
    if row["cloud_model"] == "virga":
        # PICASO's bundled Virga 2.0.1 needs this guard for bottom-adjacent decks.
        try:
            from roadrunner.runner import _patch_virga_calc_optics_sublayer_guard

            if not _patch_virga_calc_optics_sublayer_guard(verbose=verbose):
                raise RuntimeError("Virga bottom-layer safety guard could not be applied")
            virga_particle_guard = _install_virga_minimum_particle_guard()
        except ImportError as exc:
            raise RuntimeError("Aurora RoadRunner Virga compatibility helper is unavailable") from exc
        case.virga(
            condensates=list(row["virga_condensates"]),
            directory=row["virga_directory"],
            fsed=float(row["fsed"]),
            param="const",
            mh=float(row["metallicity_xsolar"]),
            kz_min=float(row["kzz_cm2_s"]),
            do_holes=False,
        )
    elif row["cloud_model"] != "none":
        raise ValueError(f"Unsupported cloud model {row['cloud_model']!r}")

    if hasattr(case, "effective_temp"):
        case.effective_temp(float(row["tint_k"]))
    else:
        case.T_eff(float(row["tint_k"]))
    profile = case.inputs["atmosphere"]["profile"]
    pressure_guess = _profile_column(profile, "pressure")
    temperature_guess = _profile_column(profile, "temperature")
    rcb_guess = max(1, pressure_guess.size - 7)
    case.inputs_climate(
        temp_guess=temperature_guess,
        pressure=pressure_guess,
        rfaci=1.0,
        rcb_guess=rcb_guess,
        rfacv=float(row["redistribution_factor"]),
        moistgrad=False,
    )
    # inputs_climate preserves kz, but assert and reset explicitly before the required call.
    case.inputs["atmosphere"]["profile"]["kz"] = float(row["kzz_cm2_s"])
    if chemistry_mode == "disequilibrium_quench":
        quench_extension = _install_quench_domain_extension()
    else:
        quench_extension = {
            "applied": False,
            "retry_count": 0,
            "maximum_pressure_bar": None,
            "levels": {},
            "pressures_bar": {},
        }
    zero_cloud_convergence_guard = (
        _install_zero_cloud_convergence_guard()
        if row["cloud_model"] == "virga" else {"adjustment_count": 0}
    )
    if chemistry_mode == "disequilibrium_quench":
        climate_out = case.climate(
            opacity,
            save_all_profiles=False,
            with_spec=True,
            diseq_chem=True,
            self_consistent_kzz=False,
            verbose=verbose,
        )
    else:
        climate_out = case.climate(
            opacity,
            save_all_profiles=False,
            with_spec=True,
            diseq_chem=False,
            self_consistent_kzz=False,
            verbose=verbose,
        )
    if not isinstance(climate_out, dict):
        raise RuntimeError(f"PICASO climate returned {type(climate_out).__name__}, not dict")
    climate_retry_count = 0
    while (
        not bool(np.asarray(climate_out.get("converged", False)).item())
        and climate_retry_count < int(row["climate_retry_attempts"])
    ):
        retry_profile = climate_out.get("ptchem_df")
        if retry_profile is None:
            break
        retry_pressure = _profile_column(retry_profile, "pressure")
        retry_temperature = _profile_column(retry_profile, "temperature")
        case.inputs_climate(
            temp_guess=retry_temperature,
            pressure=retry_pressure,
            rfaci=1.0,
            rcb_guess=max(1, retry_pressure.size - 7),
            rfacv=float(row["redistribution_factor"]),
            moistgrad=False,
        )
        case.inputs["atmosphere"]["profile"]["kz"] = float(row["kzz_cm2_s"])
        climate_retry_count += 1
        if chemistry_mode == "disequilibrium_quench":
            climate_out = case.climate(
                opacity,
                save_all_profiles=False,
                with_spec=True,
                diseq_chem=True,
                self_consistent_kzz=False,
                verbose=verbose,
            )
        else:
            climate_out = case.climate(
                opacity,
                save_all_profiles=False,
                with_spec=True,
                diseq_chem=False,
                self_consistent_kzz=False,
                verbose=verbose,
            )
        if not isinstance(climate_out, dict):
            raise RuntimeError(f"PICASO climate retry returned {type(climate_out).__name__}, not dict")
    final_profile = climate_out.get("ptchem_df")
    if final_profile is None:
        raise RuntimeError("PICASO climate did not return final ptchem_df")
    pressure = _profile_column(final_profile, "pressure")
    temperature = _profile_column(final_profile, "temperature")
    abundances = np.column_stack([_profile_column(final_profile, name) for name in REQUIRED_SPECIES])
    # PICASO's climate return drops kz from ptchem_df. Under disequilibrium it
    # must remain the chemistry Kzz; under equilibrium-only it is intentionally
    # not a chemistry input and is retained solely as the Virga mixing profile.
    if chemistry_mode == "disequilibrium_quench":
        internal_kz = np.asarray(
            case.inputs["atmosphere"]["kzz"].get("constant_kzz"), dtype=float
        )
        if internal_kz.shape != pressure.shape or not np.all(
            internal_kz == float(row["kzz_cm2_s"])
        ):
            raise RuntimeError("PICASO internal chemistry Kzz is not the required constant 1e10 cm2/s")
    final_kz = np.full(pressure.shape, float(row["kzz_cm2_s"]), dtype=float)
    final_profile["kz"] = final_kz
    case.inputs["atmosphere"]["profile"]["kz"] = final_kz
    retained_quench = bool(case.inputs["approx"]["chem_params"].get("quench", False))
    if retained_quench is not bool(row["quench"]):
        raise RuntimeError(
            f"PICASO atmosphere quench flag is {retained_quench}, expected {bool(row['quench'])}"
        )

    equilibrium_abundances, final_differs_from_equilibrium, max_log_difference = _equilibrium_comparison(
        jdi, final_profile, row
    )
    equilibrium_consistency_tolerance_dex = float(
        row.get("equilibrium_consistency_tolerance_dex", 1.0e-2)
    )
    if (
        chemistry_mode == "equilibrium_only"
        and max_log_difference > equilibrium_consistency_tolerance_dex
    ):
        raise RuntimeError(
            "Equilibrium-only climate returned abundances inconsistent with Visscher 2121 "
            f"on the final P-T profile (max difference {max_log_difference:.6g} dex; "
            f"tolerance {equilibrium_consistency_tolerance_dex:.6g} dex)"
        )
    thermal_out = climate_out.get("spectrum_output")
    if not isinstance(thermal_out, dict):
        thermal_out = case.spectrum(opacity, calculation="thermal", as_dict=True, full_output=True)
    thermal_out, thermal_correction = _correct_thermal_flux_ratio(thermal_out, row)
    transmission_out = case.spectrum(opacity, calculation="transmission", as_dict=True, full_output=True)
    case.phase_angle(0.0, num_gangle=4, num_tangle=4)
    reflected_out = case.spectrum(opacity, calculation="reflected", as_dict=True, full_output=True)

    interpolation_diagnostics: dict[str, int] = {}
    result = {
        "wavelength_um": target_wave,
        "pressure_bar": pressure,
        "temperature_k": temperature,
        "kzz_cm2_s_profile": final_kz,
        "mole_fraction": abundances,
        "equilibrium_mole_fraction": equilibrium_abundances,
        "transmission_depth": _interpolate_output(
            transmission_out, "transit_depth", target_wave, interpolation_diagnostics
        ),
        "thermal_planet_star_flux_ratio": _interpolate_output(
            thermal_out, "fpfs_thermal", target_wave, interpolation_diagnostics
        ),
        "reflected_planet_star_flux_ratio": _interpolate_output(
            reflected_out, "fpfs_reflected", target_wave, interpolation_diagnostics
        ),
        "geometric_albedo": _interpolate_output(
            reflected_out, "albedo", target_wave, interpolation_diagnostics
        ),
        "climate_converged": bool(np.asarray(climate_out.get("converged", False)).item()),
        "climate_retry_count": climate_retry_count,
        "chemistry_mode": chemistry_mode,
        "quench_enabled": bool(row["quench"]),
        "quench_applied": bool(row["quench"]),
        "quench_profile_differs_from_equilibrium": (
            final_differs_from_equilibrium if chemistry_mode == "disequilibrium_quench" else False
        ),
        "quench_pressure_extension_applied": bool(quench_extension["applied"]),
        "quench_pressure_extension_retry_count": int(quench_extension["retry_count"]),
        "quench_pressure_extension_maximum_bar": quench_extension["maximum_pressure_bar"],
        "quench_pressures_bar": dict(quench_extension["pressures_bar"]),
        "virga_minimum_particle_radius_cm": 1.0e-8,
        "virga_minimum_particle_clamp_count": int(virga_particle_guard["clamp_count"]),
        "zero_cloud_convergence_guard_count": int(
            zero_cloud_convergence_guard["adjustment_count"]
        ),
        "diseq_chem": bool(row["diseq_chem"]),
        "self_consistent_kzz": bool(row["self_consistent_kzz"]),
        "max_quench_log10_difference": (
            max_log_difference if chemistry_mode == "disequilibrium_quench" else 0.0
        ),
        "max_equilibrium_consistency_log10_difference": max_log_difference,
        "equilibrium_consistency_tolerance_dex": equilibrium_consistency_tolerance_dex,
        "selected_opacity_file": str(selected_opacity),
        "runtime_seconds": time.monotonic() - started,
        "interpolation_diagnostics": interpolation_diagnostics,
        "thermal_flux_ratio_correction": thermal_correction,
    }
    return result
