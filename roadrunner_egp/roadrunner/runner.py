"""
roadrunner.runner
~~~~~~~~~~~~~~~~
PICASO execution: run reflected + thermal spectra and extract absolute
planet fluxes with correct unit conversions.
"""

import os
import inspect
from pathlib import Path
from typing import Any

import numpy as np
from scipy.interpolate import interp1d
from astropy import units as u
from astropy.constants import R_jup, R_sun, au

from .config import (
    ATM_NLAYERS,
    HAVE_PICASO,
    jdi,
    blackbody,
    REFLECT_NUM_GANGLE,
    REFLECT_NUM_TANGLE,
    THERMAL_NUM_GANGLE,
    THERMAL_NUM_TANGLE,
)
from .system import SystemParams, resolve_slgrid_files


PICASO4_CK_FEH_VALUES = np.array(
    [-2.0, -1.5, -1.0, -0.7, -0.5, -0.3, 0.0, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0],
    dtype=float,
)
PICASO4_CK_CO_VALUES = np.array([0.14, 0.27, 0.46, 0.55, 0.82, 1.10], dtype=float)
PICASO4_SOLAR_C_TO_O = 0.55


def _nearest_available(value: float, available: np.ndarray) -> float:
    return float(available[int(np.argmin(np.abs(available - float(value))))])


def default_picaso4_ck_roots() -> list[Path]:
    """Return candidate local roots for PICASO 4 preweighted CK opacity files."""
    env_root = os.environ.get("PICASO_CK_ROOT")
    if env_root:
        return [Path(env_root).expanduser()]

    repo_root = Path(__file__).resolve().parents[2]
    return [
        repo_root / "picaso4_reference" / "opacities" / "preweighted",
        repo_root / "picaso4_reference" / "opacities",
    ]


def picaso4_preweighted_ck_filename(system: SystemParams) -> str:
    """Return the nearest-grid PICASO 4 preweighted CK filename for a system."""
    feh = _nearest_available(system.chem_log_mh, PICASO4_CK_FEH_VALUES)
    absolute_co = float(system.chem_c_o) * PICASO4_SOLAR_C_TO_O
    co = _nearest_available(absolute_co, PICASO4_CK_CO_VALUES)
    return f"sonora_2121grid_feh{feh:.1f}_co{co:.2f}.hdf5"


def select_picaso4_preweighted_ck_file(
    system: SystemParams,
    ck_root: str | Path | None = None,
) -> Path:
    """
    Locate the nearest-grid PICASO 4 preweighted correlated-k opacity file.

    The chemistry convention matches ``chemeq_visscher_2121``: ``chem_c_o`` is
    stored as x-solar and converted to absolute C/O by multiplying by 0.55.
    """
    expected_name = picaso4_preweighted_ck_filename(system)
    roots = [Path(ck_root).expanduser()] if ck_root is not None else default_picaso4_ck_roots()
    searched: list[str] = []
    for root in roots:
        searched.append(str(root))
        candidate = root / expected_name
        if candidate.exists():
            return candidate
        if root.exists():
            matches = sorted(root.rglob(expected_name))
            if matches:
                return matches[0]

    absolute_co = float(system.chem_c_o) * PICASO4_SOLAR_C_TO_O
    raise FileNotFoundError(
        "PICASO 4 preweighted CK opacity file not found. "
        f"Expected {expected_name!r} for chem_log_mh={system.chem_log_mh:g}, "
        f"chem_c_o_xsolar={system.chem_c_o:g}, absolute_c_to_o={absolute_co:g}. "
        f"Searched: {searched}."
    )


def normalize_atmosphere_source(source: str | None) -> str:
    """Normalize user-facing atmosphere source names."""
    source = (source or "slgrid").strip().lower()
    aliases = {
        "files": "slgrid",
        "file": "slgrid",
        "slgrid": "slgrid",
        "picaso": "picaso",
        "picaso_generated": "picaso",
        "generated": "picaso",
        "guillot": "picaso",
        "full_picaso": "picaso",
    }
    if source not in aliases:
        raise ValueError(
            "Unknown atmosphere source "
            f"{source!r}; choose 'slgrid' or 'picaso'."
        )
    return aliases[source]


def normalize_cloud_model(cloud_model: str | None) -> str:
    """Normalize generated-PICASO cloud model names."""
    cloud_model = (cloud_model or "virga").strip().lower()
    aliases = {
        "virga": "virga",
        "jupiter": "jupiter",
        "jupiter_cld": "jupiter",
        "jupiter_cloud": "jupiter",
        "none": "none",
        "clear": "none",
        "cloudfree": "none",
        "cloud-free": "none",
    }
    if cloud_model not in aliases:
        raise ValueError(
            "Unknown cloud model "
            f"{cloud_model!r}; choose 'virga', 'jupiter', or 'none'."
        )
    return aliases[cloud_model]


