"""
roadrunner.runner
~~~~~~~~~~~~~~~~
PICASO execution: run reflected + thermal spectra and extract absolute
planet fluxes with correct unit conversions.
"""

import os
import re
import inspect
from pathlib import Path
from typing import Any

import numpy as np
from scipy.interpolate import interp1d
from astropy import units as u
from astropy.constants import R_jup, R_sun, au

from .config import (
    ATM_NLAYERS,
    DEFAULT_PICASO_VIRGA_CONDENSATES,
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
PHASE_ANGLE_PI_EPS_RAD = 1.0e-6
_VIRGA_SUBLAYER_PATCH_APPLIED = False


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
    """Normalize user-facing atmosphere source names.

    The internal name ``picaso`` means the legacy analytic-Guillot path, not
    the converged climate solver. Science grid runs should use
    ``picaso_climate``.
    """
    source = (source or "slgrid").strip().lower()
    aliases = {
        "files": "slgrid",
        "file": "slgrid",
        "slgrid": "slgrid",
        "picaso": "picaso",
        "picaso_generated": "picaso",
        "generated": "picaso",
        "guillot": "picaso",
        "picaso_guillot": "picaso",
        "picaso_climate": "picaso_climate",
        "climate": "picaso_climate",
        "full_picaso": "picaso",
    }
    if source not in aliases:
        raise ValueError(
            "Unknown atmosphere source "
            f"{source!r}; choose 'slgrid', 'picaso_guillot', or 'picaso_climate'."
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


def reflected_phase_angle_rad(phase_deg: float) -> float:
    """Return a reflected-light-safe phase angle in radians.

    PICASO's reflected phase geometry has a singularity at 180 degrees
    (cos(phase)+1 == 0). Use a finite epsilon below pi because some downstream
    code paths reduce precision and can still hit the singularity if we only
    use ``np.nextafter``.
    """
    phase_rad = float(np.deg2rad(float(phase_deg)))
    if phase_rad >= np.pi or np.isclose(phase_rad, np.pi, rtol=0.0, atol=1.0e-12):
        return float(np.pi - PHASE_ANGLE_PI_EPS_RAD)
    return phase_rad


def _patch_virga_calc_optics_sublayer_guard(verbose: bool = False) -> bool:
    """Patch VIRGA calc_optics bottom-layer guard in-process if needed.

    VIRGA versions with guard ``ibot >= nz - 2`` can still write ``ibot+3``,
    which overflows when cloud decks sit near the pressure-grid bottom
    (e.g., ibot == nz-3). This patch rewrites that guard to ``ibot >= nz - 4``.
    """
    global _VIRGA_SUBLAYER_PATCH_APPLIED
    if _VIRGA_SUBLAYER_PATCH_APPLIED:
        return True

    try:
        import virga.justdoit as virga_jdi
    except Exception:
        return False

    calc_optics = getattr(virga_jdi, "calc_optics", None)
    if not callable(calc_optics):
        return False
    if getattr(calc_optics, "_aurora_sublayer_guard_patch", False):
        _VIRGA_SUBLAYER_PATCH_APPLIED = True
        return True

    try:
        source = inspect.getsource(calc_optics)
    except (OSError, TypeError):
        return False

    patched_guard_pattern = r"^\s*if\s+ibot\s*>=\s*nz\s*-\s*4\s*:"
    if re.search(patched_guard_pattern, source, flags=re.MULTILINE):
        setattr(calc_optics, "_aurora_sublayer_guard_patch", True)
        _VIRGA_SUBLAYER_PATCH_APPLIED = True
        return True

    old_guard_pattern = r"^(\s*)if\s+ibot\s*>=\s*nz\s*-\s*2\s*:"
    if not re.search(old_guard_pattern, source, flags=re.MULTILINE):
        return False

    patched_source = re.sub(
        old_guard_pattern,
        r"\1if ibot >= nz - 4:",
        source,
        count=1,
        flags=re.MULTILINE,
    )
    try:
        exec(compile(patched_source, calc_optics.__code__.co_filename, "exec"), virga_jdi.__dict__)
    except Exception:
        return False

    patched_calc_optics = getattr(virga_jdi, "calc_optics", None)
    if not callable(patched_calc_optics):
        return False
    setattr(patched_calc_optics, "_aurora_sublayer_guard_patch", True)
    _VIRGA_SUBLAYER_PATCH_APPLIED = True
    if verbose:
        print("✓ Applied runtime VIRGA calc_optics bottom-layer guard patch")
    return True


def _virga_condensates(value):
    """Normalize Virga condensates from string/list into a list PICASO accepts."""
    fallback = [
        part
        for part in re.split(r"[,;\s]+", DEFAULT_PICASO_VIRGA_CONDENSATES)
        if part
    ]
    if value is None:
        return fallback
    if isinstance(value, str):
        parts = [part for part in re.split(r"[,;\s]+", value.strip()) if part]
        return parts or fallback
    try:
        return list(value)
    except TypeError:
        return [str(value)]


def _patchy_cloud_kwargs(system: SystemParams) -> dict[str, Any]:
    """Return native PICASO patchy-cloud kwargs from cloudy fraction.

    PICASO's do_holes mode also expects fthin_cld to be numeric.
    For a standard patchy case, the cloudy portion keeps full cloud opacity,
    so fthin_cld=1.0 and fhole is the clear-hole area fraction.
    """
    cloud_fraction = float(getattr(system, "cloud_fraction", 1.0))
    if cloud_fraction < 0.0 or cloud_fraction > 1.0:
        raise ValueError(f"cloud_fraction must be between 0 and 1; got {cloud_fraction}")
    fhole = float(getattr(system, "cloud_hole_fraction", 1.0 - cloud_fraction))
    if cloud_fraction >= 1.0:
        return {"do_holes": False, "fhole": None, "fthin_cld": 1.0}
    if cloud_fraction <= 0.0:
        return {"do_holes": False, "fhole": None, "fthin_cld": 0.0}
    return {"do_holes": True, "fhole": fhole, "fthin_cld": 1.0}

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
    """Build a generated PICASO atmosphere instead of reading SLGRID files.

    The Guillot (2010) P-T profile is the final atmosphere only for the legacy
    ``picaso_guillot`` spectrum route. In the recommended ``picaso_climate``
    route it is merely the initial temperature guess: ``cl_run.climate(...)``
    subsequently performs radiative-convective convergence and replaces it.
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
            _patch_virga_calc_optics_sublayer_guard(verbose=verbose)
            case.inputs["atmosphere"]["profile"]["kz"] = sys.kzz_cgs
            patchy_kwargs = _patchy_cloud_kwargs(sys)
            case.virga(
                condensates=_virga_condensates(sys.virga_condensates),
                directory=sys.virga_dir,
                fsed=sys.virga_fsed,
                kz_min=sys.kzz_cgs,
                do_holes=patchy_kwargs["do_holes"],
                fhole=patchy_kwargs["fhole"],
                fthin_cld=patchy_kwargs["fthin_cld"],
            )
            if verbose:
                print(
                    "✓ Using generated PICASO atmosphere "
                    f"(Guillot PT, Teq={teq:.1f} K, "
                    f"Virga {sys.virga_condensates}, fsed={sys.virga_fsed:g})"
                )
            return
        except Exception as exc:
            if os.environ.get("ROADRUNNER_REQUIRE_VIRGA", "0").lower() in {"1", "true", "yes", "y"}:
                raise RuntimeError(f"Virga failed and ROADRUNNER_REQUIRE_VIRGA=1: {exc}") from exc
            if verbose:
                print(f"⚠ Virga not available ({exc}), using Jupiter cloud model")

    patchy_kwargs = _patchy_cloud_kwargs(sys)
    jupiter_cloud_profile = _jupiter_cloud_profile_for_nlevel(ATM_NLAYERS)
    case.clouds(
        df=jupiter_cloud_profile,
        do_holes=patchy_kwargs["do_holes"],
        fhole=patchy_kwargs["fhole"],
        fthin_cld=patchy_kwargs["fthin_cld"],
    )
    if verbose:
        print(
            "✓ Using generated PICASO atmosphere "
            f"(Guillot PT, Teq={teq:.1f} K, Jupiter cloud fallback)"
        )


def _jupiter_cloud_profile_for_nlevel(nlevel: int):
    """Return PICASO's Jupiter cloud profile on ``nlevel - 1`` layers.

    PICASO's bundled ``jupiterf3.cld`` contains 60 layers. Aurora now uses 91
    pressure levels (90 layers), so the legacy Jupiter fallback must be
    interpolated in normalized vertical-layer coordinate before
    ``case.clouds`` validates its shape. Virga does not use this adapter.
    """
    import pandas as pd

    if nlevel < 2:
        raise ValueError(f"nlevel must be at least 2; got {nlevel!r}")

    source = pd.read_csv(jdi.jupiter_cld(), sep=r"\s+")
    source.columns = [str(column).lower() for column in source.columns]
    required = {"lvl", "wv", "opd", "w0", "g0"}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(
            f"PICASO Jupiter cloud profile is missing columns: {sorted(missing)}"
        )

    source_layers = np.sort(source["lvl"].unique().astype(float))
    wavelengths = np.sort(source["wv"].unique())
    target_layer_count = int(nlevel) - 1
    if source_layers.size == target_layer_count:
        return source.loc[:, ["opd", "w0", "g0"]].reset_index(drop=True)

    target_positions = np.linspace(
        float(source_layers[0]),
        float(source_layers[-1]),
        target_layer_count,
    )
    target = {
        "opd": np.empty((target_layer_count, wavelengths.size), dtype=float),
        "w0": np.empty((target_layer_count, wavelengths.size), dtype=float),
        "g0": np.empty((target_layer_count, wavelengths.size), dtype=float),
    }
    for wave_index, wavelength in enumerate(wavelengths):
        wave_rows = source.loc[source["wv"] == wavelength].sort_values("lvl")
        wave_layers = wave_rows["lvl"].to_numpy(dtype=float)
        for column in target:
            target[column][:, wave_index] = np.interp(
                target_positions,
                wave_layers,
                wave_rows[column].to_numpy(dtype=float),
            )

    # Layer-major and wavelength-minor ordering matches the bundled file and
    # the shape expected by PICASO's no-pressure/no-wavenumber cloud input.
    return pd.DataFrame(
        {
            column: values.reshape(-1)
            for column, values in target.items()
        }
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
        PT profile, Visscher chemistry, and configured clouds in PICASO. This
        is the legacy, non-converged climate route; use
        :func:`run_picaso_climate_model_once` for an RCE-converged atmosphere.
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
        reflected_phase_angle_rad(sys.phase_deg),
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
        if "dtdp" in climate_out:
            diagnostics.setdefault("qc_dtdp", climate_out["dtdp"])
        _add_justplotit_climate_diagnostics(diagnostics, climate_out, cl_run, opa)
    else:
        diagnostics["schema_warnings"].append(
            f"PICASO climate returned {type(climate_out).__name__}, not dict"
        )
    return diagnostics


def _apply_climate_profile_to_case(case, climate_out: dict[str, Any]) -> None:
    profile = case.inputs["atmosphere"]["profile"]
    if "pressure" in climate_out:
        profile["pressure"] = np.asarray(climate_out["pressure"], dtype=float)
    if "temperature" in climate_out:
        profile["temperature"] = np.asarray(climate_out["temperature"], dtype=float)


def _compact_climate_diagnostics(
    climate_out: dict[str, Any],
    selected_ck_file: Path,
    climate_input_summary: dict[str, Any],
    cl_run,
    opa,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "selected_ck_file": str(selected_ck_file),
        "climate_opacity_method": "preweighted",
        "initial_pressure": climate_input_summary["pressure"],
        "initial_temp_guess": climate_input_summary["temp_guess"],
        "rcb_guess": climate_input_summary["rcb_guess"],
        "nstr": climate_input_summary["nstr"],
        "rfacv": climate_input_summary["rfacv"],
        "rfaci": climate_input_summary["rfaci"],
        "moistgrad": climate_input_summary["moistgrad"],
        "schema_warnings": [],
    }
    if "dtdp" in climate_out:
        diagnostics["dtdp"] = climate_out["dtdp"]
        diagnostics["qc_dtdp"] = climate_out["dtdp"]
    for source_key, target_key in {
        "fnet/fnetir": "fnet_irfnet",
        "flux_balance": "flux_balance",
        "spectrum_output": "spectrum_output",
        "pressure": "pressure",
        "temperature": "temperature",
        "converged": "climate_converged",
    }.items():
        if source_key in climate_out:
            diagnostics[target_key] = climate_out[source_key]
    _add_justplotit_climate_diagnostics(diagnostics, climate_out, cl_run, opa)
    return diagnostics


def _setup_picaso_climate_case(
    system: SystemParams,
    output_grid: np.ndarray,
    ck_root: str | Path | None = None,
    cloud_model: str | None = None,
    verbose: bool = True,
) -> tuple[Any, Any, Path, dict[str, Any]]:
    """Create PICASO climate inputs, star/planet setup, and opacity connection."""
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
    # Seed chemistry/cloud inputs and an initial Guillot P-T guess. The call to
    # cl_run.climate(...) in the convergence routines below replaces this
    # initial guess with the RCE-converged atmosphere used for the spectra.
    configure_picaso_atmosphere(
        cl_run,
        system,
        atmosphere_source="picaso",
        cloud_model=cloud_model,
        verbose=verbose,
    )
    climate_input_summary = configure_climate_inputs(cl_run, system)
    return cl_run, opa, selected_ck_file, climate_input_summary


def run_picaso_climate_converge_only(
    system: SystemParams,
    output_grid: np.ndarray,
    ck_root: str | Path | None = None,
    cloud_model: str | None = None,
    verbose: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], Path, Any]:
    """Run PICASO climate convergence only (no reflected-light spectrum).

    Returns ``(climate_out, diagnostics, selected_ck_file, cl_run)``. The
    converged ``cl_run`` object must be preserved for fast spectrum-only reruns.
    """
    cl_run, opa, selected_ck_file, climate_input_summary = _setup_picaso_climate_case(
        system,
        output_grid,
        ck_root=ck_root,
        cloud_model=cloud_model,
        verbose=verbose,
    )
    climate_out = cl_run.climate(opa, save_all_profiles=True, with_spec=True)
    if not isinstance(climate_out, dict):
        raise RuntimeError(f"PICASO climate returned {type(climate_out).__name__}, not dict")

    diagnostics = _compact_climate_diagnostics(
        climate_out,
        selected_ck_file,
        climate_input_summary,
        cl_run,
        opa,
    )
    return climate_out, diagnostics, selected_ck_file, cl_run


def run_picaso_reflected_spectrum_from_converged_case(
    cl_run: Any,
    system: SystemParams,
    output_grid: np.ndarray,
    selected_ck_file: str | Path,
) -> dict[str, Any]:
    """Compute reflected spectrum from an in-memory converged PICASO climate case."""
    output_grid = np.asarray(output_grid, dtype=float)
    opa = jdi.opannection(
        ck_db=str(selected_ck_file),
        wave_range=[float(np.nanmin(output_grid)), float(np.nanmax(output_grid))],
        method="preweighted",
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
    cl_run.phase_angle(
        reflected_phase_angle_rad(system.phase_deg),
        num_gangle=REFLECT_NUM_GANGLE,
        num_tangle=REFLECT_NUM_TANGLE,
    )
    return cl_run.spectrum(opa, calculation="reflected", as_dict=True, full_output=True)


def run_picaso_reflected_spectrum_from_climate_profile(
    system: SystemParams,
    output_grid: np.ndarray,
    climate_pressure: np.ndarray,
    climate_temperature: np.ndarray,
    *,
    ck_root: str | Path | None = None,
    selected_ck_file: str | Path | None = None,
    cloud_model: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Compute reflected spectrum at ``system.phase_deg`` from a converged PT profile."""
    cl_run, opa, ck_path, _climate_input_summary = _setup_picaso_climate_case(
        system,
        output_grid,
        ck_root=ck_root,
        cloud_model=cloud_model,
        verbose=verbose,
    )
    if selected_ck_file is not None:
        ck_path = Path(selected_ck_file)

    _apply_climate_profile_to_case(
        cl_run,
        {
            "pressure": np.asarray(climate_pressure, dtype=float),
            "temperature": np.asarray(climate_temperature, dtype=float),
        },
    )
    cl_run.phase_angle(
        reflected_phase_angle_rad(system.phase_deg),
        num_gangle=REFLECT_NUM_GANGLE,
        num_tangle=REFLECT_NUM_TANGLE,
    )
    return cl_run.spectrum(opa, calculation="reflected", as_dict=True, full_output=True)


def run_picaso_climate_model_once(
    system: SystemParams,
    output_grid: np.ndarray,
    ck_root: str | Path | None = None,
    cloud_model: str | None = None,
    verbose: bool = True,
    return_case: bool = False,
    return_opacity: bool = False,
) -> tuple[Any, ...]:
    """Run PICASO climate as the primary atmosphere, then spectra from it."""
    cl_run, opa, selected_ck_file, climate_input_summary = _setup_picaso_climate_case(
        system,
        output_grid,
        ck_root=ck_root,
        cloud_model=cloud_model,
        verbose=verbose,
    )
    climate_out = cl_run.climate(opa, save_all_profiles=True, with_spec=True)
    if not isinstance(climate_out, dict):
        raise RuntimeError(f"PICASO climate returned {type(climate_out).__name__}, not dict")

    _apply_climate_profile_to_case(cl_run, climate_out)

    cl_run.phase_angle(
        reflected_phase_angle_rad(system.phase_deg),
        num_gangle=REFLECT_NUM_GANGLE,
        num_tangle=REFLECT_NUM_TANGLE,
    )
    out_ref = cl_run.spectrum(opa, calculation="reflected", as_dict=True, full_output=True)
    out_em = climate_out.get("spectrum_output")
    if not isinstance(out_em, dict):
        out_em = {}

    diagnostics = _compact_climate_diagnostics(
        climate_out,
        selected_ck_file,
        climate_input_summary,
        cl_run,
        opa,
    )

    result = (out_ref, out_em, climate_out, diagnostics)
    if return_case and return_opacity:
        return (*result, cl_run, opa)
    if return_case:
        return (*result, cl_run)
    if return_opacity:
        return (*result, opa)
    return result


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
    if isinstance(out_em, dict) and "wavenumber" in out_em and "thermal" in out_em:
        wno_em = out_em["wavenumber"]
        lam_cm_em = 1.0 / wno_em
        wl_em_um = lam_cm_em * 1e4
        fp_th_raw = out_em["thermal"]
        fp_th_per_um = fp_th_raw * 1e-4
        fp_thermal = interp1d(
            wl_em_um, fp_th_per_um, bounds_error=False, fill_value=0.0,
        )(lam_grid_um)
    else:
        fp_thermal = np.zeros_like(lam_grid_um, dtype=float)

    # clean NaNs
    fp_reflected = np.nan_to_num(fp_reflected, nan=0.0, posinf=0.0, neginf=0.0)
    fp_thermal   = np.nan_to_num(fp_thermal,   nan=0.0, posinf=0.0, neginf=0.0)

    return lam_grid_um, fp_reflected, fp_thermal
