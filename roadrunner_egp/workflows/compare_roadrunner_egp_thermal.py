from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


WORKFLOW_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORKFLOW_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results"
ROADRUNNER_PHASE0_CSV = RESULTS_DIR / "roadrunner_10percent_phase0_grid.csv"
DEFAULT_WAVE_RANGE_UM = (0.3, 15.0)
_C_CGS = 2.99792458e10
_CONFIG_COLUMNS = ["T_eff", "logg", "R_p_Rj", "a_AU", "phase_deg"]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from roadrunner import SystemParams  # noqa: E402
from roadrunner.config import EGP_IRFLUX_DIR  # noqa: E402
from roadrunner.runner import run_picaso_once  # noqa: E402


EGP_GRID_DIR = Path(EGP_IRFLUX_DIR)


def load_roadrunner_grid(csv_path: str | Path = ROADRUNNER_PHASE0_CSV) -> pd.DataFrame:
    """Load the phase-0 Roadrunner summary grid."""
    grid = pd.read_csv(csv_path)
    numeric_columns = ["T_eff", "logg", "R_p_Rj", "a_AU", "phase_deg", "f_reflect"]
    grid[numeric_columns] = grid[numeric_columns].apply(pd.to_numeric, errors="coerce")
    return grid.sort_values(_CONFIG_COLUMNS + ["band"]).reset_index(drop=True)


def unique_roadrunner_configurations(grid: pd.DataFrame) -> pd.DataFrame:
    """Drop the per-band duplicates and keep one row per physical setup."""
    return (
        grid[_CONFIG_COLUMNS]
        .drop_duplicates()
        .sort_values(_CONFIG_COLUMNS)
        .reset_index(drop=True)
    )


def gravity_code_to_logg_cgs(gravity_code: str | int | float) -> float:
    """Convert an SLGRID gravity code like ``31`` to log(g) in cgs."""
    return float(np.log10(float(gravity_code)) + 2.0)


def select_roadrunner_configuration(
    grid: pd.DataFrame,
    temperature_k: int | float,
    gravity_code: str = "31",
    logg_cgs: float | None = None,
    radius_rj: float = 1.0,
    semi_major_au: float = 5.0,
    phase_deg: float = 0.0,
) -> pd.Series:
    """
    Pick the Roadrunner configuration that best matches one temperature.

    By default, this keeps the canonical phase-0 / 1 Rj / 5 AU setup and
    chooses the Roadrunner gravity closest to the requested SLGRID gravity
    code. For ``g31`` this resolves to the Roadrunner ``logg=3.5`` case.
    """
    configs = unique_roadrunner_configurations(grid)
    subset = configs[np.isclose(configs["T_eff"], float(temperature_k))]

    if radius_rj is not None:
        subset = subset[np.isclose(subset["R_p_Rj"], float(radius_rj))]
    if semi_major_au is not None:
        subset = subset[np.isclose(subset["a_AU"], float(semi_major_au))]
    if phase_deg is not None:
        subset = subset[np.isclose(subset["phase_deg"], float(phase_deg))]

    if subset.empty:
        raise ValueError(
            "No Roadrunner configuration matched the requested filters. "
            f"temperature={temperature_k}, radius={radius_rj}, "
            f"a={semi_major_au}, phase={phase_deg}"
        )

    target_logg = float(logg_cgs) if logg_cgs is not None else gravity_code_to_logg_cgs(gravity_code)
    scored = subset.assign(logg_distance=(subset["logg"] - target_logg).abs())
    return scored.sort_values(["logg_distance", "logg"]).iloc[0].drop(labels="logg_distance")


def build_system_params(config_row: pd.Series) -> SystemParams:
    """Convert a Roadrunner config row into the SystemParams object PICASO expects."""
    return SystemParams(
        teff_k=float(config_row["T_eff"]),
        logg_cgs=float(config_row["logg"]),
        rj=float(config_row["R_p_Rj"]),
        a_au=float(config_row["a_AU"]),
        phase_deg=float(config_row["phase_deg"]),
    )


def find_egp_irflux_file(
    temperature_k: int | float,
    gravity_code: str = "31",
    egp_dir: str | Path = EGP_GRID_DIR,
) -> Path:
    """Return the matching EGP IR flux file such as ``SLGRID_T500_g31_..._IRflux.txt``."""
    pattern = f"SLGRID_T{int(round(float(temperature_k)))}_g{gravity_code}_*_IRflux.txt"
    matches = sorted(Path(egp_dir).glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No EGP IR flux file found for temperature={temperature_k} and g{gravity_code}."
        )
    return matches[0]


def flux_nu_to_lambda_per_um(
    wavelength_um: np.ndarray | pd.Series,
    flux_nu_cgs: np.ndarray | pd.Series,
) -> np.ndarray:
    """Convert F_nu [erg cm^-2 s^-1 Hz^-1] to F_lambda [erg cm^-2 s^-1 um^-1]."""
    wavelength_cm = np.asarray(wavelength_um, dtype=float) * 1e-4
    flux_nu = np.asarray(flux_nu_cgs, dtype=float)
    flux_lambda_per_cm = flux_nu * _C_CGS / wavelength_cm**2
    return flux_lambda_per_cm * 1e-4


