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

from roadrunner.config import (  # noqa: E402
    CGI_BANDS,
    EGP_IRFLUX_DIR,
    HAVE_PICASO,
    LAM_GRID,
    REFLECT_THRESHOLD,
    SLGRID_CLD_DIR,
    SLGRID_PT_DIR,
)
from roadrunner.system import SystemParams  # noqa: E402
from workflows.hybrid_reflected_picaso_thermal_egp import (  # noqa: E402
    evaluate_hybrid_case,
)


def _gravity_code_token(gravity_code: str | int | float) -> str:
    """Return an SLGRID gravity token such as ``31`` from ``g31`` or ``31``."""
    token = str(gravity_code).strip().lower()
    if token.startswith("g"):
        token = token[1:]
    if not token:
        raise ValueError("Gravity code cannot be empty.")
    return token


def gravity_code_to_logg_cgs(gravity_code: str | int | float) -> float:
    """Convert an SLGRID gravity code like ``31`` to log(g) in cgs."""
    return float(np.log10(float(_gravity_code_token(gravity_code))) + 2.0)


def _pair_key(filename: str) -> str:
    if filename.endswith("_full.pt"):
        return filename[: -len("_full.pt")]
    if filename.endswith("_picaso.cld"):
        return filename[: -len("_picaso.cld")]
    return filename


def resolve_egp_pt_cld_pair(
    temperature_k: int | float,
    gravity_code: str | int | float = "31",
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str = "3",
    frac: str | int | None = None,
) -> tuple[str, str]:
    """
    Resolve one matching SLGRID PT/cloud pair for PICASO reflected light.

    The lookup mirrors ``phase_angle_sweep.resolve_egp_pt_cld_pair`` but lets
    the swept variable be the EGP gravity code instead of phase angle.
    """
    teff = int(round(float(temperature_k)))
    gravity = _gravity_code_token(gravity_code)
    frac_token = None if frac is None else str(frac)
    prefix = f"SLGRID_T{teff}_g{gravity}_m{metallicity}_CO{co_ratio}_fsed{fsed}"

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
            f"T={teff} K, g{gravity}, m={metallicity}, CO={co_ratio}, "
            f"fsed={fsed}, frac={frac_token}."
        )

    key = shared[0]
    return pt_matches[key], cld_matches[key]


def resolve_egp_irflux_file(
    temperature_k: int | float,
    gravity_code: str | int | float = "31",
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str = "3",
    egp_dir: str | Path = EGP_IRFLUX_DIR,
) -> Path:
    """Return the exact matching EGP IRflux file path for one gravity code."""
    teff = int(round(float(temperature_k)))
    gravity = _gravity_code_token(gravity_code)
    filename = f"SLGRID_T{teff}_g{gravity}_m{metallicity}_CO{co_ratio}_fsed{fsed}_IRflux.txt"
    exact_path = Path(egp_dir) / filename
    if exact_path.exists():
        return exact_path

    matches = sorted(
        Path(egp_dir).glob(
            f"SLGRID_T{teff}_g{gravity}_m{metallicity}_CO{co_ratio}_fsed{fsed}*_IRflux.txt"
        )
    )
    if matches:
        return matches[0]

    raise FileNotFoundError(
        "Could not find an EGP IRflux file for "
        f"T={teff} K, g{gravity}, m={metallicity}, CO={co_ratio}, fsed={fsed}."
    )


def phase60_gravity_file_inventory(
    *,
    temperature_k: int | float,
    gravity_codes: list[str | int | float] | tuple[str | int | float, ...],
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str = "3",
    frac: str | int | None = None,
) -> pd.DataFrame:
    """Return the exact PT/cloud/IRflux files that will be used for each code."""
    records = []
    for gravity_code in gravity_codes:
        gravity = _gravity_code_token(gravity_code)
        pt_file, cld_file = resolve_egp_pt_cld_pair(
            temperature_k=temperature_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=fsed,
            frac=frac,
        )
        irflux_file = resolve_egp_irflux_file(
            temperature_k=temperature_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=fsed,
        )
        records.append(
            {
                "gravity_code": gravity,
                "logg": gravity_code_to_logg_cgs(gravity),
                "pt_file": pt_file,
                "pt_exists": (Path(SLGRID_PT_DIR) / pt_file).exists(),
                "cld_file": cld_file,
                "cld_exists": (Path(SLGRID_CLD_DIR) / cld_file).exists(),
                "egp_irflux_file": irflux_file.name,
                "egp_irflux_exists": irflux_file.exists(),
            }
        )
    return pd.DataFrame(records)


