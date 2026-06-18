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


def _fsed_token(fsed: str | int | float) -> str:
    token = str(fsed).strip()
    if not token:
        raise ValueError("fsed cannot be empty.")
    if token.lower() in {"nc", "0", "0.0", "cloud_free", "cloud-free", "cloudfree"}:
        return "NC"
    if "frac" in token.lower():
        raise ValueError("This sweep only accepts non-frac fsed values.")
    return token


def _fsed_numeric(fsed: str | int | float) -> float:
    token = _fsed_token(fsed)
    if token == "NC":
        return 0.0
    return float(token)


def _non_frac_names(
    temperature_k: int | float,
    gravity_code: str | int | float,
    metallicity: str,
    co_ratio: str,
    fsed: str | int | float,
) -> tuple[str, str, str]:
    teff = int(round(float(temperature_k)))
    gravity = _gravity_code_token(gravity_code)
    fsed_value = _fsed_token(fsed)
    prefix = f"SLGRID_T{teff}_g{gravity}_m{metallicity}_CO{co_ratio}"
    if fsed_value == "NC":
        return (
            f"{prefix}_NC_full.pt",
            None,
            f"{prefix}_NC_IRflux.txt",
        )
    prefix = f"{prefix}_fsed{fsed_value}"
    return (
        f"{prefix}_full.pt",
        f"{prefix}_picaso.cld",
        f"{prefix}_IRflux.txt",
    )


def resolve_non_frac_pt_cld_pair(
    temperature_k: int | float,
    gravity_code: str | int | float = "31",
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str | int | float = "3",
) -> tuple[str, str | None]:
    """Resolve the exact non-frac SLGRID PT/cloud pair for Route C."""
    pt_file, cld_file, _ = _non_frac_names(
        temperature_k=temperature_k,
        gravity_code=gravity_code,
        metallicity=metallicity,
        co_ratio=co_ratio,
        fsed=fsed,
    )
    pt_path = Path(SLGRID_PT_DIR) / pt_file
    cld_path = None if cld_file is None else Path(SLGRID_CLD_DIR) / cld_file
    if pt_path.exists() and (cld_path is None or cld_path.exists()):
        return pt_file, cld_file

    missing = []
    if not pt_path.exists():
        missing.append(str(pt_path))
    if cld_path is not None and not cld_path.exists():
        missing.append(str(cld_path))
    raise FileNotFoundError(
        "Missing exact non-frac SLGRID Route C file(s): " + ", ".join(missing)
    )


def resolve_non_frac_irflux_file(
    temperature_k: int | float,
    gravity_code: str | int | float = "31",
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str | int | float = "3",
    egp_dir: str | Path = EGP_IRFLUX_DIR,
) -> Path:
    """Resolve the exact non-frac EGP IRflux file."""
    _, _, irflux_file = _non_frac_names(
        temperature_k=temperature_k,
        gravity_code=gravity_code,
        metallicity=metallicity,
        co_ratio=co_ratio,
        fsed=fsed,
    )
    irflux_path = Path(egp_dir) / irflux_file
    if irflux_path.exists():
        return irflux_path
    raise FileNotFoundError(f"Missing exact non-frac EGP IRflux file: {irflux_path}")