def load_egp_irflux(
    temperature_k: int | float,
    gravity_code: str = "31",
    egp_dir: str | Path = EGP_GRID_DIR,
) -> tuple[pd.DataFrame, Path]:
    """Load one EGP thermal spectrum and convert it onto F_lambda per micron."""
    file_path = find_egp_irflux_file(temperature_k=temperature_k, gravity_code=gravity_code, egp_dir=egp_dir)

    rows = []
    with file_path.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 4 and parts[0].isdigit():
                rows.append(
                    (
                        int(parts[0]),
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                    )
                )

    if not rows:
        raise ValueError(f"Could not parse any numeric spectrum rows from {file_path}.")

    spectrum = pd.DataFrame(
        rows,
        columns=["index", "wavelength_um", "brightness_temperature_k", "flux_nu_cgs"],
    )
    spectrum["flux_lambda_per_um"] = flux_nu_to_lambda_per_um(
        spectrum["wavelength_um"],
        spectrum["flux_nu_cgs"],
    )
    spectrum = spectrum.sort_values("wavelength_um").reset_index(drop=True)
    return spectrum, file_path


def run_roadrunner_thermal_spectrum(
    config_row: pd.Series,
    wave_range_um: tuple[float, float] = DEFAULT_WAVE_RANGE_UM,
    sample_count: int = 2500,
) -> tuple[pd.DataFrame, SystemParams]:
    """Run PICASO with one Roadrunner configuration and return the thermal spectrum."""
    lam_grid_um = np.linspace(float(wave_range_um[0]), float(wave_range_um[1]), int(sample_count))
    system_params = build_system_params(config_row)
    _, out_em = run_picaso_once(
        system_params,
        lam_grid_um,
        wave_range=[float(wave_range_um[0]), float(wave_range_um[1])],
    )

    wavelength_um = 1e4 / np.asarray(out_em["wavenumber"], dtype=float)
    flux_lambda_per_um = np.asarray(out_em["thermal"], dtype=float) * 1e-4
    order = np.argsort(wavelength_um)

    spectrum = pd.DataFrame(
        {
            "wavelength_um": wavelength_um[order],
            "flux_lambda_per_um": flux_lambda_per_um[order],
        }
    )
    return spectrum.reset_index(drop=True), system_params


def build_overlap_comparison(
    roadrunner_spectrum: pd.DataFrame,
    egp_spectrum: pd.DataFrame,
    sample_count: int = 800,
) -> pd.DataFrame:
    """Interpolate both spectra onto the shared wavelength window for direct comparison."""
    overlap_min = max(
        float(roadrunner_spectrum["wavelength_um"].min()),
        float(egp_spectrum["wavelength_um"].min()),
    )
    overlap_max = min(
        float(roadrunner_spectrum["wavelength_um"].max()),
        float(egp_spectrum["wavelength_um"].max()),
    )

    if overlap_min >= overlap_max:
        raise ValueError("The Roadrunner and EGP spectra do not overlap in wavelength.")

    wavelength_um = np.geomspace(overlap_min, overlap_max, int(sample_count))
    roadrunner_interp = np.interp(
        wavelength_um,
        roadrunner_spectrum["wavelength_um"],
        roadrunner_spectrum["flux_lambda_per_um"],
    )
    egp_interp = np.interp(
        wavelength_um,
        egp_spectrum["wavelength_um"],
        egp_spectrum["flux_lambda_per_um"],
    )
    ratio = np.divide(
        roadrunner_interp,
        egp_interp,
        out=np.full_like(roadrunner_interp, np.nan),
        where=egp_interp > 0,
    )

    return pd.DataFrame(
        {
            "wavelength_um": wavelength_um,
            "roadrunner_flux_lambda_per_um": roadrunner_interp,
            "egp_flux_lambda_per_um": egp_interp,
            "roadrunner_to_egp_ratio": ratio,
        }
    )