def equilibrium_temperature(sys: SystemParams) -> float:
    """Estimate equilibrium temperature from star/orbit and Bond albedo."""
    radius = sys.rstar_rsun * R_sun.value
    semi_major = sys.a_au * au.value
    albedo_factor = max(0.0, 1.0 - float(sys.bond_albedo)) ** 0.25
    return sys.tstar_k * np.sqrt(radius / (2.0 * semi_major)) * albedo_factor


def _load_slgrid_atmosphere(case, sys: SystemParams, verbose: bool = True) -> None:
    """Attach the matching SLGRID PT and cloud profiles to a PICASO case."""
    pt_path, cld_path = resolve_slgrid_files(sys)
    case.atmosphere(filename=pt_path, sep=r"\s+")

    if cld_path is None:
        if verbose:
            print(f"✓ Using SLGRID PT:  {os.path.basename(pt_path)}")
            print("✓ Using SLGRID CLD: none (NC / zero cloud fraction)")
        return

    # Read cloud file manually and normalise column names to lowercase
    # (some SLGRID files use 'Opd' instead of 'opd', which trips PICASO's
    # assertion check).
    import pandas as _pd
    cld_df = _pd.read_csv(cld_path, sep=r"\s+")
    cld_df.columns = [c.lower() for c in cld_df.columns]
    case.clouds(df=cld_df)

    if verbose:
        print(f"✓ Using SLGRID PT:  {os.path.basename(pt_path)}")
        print(f"✓ Using SLGRID CLD: {os.path.basename(cld_path)}")


def _build_generated_picaso_atmosphere(
    case,
    sys: SystemParams,
    cloud_model: str | None = None,
    verbose: bool = True,
) -> None:
    """
    Build the atmosphere inside PICASO instead of reading SLGRID files.

    This follows the notebook pattern: Guillot (2010) PT profile, Visscher
    equilibrium chemistry, then Virga/Jupiter/clear clouds. that is the old way don't use this
    """
    teq = equilibrium_temperature(sys)
    case.guillot_pt(Teq=teq, T_int=sys.teff_k, nlevel=ATM_NLAYERS)
    # PICASO4 2121 chemistry expects absolute C/O, not C/O relative to solar.
    # Our system value is x-solar (e.g. 0.5, 1.0, 2.0), so convert to absolute by
    # multiplying by the solar C/O ratio used in PICASO 2121 (≈ 0.55).
    case.chemeq_visscher_2121(
        cto_absolute=sys.chem_c_o * 0.55,
        log_mh=sys.chem_log_mh,
    )

    model = normalize_cloud_model(cloud_model or sys.cloud_model)
    if model == "none":
        if verbose:
            print(
                "✓ Using generated PICASO atmosphere "
                f"(Guillot PT, Teq={teq:.1f} K, cloud-free)"
            )
        return

    if model == "virga":
        try:
            case.inputs["atmosphere"]["profile"]["kz"] = sys.kzz_cgs
            case.virga(
                condensates=sys.virga_condensates,
                directory=sys.virga_dir,
                fsed=sys.virga_fsed,
            )
            if verbose:
                print(
                    "✓ Using generated PICASO atmosphere "
                    f"(Guillot PT, Teq={teq:.1f} K, "
                    f"Virga {sys.virga_condensates}, fsed={sys.virga_fsed:g})"
                )
            return
        except Exception as exc:
            if verbose:
                print(f"⚠ Virga not available ({exc}), using Jupiter cloud model")

    case.clouds(filename=jdi.jupiter_cld(), sep=r"\s+")
    if verbose:
        print(
            "✓ Using generated PICASO atmosphere "
            f"(Guillot PT, Teq={teq:.1f} K, Jupiter cloud fallback)"
        )


def configure_picaso_atmosphere(
    case,
    sys: SystemParams,
    atmosphere_source: str | None = None,
    cloud_model: str | None = None,
    verbose: bool = True,
) -> str:
    """Attach atmosphere/cloud inputs to a PICASO case and return the source."""
    source = normalize_atmosphere_source(atmosphere_source or sys.atmosphere_source)
    if source == "slgrid":
        _load_slgrid_atmosphere(case, sys, verbose=verbose)
    else:
        _build_generated_picaso_atmosphere(
            case,
            sys,
            cloud_model=cloud_model,
            verbose=verbose,
        )
    return source