def phase60_fsed_file_inventory(
    *,
    temperature_k: int | float,
    gravity_code: str | int | float = "31",
    fsed_values: list[str | int | float] | tuple[str | int | float, ...] = ("NC", "0.3", "1", "3", "6", "8"),
    atmosphere_fsed: str | int | float | None = None,
    metallicity: str = "+000",
    co_ratio: str = "100",
) -> pd.DataFrame:
    """Return the exact non-frac PT/cloud/IRflux files expected for each fsed.

    When ``atmosphere_fsed`` is provided, the EGP IRflux is swept over
    ``fsed_values`` while the PICASO atmosphere uses that one fixed non-frac
    SLGRID PT/cloud pair. This is useful for T500, where the local EGP thermal
    files cover the non-frac fsed sequence but SLGRID PT/cloud files do not.
    """
    records = []
    gravity = _gravity_code_token(gravity_code)
    fixed_atmosphere_fsed = None if atmosphere_fsed is None else _fsed_token(atmosphere_fsed)
    for fsed in fsed_values:
        fsed_value = _fsed_token(fsed)
        pt_file, cld_file, irflux_file = _non_frac_names(
            temperature_k=temperature_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=fsed_value,
        )
        pt_path = Path(SLGRID_PT_DIR) / pt_file
        cld_path = None if cld_file is None else Path(SLGRID_CLD_DIR) / cld_file
        irflux_path = Path(EGP_IRFLUX_DIR) / irflux_file
        atmosphere_value = fixed_atmosphere_fsed or fsed_value
        selected_pt_file, selected_cld_file, _ = _non_frac_names(
            temperature_k=temperature_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=atmosphere_value,
        )
        selected_pt_path = Path(SLGRID_PT_DIR) / selected_pt_file
        selected_cld_path = None if selected_cld_file is None else Path(SLGRID_CLD_DIR) / selected_cld_file
        selected_atmosphere_exists = selected_pt_path.exists() and (
            selected_cld_path is None or selected_cld_path.exists()
        )
        teff = int(round(float(temperature_k)))
        base_prefix = f"SLGRID_T{teff}_g{gravity}_m{metallicity}_CO{co_ratio}"
        if fsed_value == "NC":
            prefix = f"{base_prefix}_NC"
            related_cld_files = []
        else:
            prefix = f"{base_prefix}_fsed{fsed_value}"
            related_cld_files = sorted(path.name for path in Path(SLGRID_CLD_DIR).glob(f"{prefix}*_picaso.cld"))
        related_pt_files = sorted(path.name for path in Path(SLGRID_PT_DIR).glob(f"{prefix}*_full.pt"))
        records.append(
            {
                "fsed": fsed_value,
                "fsed_numeric": _fsed_numeric(fsed_value),
                "gravity_code": gravity,
                "logg": gravity_code_to_logg_cgs(gravity),
                "pt_file": pt_file,
                "pt_path": str(pt_path),
                "pt_exists": pt_path.exists(),
                "cld_file": cld_file or "none",
                "cld_path": "" if cld_path is None else str(cld_path),
                "cld_exists": True if cld_path is None else cld_path.exists(),
                "matching_atmosphere_exists": pt_path.exists() and (cld_path is None or cld_path.exists()),
                "atmosphere_fsed": atmosphere_value,
                "selected_pt_file": selected_pt_file,
                "selected_pt_path": str(selected_pt_path),
                "selected_pt_exists": selected_pt_path.exists(),
                "selected_cld_file": selected_cld_file or "none",
                "selected_cld_path": "" if selected_cld_path is None else str(selected_cld_path),
                "selected_cld_exists": True if selected_cld_path is None else selected_cld_path.exists(),
                "selected_atmosphere_exists": selected_atmosphere_exists,
                "egp_irflux_file": irflux_file,
                "egp_irflux_path": str(irflux_path),
                "egp_irflux_exists": irflux_path.exists(),
                "ready": selected_atmosphere_exists and irflux_path.exists(),
                "related_pt_files": ", ".join(related_pt_files),
                "related_cld_files": ", ".join(related_cld_files),
            }
        )
    return pd.DataFrame(records).sort_values("fsed_numeric").reset_index(drop=True)