def compare_roadrunner_to_egp(
    temperature_k: int | float,
    gravity_code: str = "31",
    logg_cgs: float | None = None,
    radius_rj: float = 1.0,
    semi_major_au: float = 5.0,
    phase_deg: float = 0.0,
    wave_range_um: tuple[float, float] = DEFAULT_WAVE_RANGE_UM,
    csv_path: str | Path = ROADRUNNER_PHASE0_CSV,
) -> dict[str, object]:
    """Run the full Roadrunner/PICASO vs EGP comparison for one temperature."""
    grid = load_roadrunner_grid(csv_path)
    config_row = select_roadrunner_configuration(
        grid,
        temperature_k=temperature_k,
        gravity_code=gravity_code,
        logg_cgs=logg_cgs,
        radius_rj=radius_rj,
        semi_major_au=semi_major_au,
        phase_deg=phase_deg,
    )
    roadrunner_spectrum, system_params = run_roadrunner_thermal_spectrum(
        config_row=config_row,
        wave_range_um=wave_range_um,
    )
    egp_spectrum, egp_file = load_egp_irflux(
        temperature_k=temperature_k,
        gravity_code=gravity_code,
    )
    overlap = build_overlap_comparison(roadrunner_spectrum, egp_spectrum)

    return {
        "temperature_k": int(round(float(temperature_k))),
        "gravity_code": gravity_code,
        "wave_range_um": wave_range_um,
        "config_row": config_row,
        "system_params": system_params,
        "roadrunner_spectrum": roadrunner_spectrum,
        "egp_spectrum": egp_spectrum,
        "egp_file": egp_file,
        "overlap": overlap,
    }


def build_summary_table(result: dict[str, object]) -> pd.DataFrame:
    """Return a compact table describing the chosen configuration and overlap window."""
    config_row = result["config_row"]
    overlap = result["overlap"]
    gravity_code = result["gravity_code"]
    egp_file = result["egp_file"]

    summary = [
        ("temperature_k", int(round(float(config_row["T_eff"])))),
        ("roadrunner_logg_cgs", float(config_row["logg"])),
        ("egp_gravity_code", gravity_code),
        ("radius_rj", float(config_row["R_p_Rj"])),
        ("semi_major_au", float(config_row["a_AU"])),
        ("phase_deg", float(config_row["phase_deg"])),
        ("egp_file", Path(egp_file).name),
        ("comparison_min_um", float(overlap["wavelength_um"].min())),
        ("comparison_max_um", float(overlap["wavelength_um"].max())),
        ("median_roadrunner_to_egp_ratio", float(np.nanmedian(overlap["roadrunner_to_egp_ratio"]))),
    ]
    return pd.DataFrame(summary, columns=["parameter", "value"])


def plot_individual_spectra(result: dict[str, object]) -> tuple[plt.Figure, np.ndarray]:
    """Plot the standalone Roadrunner/PICASO and EGP thermal spectra."""
    roadrunner_spectrum = result["roadrunner_spectrum"]
    egp_spectrum = result["egp_spectrum"]
    config_row = result["config_row"]
    temperature_k = result["temperature_k"]
    gravity_code = result["gravity_code"]

    fig, axes = plt.subplots(1, 2, figsize=(15, 5))

    axes[0].plot(
        roadrunner_spectrum["wavelength_um"],
        roadrunner_spectrum["flux_lambda_per_um"],
        color="tab:blue",
        lw=1.8,
    )
    axes[0].set_title(
        f"Roadrunner/PICASO Thermal Spectrum\nT={temperature_k} K, logg={float(config_row['logg']):.1f}",
    )

    axes[1].plot(
        egp_spectrum["wavelength_um"],
        egp_spectrum["flux_lambda_per_um"],
        color="tab:orange",
        lw=1.8,
    )
    axes[1].set_title(f"EGP IRflux Spectrum\nT={temperature_k} K, g{gravity_code}")

    for axis in axes:
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.set_xlabel("Wavelength [um]")
        axis.set_ylabel(r"Flux [erg cm$^{-2}$ s$^{-1}$ um$^{-1}$]")
        axis.grid(alpha=0.3, which="both")

    fig.tight_layout()
    return fig, axes


def plot_overlay_comparison(result: dict[str, object]) -> tuple[plt.Figure, np.ndarray]:
    """Overlay both spectra on the shared wavelength range and show their ratio."""
    overlap = result["overlap"]
    temperature_k = result["temperature_k"]
    gravity_code = result["gravity_code"]

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(10, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    axes[0].plot(
        overlap["wavelength_um"],
        overlap["roadrunner_flux_lambda_per_um"],
        label="Roadrunner/PICASO",
        color="tab:blue",
        lw=1.8,
    )
    axes[0].plot(
        overlap["wavelength_um"],
        overlap["egp_flux_lambda_per_um"],
        label=f"EGP g{gravity_code}",
        color="tab:orange",
        lw=1.8,
    )
    axes[0].set_yscale("log")
    axes[0].set_xscale("log")
    axes[0].set_ylabel(r"Flux [erg cm$^{-2}$ s$^{-1}$ um$^{-1}$]")
    axes[0].set_title(f"Roadrunner/PICASO vs EGP Thermal Comparison\nT={temperature_k} K")
    axes[0].legend()
    axes[0].grid(alpha=0.3, which="both")

    axes[1].plot(
        overlap["wavelength_um"],
        overlap["roadrunner_to_egp_ratio"],
        color="tab:green",
        lw=1.6,
    )
    axes[1].axhline(1.0, color="black", ls="--", lw=1)
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Wavelength [um]")
    axes[1].set_ylabel("RR / EGP")
    axes[1].grid(alpha=0.3, which="both")

    fig.tight_layout()
    return fig, axes
