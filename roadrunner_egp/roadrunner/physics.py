"""
roadrunner.physics
~~~~~~~~~~~~~~~~~
Pure physics / math utilities: Planck function, unit conversions,
bandpass filters, and band-integrated fluxes.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Fundamental constants (CGS)
# ---------------------------------------------------------------------------
_H  = 6.62607015e-27   # erg·s
_C  = 2.99792458e10    # cm/s
_KB = 1.380649e-16     # erg/K

# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def wno_to_lam_um(wno_cm1):
    """Convert wavenumber (cm⁻¹) → wavelength (µm)."""
    return 1e4 / np.asarray(wno_cm1)


# ---------------------------------------------------------------------------
# Planck function
# ---------------------------------------------------------------------------

def planck_surface_erg_cm(T, lam_cm):
    """
    Planck surface flux: π·B_λ(T) in erg s⁻¹ cm⁻² cm⁻¹.

    Parameters
    ----------
    T : float
        Temperature [K].
    lam_cm : array-like
        Wavelength in cm.
    """
    lam = np.asarray(lam_cm)
    a = 2.0 * _H * _C**2
    b = (_H * _C) / (_KB * T)
    B_lam = a / (lam**5 * (np.exp(b / lam) - 1.0))
    return np.pi * B_lam


# ---------------------------------------------------------------------------
# Bandpass helpers
# ---------------------------------------------------------------------------

def top_hat(lam_um, lo, hi):
    """Return a top-hat (0/1) bandpass between *lo* and *hi* µm."""
    lam = np.asarray(lam_um)
    return ((lam >= lo) & (lam <= hi)).astype(float)


def trapz_band(lam_um, y, T):
    """Integrate *y* × *T* over wavelength (trapezoidal rule)."""
    lam = np.asarray(lam_um)
    yv = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    Tv = np.nan_to_num(T, nan=0.0, posinf=0.0, neginf=0.0)
    m = np.isfinite(lam) & np.isfinite(yv) & np.isfinite(Tv)
    if m.sum() < 2:
        return 0.0
    trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return trapezoid(yv[m] * Tv[m], lam[m])


def frac_reflected(lam_um, fpfs_ref, fpfs_th, Tband):
    """Reflected fraction R / (R + Th) integrated over a bandpass."""
    R  = trapz_band(lam_um, fpfs_ref, Tband)
    Th = trapz_band(lam_um, fpfs_th, Tband)
    if (R + Th) <= 0:
        return np.nan
    return np.clip(R / (R + Th), 0.0, 1.0)