# ---------------------------------------------------------------------------
# Run PICASO (reflected + thermal)
# ---------------------------------------------------------------------------

def run_picaso_once(
    sys: SystemParams,
    lam_grid_um: np.ndarray,
    wave_range=None,
    atmosphere_source: str | None = None,
    cloud_model: str | None = None,
    verbose: bool = True,
    return_case: bool = False,
    return_opacity: bool = False,
):
    """
    Run PICASO for both reflected and thermal spectra.

    Parameters
    ----------
    sys : SystemParams
        Planet / star system configuration.
    lam_grid_um : array
        Wavelength grid in µm used for interpolation of the final outputs.
    wave_range : sequence[float, float], optional
        Explicit PICASO opacity range in µm. If omitted, the minimum and
        maximum of ``lam_grid_um`` are used.
    atmosphere_source : str, optional
        ``"slgrid"`` reads PT/cloud files. ``"picaso"`` generates a Guillot
        PT profile, Visscher chemistry, and configured clouds in PICASO.
    cloud_model : str, optional
        Generated-PICASO cloud model: ``"virga"``, ``"jupiter"``, or
        ``"none"``.
    return_case : bool, optional
        Also return the original PICASO inputs object for model preservation.
    return_opacity : bool, optional
        Also return the opacity connection for in-memory diagnostics.

    Returns
    -------
    out_ref, out_em : dict
        PICASO output dictionaries for reflected and thermal calculations.
    """
    assert HAVE_PICASO, "PICASO is required"

    if wave_range is None:
        lam_grid_um = np.asarray(lam_grid_um, dtype=float)
        wave_range = [
            float(np.nanmin(lam_grid_um)),
            float(np.nanmax(lam_grid_um)),
        ]

    opa = jdi.opannection(wave_range=wave_range)

    case = jdi.inputs()
    g_cgs = 10 ** sys.logg_cgs
    case.gravity(
        gravity=g_cgs, gravity_unit=u.cm / u.s**2,
        radius=sys.rj, radius_unit=u.R_jup,
    )
    case.star(
        opa, temp=sys.tstar_k, metal=0, logg=4.44,
        radius=sys.rstar_rsun, radius_unit=u.R_sun,
        semi_major=sys.a_au, semi_major_unit=u.AU,
    )

    configure_picaso_atmosphere(
        case,
        sys,
        atmosphere_source=atmosphere_source,
        cloud_model=cloud_model,
        verbose=verbose,
    )

    # Reflected at requested phase  (full_output for diagnostics)
    case.phase_angle(
        np.deg2rad(sys.phase_deg),
        num_gangle=REFLECT_NUM_GANGLE,
        num_tangle=REFLECT_NUM_TANGLE,
    )
    out_ref = case.spectrum(opa, calculation="reflected",
                            as_dict=True, full_output=True)

    # Thermal at zero phase (1-D thermal must be phase=0)
    case.phase_angle(
        0.0,
        num_gangle=THERMAL_NUM_GANGLE,
        num_tangle=THERMAL_NUM_TANGLE,
    )
    out_em = case.spectrum(opa, calculation="thermal", as_dict=True, full_output=True)

    if return_case and return_opacity:
        return out_ref, out_em, case, opa
    if return_case:
        return out_ref, out_em, case
    if return_opacity:
        return out_ref, out_em, opa
    return out_ref, out_em


def _as_1d_float_or_none(values: Any) -> np.ndarray | None:
    if values is None:
        return None
    try:
        array = np.asarray(values, dtype=float)
    except Exception:
        return None
    if array.ndim != 1:
        array = np.ravel(array)
    if array.size == 0:
        return None
    return array


def _parse_adiabat_result(result: Any) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    if not isinstance(result, (tuple, list)):
        return None, None, None
    if len(result) >= 4:
        _, adiabat, dtdp, pressure = result[:4]
    elif len(result) >= 3:
        adiabat, dtdp, pressure = result[:3]
    else:
        return None, None, None
    return (
        _as_1d_float_or_none(adiabat),
        _as_1d_float_or_none(dtdp),
        _as_1d_float_or_none(pressure),
    )


def _brightness_wavelength_from_spectrum(spectrum_output: Any, brightness: np.ndarray) -> np.ndarray | None:
    if not isinstance(spectrum_output, dict) or "wavenumber" not in spectrum_output:
        return None
    wno = _as_1d_float_or_none(spectrum_output.get("wavenumber"))
    if wno is None or wno.size != brightness.size:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0e4 / wno


