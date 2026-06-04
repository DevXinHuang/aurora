"""
roadrunner.bands
~~~~~~~~~~~~~~~
Band-level metrics and the main single-case evaluation pipeline.
"""

import re

import numpy as np
import pandas as pd

from .config import (
    CGI_BANDS,
    LAM_GRID,
    REFLECT_THRESHOLD,
    HAVE_PICASO,
    jpi,
)
from .physics import top_hat, trapz_band, frac_reflected
from .system import SystemParams
from .runner import run_picaso_once, extract_planet_fluxes
from .plotting import plot_spectra_with_bb, plot_band_bars

# ---------------------------------------------------------------------------
# Pre-computed band filters
# ---------------------------------------------------------------------------
BANDS = {name: top_hat(LAM_GRID, lo, hi) for name, (lo, hi) in CGI_BANDS.items()}

_BAND_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
}

# DataFrame columns
COLUMNS = [
    "T_eff", "logg", "R_p_Rj", "a_AU", "phase_deg",
    "band", "f_reflect", "Fp_ref_band", "Fp_th_band", "decision",
]


def _canonical_band_name(value) -> str:
    """Return a canonical CGI band name from friendly user input."""
    if isinstance(value, (int, np.integer)):
        candidate = f"CGI-{int(value)}"
    else:
        text = str(value).strip()
        if text in CGI_BANDS:
            return text

        normalized = re.sub(r"\s+", "-", text.lower().replace("_", "-"))
        parts = [part for part in normalized.split("-") if part]
        number = _BAND_NUMBER_WORDS.get(parts[-1]) if parts else None
        if number is None:
            match = re.search(r"(?:^|[^0-9])([1-4])$", normalized)
            number = match.group(1) if match else None

        candidate = f"CGI-{number}" if number else ""

    if candidate not in CGI_BANDS:
        choices = ", ".join(CGI_BANDS)
        raise ValueError(f"Unknown CGI band {value!r}; choose one of: {choices}.")
    return candidate


def normalize_band_names(selected_bands=None) -> list[str]:
    """
    Normalize a user band selection into canonical CGI band names.

    Examples
    --------
    ``None`` or ``"all"`` selects all bands. ``1``, ``"1"``, ``"band one"``,
    and ``"CGI-1"`` all select ``"CGI-1"``.
    """
    if selected_bands is None:
        return list(CGI_BANDS)

    if isinstance(selected_bands, str):
        raw = selected_bands.strip()
        if raw.lower() in {"", "*", "all", "any"}:
            return list(CGI_BANDS)

        if re.search(r"[,;/]", raw):
            values = [part for part in re.split(r"[,;/]+", raw) if part.strip()]
        else:
            pieces = raw.split()
            if len(pieces) > 1:
                try:
                    values = [_canonical_band_name(piece) for piece in pieces]
                except ValueError:
                    values = [raw]
            else:
                values = [raw]
    else:
        try:
            values = list(selected_bands)
        except TypeError:
            values = [selected_bands]

    names = []
    for value in values:
        name = value if value in CGI_BANDS else _canonical_band_name(value)
        if name not in names:
            names.append(name)
    return names


def select_bands(selected_bands=None, lam_grid_um=LAM_GRID) -> dict[str, np.ndarray]:
    """Build top-hat bandpass filters for the selected CGI bands."""
    lam_grid_um = np.asarray(lam_grid_um, dtype=float)
    return {
        name: top_hat(lam_grid_um, *CGI_BANDS[name])
        for name in normalize_band_names(selected_bands)
    }


def wavelength_grid_for_bands(selected_bands=None, lam_grid_um=LAM_GRID) -> np.ndarray:
    """
    Return the portion of a wavelength grid needed for the selected CGI bands.

    Selecting all bands keeps the input grid unchanged. Selecting one band, for
    example ``"CGI-1"``, narrows PICASO's opacity range to that band.
    """
    base_grid = np.asarray(lam_grid_um, dtype=float)
    names = normalize_band_names(selected_bands)

    if names == list(CGI_BANDS):
        return base_grid

    lo = min(CGI_BANDS[name][0] for name in names)
    hi = max(CGI_BANDS[name][1] for name in names)
    mask = (base_grid >= lo) & (base_grid <= hi)
    selected_grid = base_grid[mask]
    if selected_grid.size >= 2:
        return selected_grid

    if base_grid.size >= 2:
        sorted_grid = np.sort(base_grid)
        steps = np.diff(sorted_grid)
        steps = steps[steps > 0]
        spacing = float(np.median(steps)) if steps.size else (hi - lo) / 100
        count = max(2, int(np.ceil((hi - lo) / spacing)) + 1)
    else:
        count = 100
    return np.linspace(lo, hi, count)