def run_phase60_fsed_sweep(
    *,
    teff_k: float,
    rj: float,
    a_au: float,
    gravity_code: str | int | float = "31",
    fsed_values: list[str | int | float] | tuple[str | int | float, ...] = ("NC", "0.3", "1", "3", "6", "8"),
    atmosphere_fsed: str | int | float | None = None,
    phase_deg: float = 60.0,
    metallicity: str = "+000",
    co_ratio: str = "100",
    lam_grid_um: np.ndarray = LAM_GRID,
    thresh: float = REFLECT_THRESHOLD,
) -> pd.DataFrame:
    """Run a fixed phase-60 Route C sweep over non-frac EGP fsed values."""
    if not HAVE_PICASO:
        raise RuntimeError("PICASO is required for the phase-60 fsed sweep.")

    gravity = _gravity_code_token(gravity_code)
    fixed_atmosphere_fsed = None if atmosphere_fsed is None else _fsed_token(atmosphere_fsed)
    dataframes: list[pd.DataFrame] = []
    for fsed in fsed_values:
        fsed_value = _fsed_token(fsed)
        atmosphere_value = fixed_atmosphere_fsed or fsed_value
        pt_file, cld_file = resolve_non_frac_pt_cld_pair(
            temperature_k=teff_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=atmosphere_value,
        )
        egp_irflux_file = resolve_non_frac_irflux_file(
            temperature_k=teff_k,
            gravity_code=gravity,
            metallicity=metallicity,
            co_ratio=co_ratio,
            fsed=fsed_value,
        )
        system = SystemParams(
            teff_k=float(teff_k),
            logg_cgs=gravity_code_to_logg_cgs(gravity),
            rj=float(rj),
            a_au=float(a_au),
            phase_deg=float(phase_deg),
            pt_file=pt_file,
            cld_file=cld_file or "nc",
            atmosphere_source="slgrid",
        )
        dataframe = evaluate_hybrid_case(
            system,
            thermal_gravity_code=gravity,
            lam_grid_um=lam_grid_um,
            thresh=thresh,
            thermal_source="egp",
            atmosphere_source="slgrid",
            thermal_irflux_file=egp_irflux_file,
        )
        if dataframe is None or dataframe.empty:
            continue
        dataframe = dataframe.copy()
        dataframe["gravity_code"] = gravity
        dataframe["fsed"] = fsed_value
        dataframe["fsed_numeric"] = _fsed_numeric(fsed_value)
        dataframe["atmosphere_fsed"] = atmosphere_value
        dataframe["pt_file"] = pt_file
        dataframe["cld_file"] = cld_file or "none"
        dataframe["egp_irflux_file"] = egp_irflux_file.name
        dataframes.append(dataframe)

    if not dataframes:
        return pd.DataFrame()

    return (
        pd.concat(dataframes, ignore_index=True)
        .sort_values(["fsed_numeric", "band"])
        .reset_index(drop=True)
    )


def fsed_sweep_pivot(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return a compact fsed-by-band reflected-fraction table."""
    pivot = (
        dataframe.pivot(index="fsed", columns="band", values="f_reflect")
        .reset_index()
    )
    pivot["fsed_numeric"] = pivot["fsed"].map(_fsed_numeric)
    pivot = pivot.sort_values("fsed_numeric").reset_index(drop=True)
    first_columns = ["fsed", "fsed_numeric"]
    band_columns = [column for column in pivot.columns if column not in first_columns]
    pivot = pivot[first_columns + band_columns]
    pivot.columns.name = None
    return pivot


def plot_phase60_fsed_sweep(
    dataframe: pd.DataFrame,
    *,
    threshold: float = REFLECT_THRESHOLD,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """Create a phase-60 reflected-fraction plot with one line per CGI band."""
    if dataframe.empty:
        raise ValueError("No fsed-sweep data available to plot.")

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5.5))

    colors = {
        "CGI-1": "#1f77b4",
        "CGI-2": "#2ca02c",
        "CGI-3": "#ff7f0e",
        "CGI-4": "#d62728",
    }
    plot_df = dataframe.copy()
    plot_df["fsed_numeric"] = plot_df["fsed"].map(_fsed_numeric)

    for band_name in CGI_BANDS:
        band_df = plot_df[plot_df["band"] == band_name].sort_values("fsed_numeric")
        ax.plot(
            band_df["fsed_numeric"],
            band_df["f_reflect"],
            marker="o",
            linewidth=2,
            markersize=6,
            color=colors.get(band_name),
            label=band_name,
        )

    fsed_labels = (
        plot_df[["fsed", "fsed_numeric"]]
        .drop_duplicates()
        .sort_values("fsed_numeric")
    )
    ax.set_xticks(fsed_labels["fsed_numeric"])
    ax.set_xticklabels(["NC" if fsed == "NC" else f"fsed{fsed}" for fsed in fsed_labels["fsed"]])
    ax.axhline(
        threshold,
        linestyle="--",
        linewidth=1.5,
        color="black",
        alpha=0.7,
        label=f"{threshold:.0%} threshold",
    )
    ax.set_xlabel("Non-frac EGP fsed")
    ax.set_ylabel("Reflected fraction")
    ax.set_title("Phase 60 Reflected Fraction vs Non-Frac EGP Fsed")
    ax.set_ylim(bottom=0.0)
    ax.grid(alpha=0.3)
    ax.legend()
    return ax
