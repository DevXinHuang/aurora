"""Load Cahoy et al. 2010 reference albedo spectra."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

GRID_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_ROOT = (
    GRID_ROOT / "data" / "cahoy2010_reference" / "Cahoy_et_al_2010_Albedo_Spectra" / "albedo_spectra"
)
CAHOY_WAVELENGTH_MIN_UM = 0.35
CAHOY_WAVELENGTH_MAX_UM = 1.0


def resolve_reference_root(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    return DEFAULT_REFERENCE_ROOT.resolve()


def reference_spectrum_path(reference_root: Path, cahoy_reference_name: str) -> Path:
    return reference_root / cahoy_reference_name


def load_cahoy_reference_spectrum(
    cahoy_reference_name: str,
    *,
    reference_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load one Cahoy ``.dat`` file (wavelength_um, albedo)."""
    root = resolve_reference_root(reference_root)
    path = reference_spectrum_path(root, cahoy_reference_name)
    if not path.exists():
        raise FileNotFoundError(f"Missing Cahoy reference spectrum: {path}")

    table = np.loadtxt(path, dtype=float)
    if table.ndim != 2 or table.shape[1] < 2:
        raise ValueError(f"Expected two columns in {path}; got shape {table.shape}")

    wavelength_um = np.asarray(table[:, 0], dtype=float)
    albedo = np.asarray(table[:, 1], dtype=float)
    order = np.argsort(wavelength_um)
    return {
        "cahoy_reference_name": cahoy_reference_name,
        "path": path,
        "wavelength_um": wavelength_um[order],
        "albedo": albedo[order],
    }


def list_reference_spectra(reference_root: str | Path | None = None) -> list[str]:
    root = resolve_reference_root(reference_root)
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.glob("*.dat"))
