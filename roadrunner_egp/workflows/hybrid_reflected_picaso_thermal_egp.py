from __future__ import annotations

import concurrent.futures
import os
import re
import sys
from functools import lru_cache, partial
from pathlib import Path

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.constants import R_jup, au

try:
    from tqdm.auto import tqdm
except ImportError:
    tqdm = None


WORKFLOW_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORKFLOW_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from roadrunner.bands import (  # noqa: E402
    COLUMNS,
    band_metrics,
    select_bands,
    wavelength_grid_for_bands,
)
from roadrunner.config import (  # noqa: E402
    ATMOSPHERE_SOURCE,
    EGP_IRFLUX_DIR,
    HAVE_PICASO,
    LAM_GRID,
    LOGGS_CGS,
    PHASE_DEG,
    PICASO_CLOUD_MODEL,
    R_PLANETS_Rj,
    REFLECT_NUM_GANGLE,
    REFLECT_NUM_TANGLE,
    REFLECT_THRESHOLD,
    SEMI_MAJOR_AU,
    TEFFS_K,
    THERMAL_SOURCE,
    blackbody,
    jdi,
)
from roadrunner.plotting import plot_band_bars, plot_spectra_with_bb  # noqa: E402
from roadrunner.runner import (  # noqa: E402
    configure_picaso_atmosphere,
    extract_planet_fluxes,
    normalize_atmosphere_source,
    run_picaso_once,
)
from roadrunner.system import SystemParams, available_slgrid_teffs  # noqa: E402


EGP_GRID_DIR = Path(EGP_IRFLUX_DIR)
_EGP_NAME_RE = re.compile(r"^SLGRID_T(?P<teff>\d+)_g(?P<g>\d+)_.*_IRflux\.txt$")
_C_CGS = 2.99792458e10


def normalize_thermal_source(source: str | None) -> str:
    """Normalize user-facing thermal-source names."""
    source = (source or THERMAL_SOURCE).strip().lower()
    aliases = {
        "egp": "egp",
        "irflux": "egp",
        "egp_irflux": "egp",
        "file": "egp",
        "picaso": "picaso",
        "full_picaso": "picaso",
        "generated": "picaso",
    }
    if source not in aliases:
        raise ValueError(
            "Unknown thermal source "
            f"{source!r}; choose 'egp' or 'picaso'."
        )
    return aliases[source]


