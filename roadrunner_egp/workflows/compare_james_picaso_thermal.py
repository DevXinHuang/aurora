from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import astropy.units as u
import numpy as np
import pandas as pd


WORKFLOW_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORKFLOW_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from roadrunner.bands import BANDS  # noqa: E402
from roadrunner.config import (  # noqa: E402
    HAVE_PICASO,
    LAM_GRID,
    REFLECT_THRESHOLD,
    SLGRID_CLD_DIR,
    SLGRID_PT_DIR,
    jdi,
)
from roadrunner.physics import trapz_band  # noqa: E402


RESULTS_DIR = PROJECT_ROOT / "results"
CURRENT_HYBRID_CSV = RESULTS_DIR / "roadrunner_egp_g31_phase60_grid.csv"
DEFAULT_OUTPUT_CSV = RESULTS_DIR / "james_picaso_g31_phase60_comparison.csv"


def gravity_code_to_logg_cgs(gravity_code: str | int | float) -> float:
    """Convert an SLGRID code like ``31`` to log10(cm s-2)."""
    return float(np.log10(float(gravity_code)) + 2.0)


def gravity_code_to_cgs(gravity_code: str | int | float) -> float:
    """Convert an SLGRID code like ``31`` to cm s-2 for PICASO."""
    return float(gravity_code) * 100.0


def _pair_key(filename: str) -> str:
    if filename.endswith("_full.pt"):
        return filename[: -len("_full.pt")]
    if filename.endswith("_picaso.cld"):
        return filename[: -len("_picaso.cld")]
    return filename


def resolve_james_pt_cld_pair(
    temperature_k: int | float,
    gravity_code: str = "31",
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str = "3",
    frac: str | int | None = None,
) -> tuple[Path, Path]:
    """
    Resolve the EGP/SLGRID PT + PICASO cloud pair used by James-style thermal runs.

    This intentionally fixes the thermal gravity family with ``gravity_code`` so a
    g31 hybrid comparison uses g31 thermal files for every Roadrunner row.
    """
    teff = int(round(float(temperature_k)))
    frac_token = None if frac is None else str(frac)
    prefix = f"SLGRID_T{teff}_g{gravity_code}_m{metallicity}_CO{co_ratio}_fsed{fsed}"

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
        pt_path = pt_dir / pt_name
        cld_path = cld_dir / cld_name
        if pt_path.exists() and cld_path.exists():
            return pt_path, cld_path

    pt_matches = {
        _pair_key(path.name): path
        for path in sorted(pt_dir.glob(f"{prefix}*_full.pt"))
    }
    cld_matches = {
        _pair_key(path.name): path
        for path in sorted(cld_dir.glob(f"{prefix}*_picaso.cld"))
    }
    shared = sorted(set(pt_matches) & set(cld_matches))
    if not shared:
        raise FileNotFoundError(
            "Could not find a James-style PT/cloud pair for "
            f"T={teff} K, g{gravity_code}, m={metallicity}, CO={co_ratio}, "
            f"fsed={fsed}, frac={frac_token}."
        )

    key = shared[0]
    return pt_matches[key], cld_matches[key]


def _load_cloud_dataframe(cld_path: Path) -> pd.DataFrame:
    cloud = pd.read_csv(cld_path, sep=r"\s+")
    cloud.columns = [column.lower() for column in cloud.columns]
    return cloud


@lru_cache(maxsize=None)
def _james_thermal_native_cached(
    temperature_k: int,
    gravity_code: str,
    wave_min_um: float,
    wave_max_um: float,
    metallicity: str,
    co_ratio: str,
    fsed: str,
    frac: str | None,
) -> tuple[np.ndarray, np.ndarray, str, str]:
    if not HAVE_PICASO:
        raise RuntimeError("PICASO is required for the James-style thermal run.")

    pt_path, cld_path = resolve_james_pt_cld_pair(
        temperature_k=temperature_k,
        gravity_code=gravity_code,
        metallicity=metallicity,
        co_ratio=co_ratio,
        fsed=fsed,
        frac=frac,
    )

    opacity = jdi.opannection(wave_range=[float(wave_min_um), float(wave_max_um)])
    case = jdi.inputs(calculation="browndwarf")
    case.phase_angle(0)
    case.gravity(
        gravity=gravity_code_to_cgs(gravity_code),
        gravity_unit=u.Unit("cm/(s**2)"),
    )
    case.atmosphere(filename=str(pt_path), sep=r"\s+")
    case.clouds(df=_load_cloud_dataframe(cld_path))

    output = case.spectrum(opacity, full_output=False, calculation="thermal")
    wavelength_um = 1e4 / np.asarray(output["wavenumber"], dtype=float)
    flux_lambda_per_um = np.asarray(output["thermal"], dtype=float) * 1e-4
    order = np.argsort(wavelength_um)

    return (
        wavelength_um[order],
        flux_lambda_per_um[order],
        pt_path.name,
        cld_path.name,
    )


def james_thermal_on_grid(
    temperature_k: int | float,
    gravity_code: str = "31",
    lam_grid_um: np.ndarray = LAM_GRID,
    metallicity: str = "+000",
    co_ratio: str = "100",
    fsed: str = "3",
    frac: str | int | None = None,
) -> tuple[np.ndarray, dict[str, object]]:
    """Run James-style PICASO thermal and interpolate it to the Roadrunner grid."""
    lam_grid_um = np.asarray(lam_grid_um, dtype=float)
    frac_token = None if frac is None else str(frac)
    wavelength_um, flux_lambda_per_um, pt_file, cld_file = _james_thermal_native_cached(
        int(round(float(temperature_k))),
        str(gravity_code),
        float(np.nanmin(lam_grid_um)),
        float(np.nanmax(lam_grid_um)),
        metallicity,
        co_ratio,
        fsed,
        frac_token,
    )
    interpolated = np.interp(
        lam_grid_um,
        wavelength_um,
        flux_lambda_per_um,
        left=0.0,
        right=0.0,
    )
    meta = {
        "temperature_k": int(round(float(temperature_k))),
        "thermal_gravity_code": str(gravity_code),
        "thermal_logg_cgs": gravity_code_to_logg_cgs(gravity_code),
        "thermal_pt_file": pt_file,
        "thermal_cld_file": cld_file,
    }
    return np.nan_to_num(interpolated, nan=0.0, posinf=0.0, neginf=0.0), meta


