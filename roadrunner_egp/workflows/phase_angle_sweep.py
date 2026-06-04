from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


WORKFLOW_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORKFLOW_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from roadrunner.bands import BANDS, band_metrics  # noqa: E402
from roadrunner.config import (  # noqa: E402
    CGI_BANDS,
    HAVE_PICASO,
    LAM_GRID,
    REFLECT_THRESHOLD,
    SLGRID_CLD_DIR,
    SLGRID_PT_DIR,
)
from roadrunner.runner import extract_planet_fluxes, run_picaso_once  # noqa: E402
from roadrunner.system import SystemParams  # noqa: E402


def _pair_key(filename: str) -> str:
    if filename.endswith("_full.pt"):
        return filename[: -len("_full.pt")]
    if filename.endswith("_picaso.cld"):
        return filename[: -len("_picaso.cld")]
    return filename


def resolve_egp_pt_cld_pair(
    temperature_k: int | float,
    gravity_code: str = "31",
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str = "3",
    frac: str | int | None = None,
) -> tuple[str, str]:
    """
    Resolve one matching SLGRID PT/cloud pair for PICASO input.

    The lookup first tries the exact naming convention requested by the
    notebook config, then falls back to the first matching shared pair if
    only a partial family exists on disk.
    """
    teff = int(round(float(temperature_k)))
    frac_token = None if frac is None else str(frac)
    prefix = (
        f"SLGRID_T{teff}_g{gravity_code}_m{metallicity}_CO{co_ratio}_fsed{fsed}"
    )

    pt_dir = Path(SLGRID_PT_DIR)
    cld_dir = Path(SLGRID_CLD_DIR)

    preferred_pairs: list[tuple[str, str]] = []
    if frac_token is not None:
        preferred_pairs.append(
            (
                f"{prefix}_frac{frac_token}_full.pt",
                f"{prefix}_frac{frac_token}_picaso.cld",
            )
        )

    preferred_pairs.append((f"{prefix}_full.pt", f"{prefix}_picaso.cld"))

    if frac_token is None:
        for candidate_frac in ("50", "25", "75", "10"):
            preferred_pairs.append(
                (
                    f"{prefix}_frac{candidate_frac}_full.pt",
                    f"{prefix}_frac{candidate_frac}_picaso.cld",
                )
            )

    for pt_name, cld_name in preferred_pairs:
        if (pt_dir / pt_name).exists() and (cld_dir / cld_name).exists():
            return pt_name, cld_name

    pt_matches = {
        _pair_key(path.name): path.name
        for path in sorted(pt_dir.glob(f"{prefix}*_full.pt"))
    }
    cld_matches = {
        _pair_key(path.name): path.name
        for path in sorted(cld_dir.glob(f"{prefix}*_picaso.cld"))
    }
    shared = sorted(set(pt_matches) & set(cld_matches))

    if not shared:
        raise FileNotFoundError(
            "Could not find a matching PT/cloud pair for "
            f"T={teff} K, g{gravity_code}, m={metallicity}, CO={co_ratio}, "
            f"fsed={fsed}, frac={frac_token}."
        )

    key = shared[0]
    return pt_matches[key], cld_matches[key]


def run_phase_angle_sweep(
    *,
    teff_k: float,
    logg_cgs: float,
    rj: float,
    a_au: float,
    phases: list[float] | tuple[float, ...],
    pt_file: str,
    cld_file: str,
    lam_grid_um: np.ndarray = LAM_GRID,
    thresh: float = REFLECT_THRESHOLD,
) -> pd.DataFrame:
    """Run PICASO for a fixed system while sweeping only the phase angle."""
    if not HAVE_PICASO:
        raise RuntimeError("PICASO is required for the phase-angle sweep.")

    records: list[dict[str, float | str | bool]] = []
    for phase_deg in phases:
        system = SystemParams(
            teff_k=float(teff_k),
            logg_cgs=float(logg_cgs),
            rj=float(rj),
            a_au=float(a_au),
            phase_deg=float(phase_deg),
            pt_file=pt_file,
            cld_file=cld_file,
        )
        out_ref, out_em = run_picaso_once(system, lam_grid_um)
        lam_um, fp_ref, fp_th = extract_planet_fluxes(
            out_ref,
            out_em,
            lam_grid_um,
            system,
        )

        rows = band_metrics(lam_um, fp_ref, fp_th, BANDS, thresh=thresh)
        for band_name, f_reflect, fp_ref_band, fp_th_band, decision in rows:
            records.append(
                {
                    "T_eff": float(teff_k),
                    "logg": float(logg_cgs),
                    "R_p_Rj": float(rj),
                    "a_AU": float(a_au),
                    "phase_deg": float(phase_deg),
                    "band": band_name,
                    "f_reflect": float(f_reflect),
                    "Fp_ref_band": float(fp_ref_band),
                    "Fp_th_band": float(fp_th_band),
                    "decision": bool(decision),
                    "pt_file": pt_file,
                    "cld_file": cld_file,
                }
            )

    dataframe = pd.DataFrame(records)
    if dataframe.empty:
        return dataframe

    return dataframe.sort_values(["phase_deg", "band"]).reset_index(drop=True)


def phase_sweep_pivot(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return a compact phase-by-band reflected-fraction table."""
    pivot = (
        dataframe.pivot(index="phase_deg", columns="band", values="f_reflect")
        .sort_index()
        .reset_index()
    )
    pivot.columns.name = None
    return pivot


def plot_phase_angle_sweep(
    dataframe: pd.DataFrame,
    *,
    threshold: float = REFLECT_THRESHOLD,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """Create the required phase-angle line plot with one line per CGI band."""
    if dataframe.empty:
        raise ValueError("No phase-sweep data available to plot.")

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5.5))

    colors = {
        "CGI-1": "#1f77b4",
        "CGI-2": "#2ca02c",
        "CGI-3": "#ff7f0e",
        "CGI-4": "#d62728",
    }

    for band_name in CGI_BANDS:
        band_df = dataframe[dataframe["band"] == band_name].sort_values("phase_deg")
        ax.plot(
            band_df["phase_deg"],
            band_df["f_reflect"],
            marker="o",
            linewidth=2,
            markersize=6,
            color=colors.get(band_name),
            label=band_name,
        )

    ax.axhline(
        threshold,
        linestyle="--",
        linewidth=1.5,
        color="black",
        alpha=0.7,
        label=f"{threshold:.0%} threshold",
    )
    ax.set_xlabel("Phase angle (degrees)")
    ax.set_ylabel("Reflected fraction")
    ax.set_title("Reflected Fraction vs Phase Angle")
    ax.set_xlim(float(dataframe["phase_deg"].min()), float(dataframe["phase_deg"].max()))
    ax.set_ylim(bottom=0.0)
    ax.grid(alpha=0.3)
    ax.legend()
    return ax