def configure_climate_inputs(
    cl_run,
    system: SystemParams,
    *,
    rfacv: float = 0.5,
    rfaci: float = 1.0,
    moistgrad: bool = False,
) -> dict[str, Any]:
    """Attach PICASO climate solver controls using the generated PT profile."""
    if hasattr(cl_run, "effective_temp"):
        cl_run.effective_temp(float(system.teff_k))
    else:
        cl_run.T_eff(float(system.teff_k))

    profile = cl_run.inputs["atmosphere"]["profile"]
    pressure = np.asarray(profile["pressure"], dtype=float)
    temp_guess = np.asarray(profile["temperature"], dtype=float)

    nlevel = len(pressure)
    rcb_guess = max(1, nlevel - 7)
    nstr = np.array([0, rcb_guess, nlevel - 2, 0, 0, 0])

    sig = inspect.signature(cl_run.inputs_climate)
    params = sig.parameters
    kwargs: dict[str, Any] = {
        "temp_guess": temp_guess,
        "pressure": pressure,
        "rfacv": rfacv,
        "moistgrad": moistgrad,
    }

    if "rfaci" in params:
        kwargs["rfaci"] = rfaci

    if "rcb_guess" in params:
        kwargs["rcb_guess"] = rcb_guess
    else:
        kwargs["nstr"] = nstr
        kwargs["nofczns"] = 1

    cl_run.inputs_climate(**kwargs)

    return {
        "pressure": pressure,
        "temp_guess": temp_guess,
        "rcb_guess": rcb_guess,
        "nstr": nstr,
        "rfacv": rfacv,
        "rfaci": rfaci,
        "moistgrad": moistgrad,
    }


def _add_justplotit_climate_diagnostics(
    diagnostics: dict[str, Any],
    climate_out: dict[str, Any],
    cl_run: Any,
    opa: Any,
) -> None:
    warnings = diagnostics.setdefault("schema_warnings", [])
    try:
        from picaso import justplotit as jpi
    except Exception as exc:
        warnings.append(f"PICASO justplotit diagnostics unavailable: {exc}")
        return

    pt_adiabat = getattr(jpi, "pt_adiabat", None)
    if pt_adiabat is not None:
        last_error: Exception | str = "no usable adiabat arrays returned"
        for call in (
            lambda: pt_adiabat(climate_out, cl_run, opa, plot=False),
            lambda: pt_adiabat(climate_out, cl_run, plot=False),
        ):
            try:
                adiabat, dtdp, pressure = _parse_adiabat_result(call())
            except Exception as exc:
                last_error = exc
                continue
            if adiabat is not None and dtdp is not None and pressure is not None:
                diagnostics["qc_adiabat"] = adiabat
                diagnostics["qc_dtdp"] = dtdp
                diagnostics["qc_adiabat_pressure"] = pressure
                break
        else:
            warnings.append(f"PICASO adiabat diagnostic unavailable: {last_error}")
    else:
        warnings.append("PICASO adiabat diagnostic unavailable: pt_adiabat missing")

    spectrum_output = climate_out.get("spectrum_output")
    brightness_temperature = getattr(jpi, "brightness_temperature", None)
    if brightness_temperature is not None and spectrum_output is not None:
        last_error = "no usable brightness-temperature array returned"
        for call in (
            lambda: brightness_temperature(spectrum_output, plot=False),
            lambda: brightness_temperature(spectrum_output),
        ):
            try:
                brightness = _as_1d_float_or_none(call())
            except Exception as exc:
                last_error = exc
                continue
            if brightness is not None:
                diagnostics["qc_brightness_temperature"] = brightness
                wavelength = _brightness_wavelength_from_spectrum(spectrum_output, brightness)
                if wavelength is not None:
                    diagnostics["qc_brightness_wavelength"] = wavelength
                break
        else:
            warnings.append(f"PICASO brightness-temperature diagnostic unavailable: {last_error}")
    else:
        warnings.append("PICASO brightness-temperature diagnostic unavailable")