# ---------------------------------------------------------------------------
# Per-band metrics
# ---------------------------------------------------------------------------

def band_metrics(lam_um, fp_ref, fp_th, bands_dict, thresh=REFLECT_THRESHOLD):
    """
    Compute reflected fraction for each band.

    Returns
    -------
    list of (name, f, Fp_ref_band, Fp_th_band, decision)
    """
    rows = []
    for name, Tband in bands_dict.items():
        f          = frac_reflected(lam_um, fp_ref, fp_th, Tband)
        Fp_ref_band = trapz_band(lam_um, fp_ref, Tband)
        Fp_th_band  = trapz_band(lam_um, fp_th, Tband)
        decision    = (f >= thresh) if np.isfinite(f) else False
        rows.append((name, f, Fp_ref_band, Fp_th_band, decision))
    return rows


# ---------------------------------------------------------------------------
# Full single-case evaluation
# ---------------------------------------------------------------------------

def evaluate_case(
    sys: SystemParams,
    lam_grid_um=LAM_GRID,
    thresh=REFLECT_THRESHOLD,
    do_plots=False,
    atmosphere_source=None,
    cloud_model=None,
    selected_bands=None,
):
    """
    Run PICASO for one system → extract fluxes → compute band metrics.

    Parameters
    ----------
    sys : SystemParams
    lam_grid_um : array
    thresh : float
    do_plots : bool
        If True, produce spectra + bar-chart plots.
    atmosphere_source : str, optional
        ``"slgrid"`` reads PT/cloud files. ``"picaso"`` generates a Guillot
        PT profile, Visscher chemistry, and configured clouds in PICASO.
    cloud_model : str, optional
        Generated-PICASO cloud model: ``"virga"``, ``"jupiter"``, or
        ``"none"``.
    selected_bands : str or sequence, optional
        CGI bands to evaluate. Examples: ``"CGI-1"``, ``1``, or
        ``["CGI-1", "CGI-2"]``. Defaults to all bands.

    Returns
    -------
    pd.DataFrame  with columns ``COLUMNS``.
    """
    if not HAVE_PICASO:
        raise RuntimeError("PICASO is required")

    import matplotlib.pyplot as plt

    lam_grid_um = wavelength_grid_for_bands(selected_bands, lam_grid_um)

    # 1. run PICASO
    out_ref, out_em = run_picaso_once(
        sys,
        lam_grid_um,
        atmosphere_source=atmosphere_source,
        cloud_model=cloud_model,
    )

    # 2. extract absolute planet fluxes
    lam, fp_ref, fp_th = extract_planet_fluxes(
        out_ref, out_em, lam_grid_um, sys,
    )

    # 3. band metrics
    rows = band_metrics(
        lam,
        fp_ref,
        fp_th,
        select_bands(selected_bands, lam),
        thresh=thresh,
    )

    # 4. optional plots
    if do_plots:
        suffix = (f" (Teff={sys.teff_k}K, a={sys.a_au}AU, "
                  f"α={sys.phase_deg}°)")
        plot_spectra_with_bb(lam, fp_ref, fp_th, sys, title_suffix=suffix)
        plot_band_bars(rows, title_suffix=suffix)

        # PICASO full-output diagnostics (heatmap of opacities)
        if "full_output" in out_ref:
            try:
                jpi.heatmap_taus(out_ref)
                plt.show()
            except Exception:
                pass
            try:
                jpi.output_notebook()
                jpi.show(jpi.cloud(out_ref["full_output"]))
                jpi.show(jpi.mixing_ratio(out_ref["full_output"]))
            except Exception as e:
                print("Cloud profile plot skipped:", e)

    # 5. build DataFrame
    recs = []
    for name, f, Fp_ref, Fp_th, decision in rows:
        recs.append({
            "T_eff":      sys.teff_k,
            "logg":       sys.logg_cgs,
            "R_p_Rj":     sys.rj,
            "a_AU":       sys.a_au,
            "phase_deg":  sys.phase_deg,
            "band":       name,
            "f_reflect":  float(f) if np.isfinite(f) else np.nan,
            "Fp_ref_band": float(Fp_ref),
            "Fp_th_band":  float(Fp_th),
            "decision":   bool(decision),
        })
    return pd.DataFrame(recs)
