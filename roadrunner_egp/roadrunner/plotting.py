"""
roadrunner.plotting
~~~~~~~~~~~~~~~~~~
All visualisation functions for the Roman CGI pipeline.
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

from .config import CGI_BANDS, REFLECT_THRESHOLD
from .physics import planck_surface_erg_cm

# ---------------------------------------------------------------------------
# Blackbody fitting
# ---------------------------------------------------------------------------

def fit_blackbody(lam_um, flux, teff_guess):
    """Fit a scaled blackbody to *flux*(λ).  Returns (T_fit, scale)."""
    def bb_func(lam, T, scale):
        lam_cm = lam * 1e-4
        return scale * planck_surface_erg_cm(T, lam_cm) / np.pi

    try:
        mask = (lam_um > 0.5) & (lam_um < 0.9) & (flux > 0)
        if mask.sum() < 10:
            return teff_guess, 1.0
        popt, _ = curve_fit(
            bb_func, lam_um[mask], flux[mask],
            p0=[teff_guess, 1.0], maxfev=5000,
            bounds=([100, 0], [3000, np.inf]),
        )
        return popt[0], popt[1]
    except Exception:
        return teff_guess, 1.0


# ---------------------------------------------------------------------------
# Spectra + BB sanity-check  (2-panel)
# ---------------------------------------------------------------------------

def plot_spectra_with_bb(lam_um, fp_ref, fp_th, sys, title_suffix=""):
    """Dual-panel plot: fluxes + ratio, with blackbody fits."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))

    # --- Panel 1: fluxes ---
    ax1.plot(lam_um, fp_ref, label="Reflected Flux", lw=2, color="steelblue")
    ax1.plot(lam_um, fp_th,  label="Thermal Flux",   lw=2, color="coral")

    # BB fit – thermal
    T_fit, scale_fit = fit_blackbody(lam_um, fp_th, sys.teff_k)
    lam_cm = lam_um * 1e-4
    bb_fit = scale_fit * planck_surface_erg_cm(T_fit, lam_cm) / np.pi
    ax1.plot(lam_um, bb_fit, "--",
             label=f"Thermal BB: T={T_fit:.0f}K", lw=2,
             color="red", alpha=0.7)

    # BB fit – reflected  (should match T_star)
    T_fit_ref = None
    try:
        T_fit_ref, scale_fit_ref = fit_blackbody(lam_um, fp_ref, sys.tstar_k)
        bb_fit_ref = scale_fit_ref * planck_surface_erg_cm(T_fit_ref, lam_cm) / np.pi
        ax1.plot(lam_um, bb_fit_ref, "--",
                 label=f"Reflected BB: T={T_fit_ref:.0f}K", lw=2,
                 color="blue", alpha=0.7)
        frac_diff = abs(T_fit_ref - sys.tstar_k) / sys.tstar_k
        if frac_diff < 0.1:
            print(f"✓ Reflected spectrum matches stellar BB "
                  f"(T_fit={T_fit_ref:.0f}K vs T★={sys.tstar_k}K)")
        else:
            print(f"⚠ Reflected spectrum deviates from stellar BB "
                  f"(T_fit={T_fit_ref:.0f}K vs T★={sys.tstar_k}K)")
    except Exception as e:
        print(f"Reflected blackbody fit failed: {e}")

    # CGI band shading
    _band_colors = ["#e8f4f8", "#d4ebf2", "#bee3e9", "#a8dbe0"]
    for i, (name, (lo, hi)) in enumerate(CGI_BANDS.items()):
        ax1.axvspan(lo, hi, color=_band_colors[i], alpha=0.2)

    ax1.set_yscale("log")
    ax1.set_xlim(0.3, 1)
    ax1.set_xlabel("Wavelength (µm)", fontweight="bold")
    ax1.set_ylabel("Planet Flux (erg/s/cm²/cm)", fontweight="bold")
    ax1.set_title(f"Planet Fluxes with BB Sanity Check{title_suffix}",
                  fontweight="bold")
    ax1.legend(loc="best")
    ax1.grid(alpha=0.3)

    # --- Panel 2: ratio ---
    ratio = np.where(fp_th > 0, fp_ref / fp_th, 0)
    ax2.plot(lam_um, ratio, lw=2, color="purple")
    ax2.axhline(1, ls="--", color="black", alpha=0.5,
                label="Equal contribution")

    for i, (name, (lo, hi)) in enumerate(CGI_BANDS.items()):
        ax2.axvspan(lo, hi, color=_band_colors[i], alpha=0.2,
                    label=name if i == 0 else "")

    ax2.set_xlim(0.3, 1)
    ax2.set_xlabel("Wavelength (µm)", fontweight="bold")
    ax2.set_ylabel("Fp_reflected / Fp_thermal", fontweight="bold")
    ax2.set_title("Reflected/Thermal Ratio", fontweight="bold")
    ax2.set_yscale("log")
    ax2.legend(loc="best")
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.show()

    print(f"Thermal BB fit: T_eff = {T_fit:.0f} K (input: {sys.teff_k} K), "
          f"scale = {scale_fit:.2e}")
    if T_fit_ref is not None:
        print(f"Reflected BB fit: T_eff = {T_fit_ref:.0f} K "
              f"(stellar: {sys.tstar_k} K), scale = {scale_fit_ref:.2e}")