def james_thermal_band_table(
    teffs: list[int] | np.ndarray,
    gravity_code: str = "31",
    lam_grid_um: np.ndarray = LAM_GRID,
) -> pd.DataFrame:
    """Compute James-style thermal band integrals for each requested temperature."""
    records: list[dict[str, object]] = []
    for teff in sorted({int(round(float(value))) for value in teffs}):
        thermal, meta = james_thermal_on_grid(
            temperature_k=teff,
            gravity_code=gravity_code,
            lam_grid_um=lam_grid_um,
        )
        for band_name, bandpass in BANDS.items():
            records.append(
                {
                    "T_eff_key": teff,
                    "band": band_name,
                    "Fp_th_band_james_picaso": float(
                        trapz_band(lam_grid_um, thermal, bandpass)
                    ),
                    **meta,
                }
            )
    return pd.DataFrame(records)


def load_current_hybrid(csv_path: str | Path = CURRENT_HYBRID_CSV) -> pd.DataFrame:
    """Load the existing Roadrunner phase-60 EGP-IRflux hybrid grid."""
    current = pd.read_csv(csv_path)
    current = current.copy()
    current["T_eff_key"] = current["T_eff"].round().astype(int)
    return current


def compare_with_roadrunner_hybrid(
    current_csv: str | Path = CURRENT_HYBRID_CSV,
    output_csv: str | Path | None = DEFAULT_OUTPUT_CSV,
    gravity_code: str = "31",
    teffs: list[int] | None = None,
    thresh: float = REFLECT_THRESHOLD,
) -> pd.DataFrame:
    """
    Compare current hybrid thermal bands with James-style PICASO thermal bands.

    The existing phase-60 reflected band flux is reused so the comparison isolates
    the thermal-source difference: EGP IRflux text file vs PICASO PT+cloud thermal.
    """
    current = load_current_hybrid(current_csv)
    if teffs is None:
        teffs = sorted(current["T_eff_key"].unique().tolist())

    james_thermal = james_thermal_band_table(teffs, gravity_code=gravity_code)
    comparison = current.merge(
        james_thermal,
        on=["T_eff_key", "band"],
        how="inner",
        validate="many_to_one",
    )

    comparison = comparison.rename(
        columns={
            "f_reflect": "f_reflect_hybrid_irflux",
            "Fp_th_band": "Fp_th_band_hybrid_irflux",
            "decision": "decision_hybrid_irflux",
        }
    )
    denominator = comparison["Fp_ref_band"] + comparison["Fp_th_band_james_picaso"]
    comparison["f_reflect_james_picaso"] = np.divide(
        comparison["Fp_ref_band"],
        denominator,
        out=np.full(len(comparison), np.nan, dtype=float),
        where=denominator.to_numpy(dtype=float) > 0,
    )
    comparison["decision_james_picaso"] = (
        comparison["f_reflect_james_picaso"] >= float(thresh)
    )
    comparison["delta_f_reflect_james_minus_hybrid"] = (
        comparison["f_reflect_james_picaso"]
        - comparison["f_reflect_hybrid_irflux"]
    )
    comparison["thermal_ratio_james_to_hybrid"] = np.divide(
        comparison["Fp_th_band_james_picaso"],
        comparison["Fp_th_band_hybrid_irflux"],
        out=np.full(len(comparison), np.nan, dtype=float),
        where=comparison["Fp_th_band_hybrid_irflux"].to_numpy(dtype=float) > 0,
    )
    comparison["decision_changed"] = (
        comparison["decision_james_picaso"]
        != comparison["decision_hybrid_irflux"].astype(bool)
    )

    first_cols = [
        "T_eff",
        "logg",
        "R_p_Rj",
        "a_AU",
        "phase_deg",
        "band",
        "Fp_ref_band",
        "Fp_th_band_hybrid_irflux",
        "Fp_th_band_james_picaso",
        "thermal_ratio_james_to_hybrid",
        "f_reflect_hybrid_irflux",
        "f_reflect_james_picaso",
        "delta_f_reflect_james_minus_hybrid",
        "decision_hybrid_irflux",
        "decision_james_picaso",
        "decision_changed",
    ]
    remaining_cols = [col for col in comparison.columns if col not in first_cols]
    comparison = comparison[first_cols + remaining_cols]

    if output_csv is not None:
        comparison.to_csv(output_csv, index=False)
    return comparison


def summarize_comparison(comparison: pd.DataFrame) -> pd.DataFrame:
    """Compact band-level summary for the comparison notebook."""
    grouped = comparison.groupby("band", as_index=False)
    return grouped.agg(
        rows=("band", "size"),
        hybrid_decisions=("decision_hybrid_irflux", "sum"),
        james_decisions=("decision_james_picaso", "sum"),
        changed_decisions=("decision_changed", "sum"),
        median_thermal_ratio=("thermal_ratio_james_to_hybrid", "median"),
        median_delta_f_reflect=("delta_f_reflect_james_minus_hybrid", "median"),
        max_abs_delta_f_reflect=(
            "delta_f_reflect_james_minus_hybrid",
            lambda values: float(np.nanmax(np.abs(values))),
        ),
    )
