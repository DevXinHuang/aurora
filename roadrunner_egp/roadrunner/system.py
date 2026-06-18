"""
roadrunner.system
~~~~~~~~~~~~~~~~
SystemParams dataclass and SLGRID atmosphere-file resolution.
"""

import os
import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from .config import (
    ATMOSPHERE_SOURCE,
    PICASO_BOND_ALBEDO,
    PICASO_CHEM_C_TO_O,
    PICASO_CHEM_LOG_MH,
    PICASO_CLOUD_MODEL,
    PICASO_KZZ_CGS,
    PICASO_VIRGA_CONDENSATES,
    PICASO_VIRGA_DIR,
    PICASO_VIRGA_FSED,
    T_STAR_K,
    R_STAR_Rsun,
    ATM_NLAYERS,
    SLGRID_PT_DIR,
    SLGRID_CLD_DIR,
    SLGRID_FILES_BY_TEFF,
    FALLBACK_TEFF_MAP,
)

NO_SLGRID_CLOUD_TOKENS = {"", "none", "clear", "cloudfree", "cloud-free", "nc"}

_SLGRID_NAME_RE = re.compile(
    r"^SLGRID_T(?P<teff>\d+)_g(?P<g>\d+)_m(?P<metal>[+-]\d{3})_CO(?P<co>\d{3})_"
    r"(?P<cloud>.+)\.(?P<ext>pt|cld)$"
)
_PREFERRED_SLGRID_METAL = "+000"
_PREFERRED_SLGRID_CO = "100"
_PREFERRED_SLGRID_FSED = "3"
_PREFERRED_SLGRID_FRAC = None

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class SystemParams:
    """Physical parameters for one exoplanet system."""
    teff_k:      float
    logg_cgs:    float
    rj:          float          # planet radius [R_Jup]
    a_au:        float          # semi-major axis [AU]
    phase_deg:   float          # phase angle [deg]
    tstar_k:     float = T_STAR_K
    rstar_rsun:  float = R_STAR_Rsun
    pt_file:     str   = None   # override: absolute or basename PT file
    cld_file:    str   = None   # override: absolute or basename CLD file
    atmosphere_source: str = ATMOSPHERE_SOURCE  # "slgrid" or "picaso"
    cloud_model: str = PICASO_CLOUD_MODEL       # for atmosphere_source="picaso"
    bond_albedo: float = PICASO_BOND_ALBEDO
    chem_c_o: float = PICASO_CHEM_C_TO_O
    chem_log_mh: float = PICASO_CHEM_LOG_MH
    kzz_cgs: float = PICASO_KZZ_CGS
    virga_condensates: str = PICASO_VIRGA_CONDENSATES
    virga_fsed: float = PICASO_VIRGA_FSED
    virga_dir: str = PICASO_VIRGA_DIR


# ---------------------------------------------------------------------------
# SLGRID file resolution
# ---------------------------------------------------------------------------

def _resolve_slgrid_file(spec, base_dir):
    """Return absolute path from *spec* (may be None, basename, or abs)."""
    if spec is None:
        return None
    if os.path.isabs(spec):
        return spec
    return os.path.join(base_dir, spec)


def _parse_slgrid_filename(name):
    """Parse an SLGRID filename into comparable metadata."""
    match = _SLGRID_NAME_RE.match(name)
    if not match:
        return None

    meta = match.groupdict()
    fsed_match = re.search(r"_fsed(?P<fsed>[0-9.]+)", name)
    frac_match = re.search(r"_frac(?P<frac>\d+)", name)

    g_code = int(meta["g"])
    return {
        "name": name,
        "teff": int(meta["teff"]),
        "g_code": g_code,
        "logg_cgs": float(np.log10(g_code) + 2.0),
        "metal": meta["metal"],
        "co": meta["co"],
        "fsed": fsed_match.group("fsed") if fsed_match else None,
        "frac": frac_match.group("frac") if frac_match else None,
        "ext": meta["ext"],
    }


def _inventory_key(meta):
    return (
        meta["teff"],
        meta["g_code"],
        meta["metal"],
        meta["co"],
        meta["fsed"],
        meta["frac"],
    )