def run_picaso_climate_diagnostics_once(
    system: SystemParams,
    output_grid: np.ndarray,
    ck_root: str | Path | None = None,
    cloud_model: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Run PICASO's exact climate path once and return compact QC diagnostics."""
    assert HAVE_PICASO, "PICASO is required"

    output_grid = np.asarray(output_grid, dtype=float)
    selected_ck_file = select_picaso4_preweighted_ck_file(system, ck_root=ck_root)
    opa = jdi.opannection(
        ck_db=str(selected_ck_file),
        wave_range=[float(np.nanmin(output_grid)), float(np.nanmax(output_grid))],
        method="preweighted",
    )

    cl_run = jdi.inputs(calculation="planet", climate=True)
    g_cgs = 10 ** system.logg_cgs
    cl_run.gravity(
        gravity=g_cgs,
        gravity_unit=u.cm / u.s**2,
        radius=system.rj,
        radius_unit=u.R_jup,
    )
    cl_run.star(
        opa,
        temp=system.tstar_k,
        metal=0,
        logg=4.44,
        radius=system.rstar_rsun,
        radius_unit=u.R_sun,
        semi_major=system.a_au,
        semi_major_unit=u.AU,
    )

    configure_picaso_atmosphere(
        cl_run,
        system,
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        verbose=verbose,
    )
    climate_input_summary = configure_climate_inputs(cl_run, system)

    climate_out = cl_run.climate(opa, save_all_profiles=True, with_spec=True)
    diagnostics: dict[str, Any] = {
        "selected_ck_file": str(selected_ck_file),
        "initial_pressure": climate_input_summary["pressure"],
        "initial_temp_guess": climate_input_summary["temp_guess"],
        "rcb_guess": climate_input_summary["rcb_guess"],
        "nstr": climate_input_summary["nstr"],
        "rfacv": climate_input_summary["rfacv"],
        "rfaci": climate_input_summary["rfaci"],
        "moistgrad": climate_input_summary["moistgrad"],
        "schema_warnings": [],
    }
    if isinstance(climate_out, dict):
        for source_key, target_key in {
            "dtdp": "dtdp",
            "fnet/fnetir": "fnet_irfnet",
            "flux_balance": "flux_balance",
            "spectrum_output": "spectrum_output",
            "pressure": "pressure",
            "temperature": "temperature",
            "converged": "converged",
        }.items():
            if source_key in climate_out:
                diagnostics[target_key] = climate_out[source_key]
        _add_justplotit_climate_diagnostics(diagnostics, climate_out, cl_run, opa)
    else:
        diagnostics["schema_warnings"].append(
            f"PICASO climate returned {type(climate_out).__name__}, not dict"
        )
    return diagnostics


# ---------------------------------------------------------------------------
# Extract absolute fluxes
# ---------------------------------------------------------------------------

def extract_planet_fluxes(out_ref: dict, out_em: dict,
                          lam_grid_um: np.ndarray,
                          sys: SystemParams):
    """
    Extract absolute planet fluxes (reflected + thermal) from PICASO
    output dicts.

    Returns
    -------
    lam_um, fp_reflected, fp_thermal : ndarray
        All on *lam_grid_um* in erg s⁻¹ cm⁻² µm⁻¹.
    """
    # --- reflected ---
    wno_ref    = out_ref["wavenumber"]
    lam_cm_ref = 1.0 / wno_ref
    wl_ref_um  = lam_cm_ref * 1e4

    fpfs_data = out_ref.get("fpfs_reflected", None)
    if isinstance(fpfs_data, np.ndarray):
        fpfs_ref = fpfs_data
    else:
        albedo   = out_ref["albedo"]
        Rp_cm    = sys.rj * R_jup.value
        a_cm     = sys.a_au * au.value
        fpfs_ref = albedo * (Rp_cm / a_cm) ** 2

    Fs_per_cm     = np.pi * np.squeeze(blackbody(sys.tstar_k, lam_cm_ref))
    Fp_ref_per_cm = fpfs_ref * Fs_per_cm       # erg/cm²/s/cm
    fp_ref_raw    = Fp_ref_per_cm * 1e-4        # → per µm

    fp_reflected = interp1d(
        wl_ref_um, fp_ref_raw, bounds_error=False, fill_value=0.0,
    )(lam_grid_um)

    # --- thermal ---
    wno_em    = out_em["wavenumber"]
    lam_cm_em = 1.0 / wno_em
    wl_em_um  = lam_cm_em * 1e4

    fp_th_raw   = out_em["thermal"]           # erg/cm²/s/cm
    fp_th_per_um = fp_th_raw * 1e-4           # → per µm
    fp_thermal  = interp1d(
        wl_em_um, fp_th_per_um, bounds_error=False, fill_value=0.0,
    )(lam_grid_um)

    # clean NaNs
    fp_reflected = np.nan_to_num(fp_reflected, nan=0.0, posinf=0.0, neginf=0.0)
    fp_thermal   = np.nan_to_num(fp_thermal,   nan=0.0, posinf=0.0, neginf=0.0)

    return lam_grid_um, fp_reflected, fp_thermal
