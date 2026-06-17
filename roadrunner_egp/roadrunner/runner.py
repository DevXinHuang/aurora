"""
roadrunner.runner
~~~~~~~~~~~~~~~~
PICASO execution: run reflected + thermal spectra and extract absolute
planet fluxes with correct unit conversions.
"""

import os

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
    equilibrium chemistry, then Virga/Jupiter/clear clouds.
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
    out_em = case.spectrum(opa, calculation="thermal", as_dict=True)

    return out_ref, out_em


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