def _progress(iterable, total: int, desc: str):
    """Wrap an iterable in tqdm when available, otherwise print coarse progress."""
    if tqdm is not None:
        return tqdm(iterable, total=total, desc=desc)

    def _generator():
        step = max(1, total // 10)
        for index, item in enumerate(iterable, start=1):
            if index == 1 or index == total or index % step == 0:
                print(f"{desc}: {index}/{total}")
            yield item

    return _generator()


def egp_inventory(gravity_code: str = "31", egp_dir: str | Path = EGP_GRID_DIR) -> pd.DataFrame:
    """List the available EGP IRflux files for one gravity code."""
    rows = []
    for path in sorted(Path(egp_dir).glob(f"SLGRID_T*_g{gravity_code}_*_IRflux.txt")):
        match = _EGP_NAME_RE.match(path.name)
        if match:
            rows.append(
                {
                    "temperature_k": int(match.group("teff")),
                    "gravity_code": match.group("g"),
                    "filename": path.name,
                }
            )
    return pd.DataFrame(rows).sort_values("temperature_k").reset_index(drop=True)


def available_egp_temperatures(gravity_code: str = "31", egp_dir: str | Path = EGP_GRID_DIR) -> list[int]:
    """Temperatures available in the EGP grid for one gravity code."""
    inventory = egp_inventory(gravity_code=gravity_code, egp_dir=egp_dir)
    if inventory.empty:
        return []
    return inventory["temperature_k"].astype(int).tolist()


def available_hybrid_temperatures(gravity_code: str = "31") -> list[int]:
    """Intersection of SLGRID temperatures and EGP temperatures for a given gravity code."""
    slgrid_teffs = {int(teff) for teff in available_slgrid_teffs()}
    egp_teffs = set(available_egp_temperatures(gravity_code=gravity_code))
    return sorted(slgrid_teffs & egp_teffs)


def find_egp_irflux_file(
    temperature_k: int | float,
    gravity_code: str = "31",
    egp_dir: str | Path = EGP_GRID_DIR,
) -> Path:
    """Return the matching EGP IRflux file path for one temperature and gravity code."""
    pattern = f"SLGRID_T{int(round(float(temperature_k)))}_g{gravity_code}_*_IRflux.txt"
    matches = sorted(Path(egp_dir).glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No EGP IRflux file found for temperature={temperature_k} and g{gravity_code}."
        )
    return matches[0]


def _flux_nu_to_lambda_per_um(
    wavelength_um: np.ndarray,
    flux_nu_cgs: np.ndarray,
) -> np.ndarray:
    """Convert F_nu [erg cm^-2 s^-1 Hz^-1] to F_lambda [erg cm^-2 s^-1 um^-1]."""
    wavelength_cm = np.asarray(wavelength_um, dtype=float) * 1e-4
    flux_lambda_per_cm = np.asarray(flux_nu_cgs, dtype=float) * _C_CGS / wavelength_cm**2
    return flux_lambda_per_cm * 1e-4


@lru_cache(maxsize=None)
def load_egp_irflux_native(
    temperature_k: int | float,
    gravity_code: str = "31",
    egp_dir: str | Path = EGP_GRID_DIR,
) -> tuple[np.ndarray, np.ndarray, str]:
    """Load one EGP spectrum on its native grid and return wavelength, flux, and filename."""
    file_path = find_egp_irflux_file(
        temperature_k=temperature_k,
        gravity_code=gravity_code,
        egp_dir=egp_dir,
    )

    wavelengths = []
    flux_nu = []
    with file_path.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 4 and parts[0].isdigit():
                wavelengths.append(float(parts[1]))
                flux_nu.append(float(parts[3]))

    if not wavelengths:
        raise ValueError(f"Could not parse numeric spectrum rows from {file_path}.")

    wavelengths = np.asarray(wavelengths, dtype=float)
    flux_lambda_per_um = _flux_nu_to_lambda_per_um(wavelengths, np.asarray(flux_nu, dtype=float))
    order = np.argsort(wavelengths)
    return wavelengths[order], flux_lambda_per_um[order], file_path.name


@lru_cache(maxsize=None)
def load_egp_irflux_file_native(file_path: str | Path) -> tuple[np.ndarray, np.ndarray, str]:
    """Load one explicit EGP spectrum on its native grid."""
    file_path = Path(file_path)
    wavelengths = []
    flux_nu = []
    with file_path.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 4 and parts[0].isdigit():
                wavelengths.append(float(parts[1]))
                flux_nu.append(float(parts[3]))

    if not wavelengths:
        raise ValueError(f"Could not parse numeric spectrum rows from {file_path}.")

    wavelengths = np.asarray(wavelengths, dtype=float)
    flux_lambda_per_um = _flux_nu_to_lambda_per_um(wavelengths, np.asarray(flux_nu, dtype=float))
    order = np.argsort(wavelengths)
    return wavelengths[order], flux_lambda_per_um[order], file_path.name


def egp_thermal_on_grid(
    temperature_k: int | float,
    gravity_code: str = "31",
    lam_grid_um: np.ndarray = LAM_GRID,
    irflux_file: str | Path | None = None,
) -> tuple[np.ndarray, str]:
    """Interpolate one EGP thermal spectrum onto the Roadrunner wavelength grid."""
    if irflux_file is None:
        native_wavelength_um, native_flux_lambda_per_um, filename = load_egp_irflux_native(
            temperature_k=temperature_k,
            gravity_code=gravity_code,
        )
    else:
        native_wavelength_um, native_flux_lambda_per_um, filename = load_egp_irflux_file_native(
            str(irflux_file)
        )
    interpolated = np.interp(
        np.asarray(lam_grid_um, dtype=float),
        native_wavelength_um,
        native_flux_lambda_per_um,
        left=0.0,
        right=0.0,
    )
    return interpolated, filename


def run_picaso_reflected_only(
    sys_params: SystemParams,
    lam_grid_um: np.ndarray = LAM_GRID,
    full_output: bool = False,
    verbose: bool = False,
    atmosphere_source: str | None = None,
    cloud_model: str | None = None,
) -> dict:
    """Run only the PICASO reflected-light calculation for one Roadrunner system."""
    if not HAVE_PICASO:
        raise RuntimeError("PICASO is required")

    lam_grid_um = np.asarray(lam_grid_um, dtype=float)
    wave_range = [float(np.nanmin(lam_grid_um)), float(np.nanmax(lam_grid_um))]
    opa = jdi.opannection(wave_range=wave_range)

    case = jdi.inputs()
    g_cgs = 10 ** sys_params.logg_cgs
    case.gravity(
        gravity=g_cgs,
        gravity_unit=u.cm / u.s**2,
        radius=sys_params.rj,
        radius_unit=u.R_jup,
    )
    case.star(
        opa,
        temp=sys_params.tstar_k,
        metal=0,
        logg=4.44,
        radius=sys_params.rstar_rsun,
        radius_unit=u.R_sun,
        semi_major=sys_params.a_au,
        semi_major_unit=u.AU,
    )

    configure_picaso_atmosphere(
        case,
        sys_params,
        atmosphere_source=atmosphere_source,
        cloud_model=cloud_model,
        verbose=verbose,
    )

    case.phase_angle(
        np.deg2rad(sys_params.phase_deg),
        num_gangle=REFLECT_NUM_GANGLE,
        num_tangle=REFLECT_NUM_TANGLE,
    )
    return case.spectrum(
        opa,
        calculation="reflected",
        as_dict=True,
        full_output=full_output,
    )


def extract_reflected_flux_only(
    out_ref: dict,
    lam_grid_um: np.ndarray,
    sys_params: SystemParams,
) -> np.ndarray:
    """Convert Roadrunner reflected output to absolute planet flux on the requested grid."""
    wno_ref = np.asarray(out_ref["wavenumber"], dtype=float)
    lam_cm_ref = 1.0 / wno_ref
    wl_ref_um = lam_cm_ref * 1e4

    fpfs_data = out_ref.get("fpfs_reflected")
    if isinstance(fpfs_data, np.ndarray):
        fpfs_ref = fpfs_data
    else:
        albedo = np.asarray(out_ref["albedo"], dtype=float)
        rp_cm = sys_params.rj * R_jup.value
        a_cm = sys_params.a_au * au.value
        fpfs_ref = albedo * (rp_cm / a_cm) ** 2

    stellar_flux_per_cm = np.pi * np.squeeze(blackbody(sys_params.tstar_k, lam_cm_ref))
    planet_reflected_per_cm = fpfs_ref * stellar_flux_per_cm
    planet_reflected_per_um = planet_reflected_per_cm * 1e-4

    order = np.argsort(wl_ref_um)
    interpolated = np.interp(
        np.asarray(lam_grid_um, dtype=float),
        wl_ref_um[order],
        planet_reflected_per_um[order],
        left=0.0,
        right=0.0,
    )
    return np.nan_to_num(interpolated, nan=0.0, posinf=0.0, neginf=0.0)


def evaluate_hybrid_case(
    sys_params: SystemParams,
    thermal_gravity_code: str = "31",
    lam_grid_um: np.ndarray = LAM_GRID,
    thresh: float = REFLECT_THRESHOLD,
    do_plots: bool = False,
    thermal_source: str | None = None,
    atmosphere_source: str | None = None,
    cloud_model: str | None = None,
    thermal_irflux_file: str | Path | None = None,
    selected_bands=None,
) -> pd.DataFrame:
    """
    Evaluate one Roadrunner case with selectable thermal/atmosphere sources.

    ``thermal_source="egp"`` uses the matching EGP IRflux file for the thermal
    spectrum. ``thermal_source="picaso"`` runs reflected and thermal spectra
    together in PICASO. ``atmosphere_source="picaso"`` avoids SLGRID PT/cloud
    files by generating a Guillot/Visscher/cloud atmosphere in PICASO.
    """
    thermal = normalize_thermal_source(thermal_source)
    atmosphere = normalize_atmosphere_source(
        atmosphere_source or ("picaso" if thermal == "picaso" else ATMOSPHERE_SOURCE)
    )
    lam_grid_um = wavelength_grid_for_bands(selected_bands, lam_grid_um)

    if thermal == "picaso":
        out_ref, out_em = run_picaso_once(
            sys_params,
            lam_grid_um,
            atmosphere_source=atmosphere,
            cloud_model=cloud_model,
            verbose=do_plots,
        )
        _, fp_ref, fp_th = extract_planet_fluxes(
            out_ref,
            out_em,
            lam_grid_um,
            sys_params,
        )
        thermal_label = "PICASO"
    else:
        out_ref = run_picaso_reflected_only(
            sys_params,
            lam_grid_um=lam_grid_um,
            full_output=do_plots,
            verbose=do_plots,
            atmosphere_source=atmosphere,
            cloud_model=cloud_model,
        )
        fp_ref = extract_reflected_flux_only(out_ref, lam_grid_um, sys_params)
        fp_th, egp_filename = egp_thermal_on_grid(
            temperature_k=sys_params.teff_k,
            gravity_code=thermal_gravity_code,
            lam_grid_um=lam_grid_um,
            irflux_file=thermal_irflux_file,
        )
        thermal_label = f"EGP {egp_filename}"

    rows = band_metrics(
        lam_grid_um,
        fp_ref,
        fp_th,
        select_bands(selected_bands, lam_grid_um),
        thresh=thresh,
    )

    if do_plots:
        suffix = (
            f" (Teff={sys_params.teff_k}K, logg={sys_params.logg_cgs}, "
            f"a={sys_params.a_au}AU, α={sys_params.phase_deg}°, "
            f"atmosphere={atmosphere}, thermal={thermal_label})"
        )
        if thermal == "egp":
            print(f"✓ Using EGP thermal file: {egp_filename}")
        plot_spectra_with_bb(lam_grid_um, fp_ref, fp_th, sys_params, title_suffix=suffix)
        plot_band_bars(rows, title_suffix=suffix)

    records = []
    for band_name, f_reflect, fp_ref_band, fp_th_band, decision in rows:
        records.append(
            {
                "T_eff": sys_params.teff_k,
                "logg": sys_params.logg_cgs,
                "R_p_Rj": sys_params.rj,
                "a_AU": sys_params.a_au,
                "phase_deg": sys_params.phase_deg,
                "band": band_name,
                "f_reflect": float(f_reflect) if np.isfinite(f_reflect) else np.nan,
                "Fp_ref_band": float(fp_ref_band),
                "Fp_th_band": float(fp_th_band),
                "decision": bool(decision),
            }
        )

    return pd.DataFrame(records, columns=COLUMNS)


def run_hybrid_grid_parallel(
    teffs: list[int] | None = None,
    loggs: list[float] = LOGGS_CGS,
    rps: list[float] = R_PLANETS_Rj,
    as_au: list[float] = SEMI_MAJOR_AU,
    phases: list[float] = PHASE_DEG,
    lam_grid_um: np.ndarray = LAM_GRID,
    thresh: float = REFLECT_THRESHOLD,
    thermal_gravity_code: str = "31",
    max_workers: int | None = None,
    thermal_source: str | None = None,
    atmosphere_source: str | None = None,
    cloud_model: str | None = None,
    selected_bands=None,
) -> pd.DataFrame:
    """Run the full grid in parallel and return the same columns as Roadrunner."""
    thermal = normalize_thermal_source(thermal_source)
    atmosphere = normalize_atmosphere_source(
        atmosphere_source or ("picaso" if thermal == "picaso" else ATMOSPHERE_SOURCE)
    )
    if teffs is None:
        if thermal == "egp":
            if atmosphere == "slgrid":
                teffs = available_hybrid_temperatures(gravity_code=thermal_gravity_code)
            else:
                teffs = available_egp_temperatures(gravity_code=thermal_gravity_code)
        elif atmosphere == "slgrid":
            teffs = available_slgrid_teffs()
        else:
            teffs = list(TEFFS_K)
    else:
        teffs = list(teffs)

    cases = [
        SystemParams(
            teff_k,
            logg,
            rp,
            a_au,
            phase_deg,
            atmosphere_source=atmosphere,
            cloud_model=cloud_model or PICASO_CLOUD_MODEL,
        )
        for teff_k in teffs
        for logg in loggs
        for rp in rps
        for a_au in as_au
        for phase_deg in phases
    ]

    max_workers = max_workers or max(1, (os.cpu_count() or 2) - 1)
    func = partial(
        evaluate_hybrid_case,
        lam_grid_um=lam_grid_um,
        thresh=thresh,
        thermal_gravity_code=thermal_gravity_code,
        do_plots=False,
        thermal_source=thermal,
        atmosphere_source=atmosphere,
        cloud_model=cloud_model,
        selected_bands=selected_bands,
    )

    dataframes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        mapped = executor.map(func, cases)
        desc = f"Running {thermal} grid"
        for dataframe in _progress(mapped, total=len(cases), desc=desc):
            if dataframe is not None and not dataframe.empty:
                dataframes.append(dataframe)

    if not dataframes:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(dataframes, ignore_index=True)


def thermal_source_summary(gravity_code: str = "31") -> pd.DataFrame:
    """Convenience table showing which temperatures will be used in the hybrid notebook."""
    inventory = egp_inventory(gravity_code=gravity_code)
    if inventory.empty:
        return inventory

    hybrid_temps = set(available_hybrid_temperatures(gravity_code=gravity_code))
    inventory["used_in_hybrid_grid"] = inventory["temperature_k"].isin(hybrid_temps)
    return inventory