def run_phase60_gravity_sweep(
    *,
    teff_k: float,
    rj: float,
    a_au: float,
    gravity_codes: list[str | int | float] | tuple[str | int | float, ...],
    phase_deg: float = 60.0,
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str = "3",
    frac: str | int | None = None,
    lam_grid_um: np.ndarray = LAM_GRID,
    thresh: float = REFLECT_THRESHOLD,
) -> pd.DataFrame:
    """Run a fixed phase-60 EGP thermal sweep over SLGRID gravity codes."""
    if not HAVE_PICASO:
        raise RuntimeError("PICASO is required for the phase-60 gravity sweep.")

    dataframes: list[pd.DataFrame] = []
    for gravity_code in gravity_codes:
        gravity = _gravity_code_token(gravity_code)
        pt_file, cld_file = resolve_egp_pt_cld_pair(
            temperature_k=teff_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=fsed,
            frac=frac,
        )
        egp_irflux_file = resolve_egp_irflux_file(
            temperature_k=teff_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=fsed,
        )
        system = SystemParams(
            teff_k=float(teff_k),
            logg_cgs=gravity_code_to_logg_cgs(gravity),
            rj=float(rj),
            a_au=float(a_au),
            phase_deg=float(phase_deg),
            pt_file=pt_file,
            cld_file=cld_file,
            atmosphere_source="slgrid",
        )
        dataframe = evaluate_hybrid_case(
            system,
            thermal_gravity_code=gravity,
            lam_grid_um=lam_grid_um,
            thresh=thresh,
            thermal_source="egp",
            atmosphere_source="slgrid",
        )
        if dataframe is None or dataframe.empty:
            continue
        dataframe = dataframe.copy()
        dataframe["gravity_code"] = gravity
        dataframe["pt_file"] = pt_file
        dataframe["cld_file"] = cld_file
        dataframe["egp_irflux_file"] = egp_irflux_file.name
        dataframes.append(dataframe)

    if not dataframes:
        return pd.DataFrame()

    return (
        pd.concat(dataframes, ignore_index=True)
        .sort_values(["logg", "band"])
        .reset_index(drop=True)
    )


def gravity_sweep_pivot(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return a compact gravity-by-band reflected-fraction table."""
    pivot = (
        dataframe.pivot(index="gravity_code", columns="band", values="f_reflect")
        .reset_index()
    )
    pivot["logg"] = pivot["gravity_code"].map(gravity_code_to_logg_cgs)
    pivot = pivot.sort_values("logg").reset_index(drop=True)
    first_columns = ["gravity_code", "logg"]
    band_columns = [column for column in pivot.columns if column not in first_columns]
    pivot = pivot[first_columns + band_columns]
    pivot.columns.name = None
    return pivot


def plot_phase60_gravity_sweep(
    dataframe: pd.DataFrame,
    *,
    threshold: float = REFLECT_THRESHOLD,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """Create a phase-60 reflected-fraction plot with one line per CGI band."""
    if dataframe.empty:
        raise ValueError("No gravity-sweep data available to plot.")

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5.5))

    colors = {
        "CGI-1": "#1f77b4",
        "CGI-2": "#2ca02c",
        "CGI-3": "#ff7f0e",
        "CGI-4": "#d62728",
    }
    plot_df = dataframe.copy()
    plot_df["logg_for_plot"] = plot_df["gravity_code"].map(gravity_code_to_logg_cgs)

    for band_name in CGI_BANDS:
        band_df = plot_df[plot_df["band"] == band_name].sort_values("logg_for_plot")
        ax.plot(
            band_df["logg_for_plot"],
            band_df["f_reflect"],
            marker="o",
            linewidth=2,
            markersize=6,
            color=colors.get(band_name),
            label=band_name,
        )

    code_labels = (
        plot_df[["gravity_code", "logg_for_plot"]]
        .drop_duplicates()
        .sort_values("logg_for_plot")
    )
    ax.set_xticks(code_labels["logg_for_plot"])
    ax.set_xticklabels([f"g{code}" for code in code_labels["gravity_code"]])
    ax.axhline(
        threshold,
        linestyle="--",
        linewidth=1.5,
        color="black",
        alpha=0.7,
        label=f"{threshold:.0%} threshold",
    )
    ax.set_xlabel("EGP gravity code")
    ax.set_ylabel("Reflected fraction")
    ax.set_title("Phase 60 Reflected Fraction vs EGP Gravity")
    ax.set_ylim(bottom=0.0)
    ax.grid(alpha=0.3)
    ax.legend()
    return ax