def _inventory_entry_sort_key(entry):
    fsed_rank = float(entry["fsed"]) if entry["fsed"] is not None else -1.0
    frac_rank = int(entry["frac"]) if entry["frac"] is not None else -1
    return (
        entry["teff"],
        entry["g_code"],
        entry["metal"],
        entry["co"],
        entry["fsed"] is None,
        fsed_rank,
        entry["frac"] is not None,
        frac_rank,
    )


@lru_cache(maxsize=None)
def _scan_slgrid_inventory(pt_dir=SLGRID_PT_DIR, cld_dir=SLGRID_CLD_DIR):
    """Scan SLGRID PT and cloud directories once and cache the result."""
    pt_entries = {}
    cld_entries = {}

    if os.path.isdir(pt_dir):
        for name in os.listdir(pt_dir):
            if not name.endswith(".pt"):
                continue
            meta = _parse_slgrid_filename(name)
            if meta:
                pt_entries[_inventory_key(meta)] = meta

    if os.path.isdir(cld_dir):
        for name in os.listdir(cld_dir):
            if not name.endswith(".cld"):
                continue
            meta = _parse_slgrid_filename(name)
            if meta:
                cld_entries[_inventory_key(meta)] = meta

    shared_by_teff = {}
    for key in (set(pt_entries) & set(cld_entries)):
        teff = key[0]
        shared_by_teff.setdefault(teff, []).append({
            "teff": teff,
            "g_code": key[1],
            "logg_cgs": float(np.log10(key[1]) + 2.0),
            "metal": key[2],
            "co": key[3],
            "fsed": key[4],
            "frac": key[5],
            "pt": pt_entries[key]["name"],
            "cld": cld_entries[key]["name"],
        })

    for teff in shared_by_teff:
        shared_by_teff[teff].sort(key=_inventory_entry_sort_key)

    return {
        "pt_teffs": sorted({key[0] for key in pt_entries}),
        "cld_teffs": sorted({key[0] for key in cld_entries}),
        "shared_teffs": sorted(shared_by_teff),
        "shared_by_teff": shared_by_teff,
    }


def _score_slgrid_candidate(entry, logg_cgs):
    target_g_code = 10 ** (float(logg_cgs) - 2.0)
    return (
        entry["metal"] != _PREFERRED_SLGRID_METAL,
        entry["co"] != _PREFERRED_SLGRID_CO,
        entry["fsed"] != _PREFERRED_SLGRID_FSED,
        entry["frac"] != _PREFERRED_SLGRID_FRAC,
        abs(entry["logg_cgs"] - float(logg_cgs)),
        abs(entry["g_code"] - target_g_code),
        entry["g_code"],
        entry["pt"],
    )


def _best_slgrid_entry(teff_k, logg_cgs):
    """Return the best shared PT/cloud pairing for a temperature/logg."""
    inventory = _scan_slgrid_inventory()
    teff_key = int(round(teff_k))
    entries = inventory["shared_by_teff"].get(teff_key, [])
    if not entries:
        return None
    return min(entries, key=lambda entry: _score_slgrid_candidate(entry, logg_cgs))


def available_slgrid_teffs():
    """Temperatures that have at least one shared PT/cloud pairing."""
    return list(_scan_slgrid_inventory()["shared_teffs"])


def summarize_slgrid_inventory():
    """Summary of PT-only, cloud-only, and shared SLGRID temperatures."""
    inventory = _scan_slgrid_inventory()
    pt_teffs = set(inventory["pt_teffs"])
    cld_teffs = set(inventory["cld_teffs"])
    shared_teffs = set(inventory["shared_teffs"])
    return {
        "pt_teffs": inventory["pt_teffs"],
        "cld_teffs": inventory["cld_teffs"],
        "shared_teffs": inventory["shared_teffs"],
        "pt_only_teffs": sorted(pt_teffs - cld_teffs),
        "cld_only_teffs": sorted(cld_teffs - pt_teffs),
        "preferred_family": {
            "metal": _PREFERRED_SLGRID_METAL,
            "co": _PREFERRED_SLGRID_CO,
            "fsed": _PREFERRED_SLGRID_FSED,
            "frac": _PREFERRED_SLGRID_FRAC,
        },
    }