# ---------------------------------------------------------------------------
# Band bar chart
# ---------------------------------------------------------------------------

def plot_band_bars(rows, title_suffix=""):
    """Bar plot of reflected fraction per CGI band."""
    names  = [r[0] for r in rows]
    fvals  = [r[1] for r in rows]
    colors = ["steelblue", "teal", "mediumseagreen", "coral"]

    plt.figure(figsize=(8, 5))
    plt.bar(names, fvals, color=colors, alpha=0.8,
            edgecolor="black", linewidth=1.5)
    plt.axhline(REFLECT_THRESHOLD, ls="--", color="red", lw=2,
                label=f"{REFLECT_THRESHOLD*100}% threshold")
    plt.ylim(0, 1)
    plt.ylabel("f_reflect = Fp_ref / (Fp_ref + Fp_th)", fontweight="bold")
    plt.xlabel("Roman CGI Band", fontweight="bold")
    plt.title(f"Reflected Fraction per Band{title_suffix}", fontweight="bold")
    plt.legend()
    plt.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.show()


# ---------------------------------------------------------------------------
# Grid-summary visualisations
# ---------------------------------------------------------------------------

def plot_summary_histogram(df_all, thresh=REFLECT_THRESHOLD):
    """Histogram of *f_reflect* by band."""
    plt.figure(figsize=(10, 5))
    for band in ["CGI-1", "CGI-2", "CGI-3", "CGI-4"]:
        sub = df_all[df_all["band"] == band]
        plt.hist(sub["f_reflect"], bins=30, alpha=0.3, label=band)
    plt.axvline(thresh, ls="--", color="red", lw=2,
                label=f"{thresh*100}% threshold")
    plt.xlabel("f_reflect", fontweight="bold")
    plt.ylabel("Count", fontweight="bold")
    plt.title("Distribution of Reflected Fraction by Band", fontweight="bold")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.show()


def plot_summary_heatmaps(df_all):
    """Heatmap of f_reflect vs T_eff and a_AU for each CGI band."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    axes = axes.flatten()
    phase_vals = []
    if "phase_deg" in df_all.columns:
        phase_vals = sorted(df_all["phase_deg"].dropna().unique())

    for i, band in enumerate(["CGI-1", "CGI-2", "CGI-3", "CGI-4"]):
        sub = df_all[
            (df_all["band"] == band)
            & (np.isclose(df_all["logg"], 3.5))
            & (np.isclose(df_all["R_p_Rj"], 1.0))
        ]
        if sub.empty:
            continue
        pivot = sub.pivot_table(
            index="T_eff", columns="a_AU",
            values="f_reflect", aggfunc="mean",
        )
        im = axes[i].imshow(
            pivot.values, aspect="auto", cmap="RdYlBu_r",
            vmin=0, vmax=1, origin="lower",
        )
        axes[i].set_xticks(range(len(pivot.columns)))
        axes[i].set_xticklabels([f"{x:.0f}" for x in pivot.columns])
        axes[i].set_yticks(range(len(pivot.index)))
        axes[i].set_yticklabels([f"{int(x)}" for x in pivot.index])
        axes[i].set_xlabel("a (AU)", fontweight="bold")
        axes[i].set_ylabel("Teff (K)", fontweight="bold")
        axes[i].set_title(band, fontweight="bold")

        for j in range(len(pivot.index)):
            for k in range(len(pivot.columns)):
                val = pivot.values[j, k]
                if not np.isnan(val):
                    color = "white" if val > 0.5 else "black"
                    axes[i].text(k, j, f"{val:.2f}",
                                 ha="center", va="center",
                                 color=color, fontsize=9)

    if len(phase_vals) == 1:
        phase_text = f"phase={phase_vals[0]:g}°"
    elif len(phase_vals) > 1:
        phase_text = "phases=" + ", ".join(f"{phase:g}°" for phase in phase_vals)
    else:
        phase_text = "phase=unknown"

    plt.suptitle(
        f"Reflected Fraction Heatmaps (logg=3.5, Rp=1.0 Rj, {phase_text})",
        fontweight="bold", fontsize=14,
    )
    plt.tight_layout()
    plt.show()