def resolve_slgrid_files(sys: SystemParams):
    """
    Return ``(pt_path, cld_path)`` for a given ``SystemParams``.

    Resolution order:
    1. Explicit ``sys.pt_file`` / ``sys.cld_file`` overrides.
    2. Auto-discovered shared PT/cloud match from the real SLGRID folders.
    3. ``SLGRID_FILES_BY_TEFF[teff]`` lookup.
    4. ``FALLBACK_TEFF_MAP[teff]`` → try step 3 again.

    Raises ``FileNotFoundError`` if files cannot be located.
    """
    teff_key = int(round(sys.teff_k))
    pt_file  = sys.pt_file
    cld_file = sys.cld_file
    cloudless = isinstance(cld_file, str) and cld_file.strip().lower() in NO_SLGRID_CLOUD_TOKENS

    # Step 2 — discovered shared PT/cloud pairing
    if pt_file is None or (cld_file is None and not cloudless):
        entry = _best_slgrid_entry(teff_key, sys.logg_cgs)
        if entry:
            pt_file = pt_file or entry["pt"]
            if not cloudless:
                cld_file = cld_file or entry["cld"]

    # Step 3 — legacy manual mapping
    if pt_file is None or (cld_file is None and not cloudless):
        spec = SLGRID_FILES_BY_TEFF.get(teff_key)
        if spec:
            pt_file  = pt_file  or spec.get("pt")
            if not cloudless:
                cld_file = cld_file or spec.get("cld")

    # Step 4 — fallback temperature mapping
    if (pt_file is None or (cld_file is None and not cloudless)) and teff_key in FALLBACK_TEFF_MAP:
        fb = FALLBACK_TEFF_MAP[teff_key]
        entry = _best_slgrid_entry(fb, sys.logg_cgs)
        if entry:
            pt_file = pt_file or entry["pt"]
            if not cloudless:
                cld_file = cld_file or entry["cld"]
            print(
                f"⚠ No SLGRID files for Teff={teff_key}K; "
                f"falling back to Teff={fb}K files."
            )
        else:
            spec = SLGRID_FILES_BY_TEFF.get(fb)
            if spec:
                pt_file  = pt_file  or spec.get("pt")
                if not cloudless:
                    cld_file = cld_file or spec.get("cld")
                print(
                    f"⚠ No SLGRID files for Teff={teff_key}K; "
                    f"falling back to Teff={fb}K files."
                )

    pt_path  = _resolve_slgrid_file(pt_file,  SLGRID_PT_DIR)
    cld_path = None if cloudless else _resolve_slgrid_file(cld_file, SLGRID_CLD_DIR)

    if not pt_path or (not cld_path and not cloudless):
        raise FileNotFoundError(
            f"Missing SLGRID PT/CLD file for Teff={teff_key}K. "
            f"Check the shared SLGRID inventory, set "
            f"SLGRID_FILES_BY_TEFF[{teff_key}], or pass "
            f"SystemParams(pt_file=..., cld_file=...)."
        )
    if not os.path.exists(pt_path):
        raise FileNotFoundError(f"PT file not found: {pt_path}")
    if cld_path is not None and not os.path.exists(cld_path):
        raise FileNotFoundError(f"CLD file not found: {cld_path}")

    return pt_path, cld_path


# ---------------------------------------------------------------------------
# Fallback atmosphere builder (kept for compatibility)
# ---------------------------------------------------------------------------

def build_simple_atmosphere(teff_k: float, logg_cgs: float,
                            nlayer: int = ATM_NLAYERS) -> pd.DataFrame:
    """Simple H₂/He atmosphere with a power-law T–P profile.

    .. deprecated:: This is a placeholder; prefer SLGRID PT files.
    """
    p_bar = np.logspace(-6, 2, nlayer)
    temperature = np.clip(
        teff_k * (p_bar / p_bar.mean()) ** 0.02,
        0.5 * teff_k,
        1.5 * teff_k,
    )
    return pd.DataFrame({
        "pressure":    p_bar,
        "temperature": temperature,
        "H2":          np.full(nlayer, 0.85),
        "He":          np.full(nlayer, 0.15),
    })
