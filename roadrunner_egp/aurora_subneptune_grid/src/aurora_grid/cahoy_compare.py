"""Compare Aurora PICASO NetCDF spectra against Cahoy et al. 2010 reference albedos."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from .cahoy_reference import (
    CAHOY_WAVELENGTH_MAX_UM,
    CAHOY_WAVELENGTH_MIN_UM,
    list_reference_spectra,
    load_cahoy_reference_spectrum,
    resolve_reference_root,
)
from .parameters import read_manifest_csv, resolve_repo_path

ROMAN_CGI_BANDS_UM: dict[str, tuple[float, float]] = {
    "CGI-1": (0.546, 0.604),
    "CGI-2": (0.610, 0.710),
    "CGI-3": (0.675, 0.785),
    "CGI-4": (0.783, 0.867),
}


@dataclass(frozen=True)
class CahoyCompareMetrics:
    cahoy_reference_name: str
    run_index: int
    output_nc: str
    phase_deg: float
    n_points: int
    rmse: float
    mae: float
    max_abs_diff: float
    mean_cahoy_albedo: float
    mean_aurora_albedo: float
    relative_rmse: float
    pearson_r: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _manifest_lookup(manifest_path: str | Path) -> dict[int, dict[str, Any]]:
    table = read_manifest_csv(manifest_path)
    return {int(row["run_index"]): dict(row) for row in table.rows}


def _cahoy_name_from_dataset(ds: xr.Dataset) -> str | None:
    raw = ds.attrs.get("source_manifest_row")
    if not raw:
        return None
    try:
        row = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    name = row.get("cahoy_reference_name")
    return str(name) if name else None


def _run_index_from_dataset(ds: xr.Dataset) -> int | None:
    if "run_index" in ds:
        return int(ds["run_index"].values)
    raw = ds.attrs.get("source_manifest_row")
    if not raw:
        return None
    try:
        row = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if "run_index" not in row:
        return None
    return int(row["run_index"])


def load_aurora_albedo_spectrum(nc_path: str | Path) -> dict[str, Any]:
    path = Path(nc_path)
    with xr.open_dataset(path) as ds:
        wavelength_um = np.asarray(ds["wavelength_um"].values, dtype=float)
        albedo = np.asarray(ds["geometric_albedo"].values, dtype=float)
        phase_deg = float(ds["phase_angle_deg"].values) if "phase_angle_deg" in ds else float("nan")
        run_index = _run_index_from_dataset(ds)
        cahoy_name = _cahoy_name_from_dataset(ds)
        return {
            "path": path,
            "wavelength_um": wavelength_um,
            "albedo": albedo,
            "phase_deg": phase_deg,
            "run_index": run_index,
            "cahoy_reference_name": cahoy_name,
        }


def interpolate_aurora_to_cahoy_grid(
    aurora_wavelength_um: np.ndarray,
    aurora_albedo: np.ndarray,
    cahoy_wavelength_um: np.ndarray,
) -> np.ndarray:
    order = np.argsort(aurora_wavelength_um)
    sorted_wave = aurora_wavelength_um[order]
    sorted_albedo = aurora_albedo[order]
    return np.interp(
        cahoy_wavelength_um,
        sorted_wave,
        sorted_albedo,
        left=np.nan,
        right=np.nan,
    )


def band_mean_albedo(wavelength_um: np.ndarray, albedo: np.ndarray, lo: float, hi: float) -> float:
    mask = (wavelength_um >= lo) & (wavelength_um <= hi) & np.isfinite(albedo)
    if mask.sum() < 2:
        return float("nan")
    trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(trapezoid(albedo[mask], wavelength_um[mask]) / (hi - lo))


def compare_spectrum_pair(
    cahoy: dict[str, Any],
    aurora: dict[str, Any],
    *,
    cahoy_reference_name: str,
    run_index: int,
    output_nc: str,
    phase_deg: float,
) -> tuple[CahoyCompareMetrics, dict[str, np.ndarray]]:
    wave = np.asarray(cahoy["wavelength_um"], dtype=float)
    cahoy_albedo = np.asarray(cahoy["albedo"], dtype=float)
    aurora_on_cahoy = interpolate_aurora_to_cahoy_grid(
        np.asarray(aurora["wavelength_um"], dtype=float),
        np.asarray(aurora["albedo"], dtype=float),
        wave,
    )

    valid = np.isfinite(cahoy_albedo) & np.isfinite(aurora_on_cahoy)
    if valid.sum() < 2:
        raise ValueError(f"Not enough overlapping points for {cahoy_reference_name}")

    diff = aurora_on_cahoy[valid] - cahoy_albedo[valid]
    rmse = float(np.sqrt(np.mean(diff**2)))
    mae = float(np.mean(np.abs(diff)))
    max_abs = float(np.max(np.abs(diff)))
    mean_cahoy = float(np.mean(cahoy_albedo[valid]))
    mean_aurora = float(np.mean(aurora_on_cahoy[valid]))
    denom = max(mean_cahoy, 1.0e-6)
    relative_rmse = rmse / denom
    if np.std(cahoy_albedo[valid]) > 0 and np.std(aurora_on_cahoy[valid]) > 0:
        pearson_r = float(np.corrcoef(cahoy_albedo[valid], aurora_on_cahoy[valid])[0, 1])
    else:
        pearson_r = float("nan")

    metrics = CahoyCompareMetrics(
        cahoy_reference_name=cahoy_reference_name,
        run_index=run_index,
        output_nc=output_nc,
        phase_deg=phase_deg,
        n_points=int(valid.sum()),
        rmse=rmse,
        mae=mae,
        max_abs_diff=max_abs,
        mean_cahoy_albedo=mean_cahoy,
        mean_aurora_albedo=mean_aurora,
        relative_rmse=relative_rmse,
        pearson_r=pearson_r,
    )
    arrays = {
        "wavelength_um": wave,
        "cahoy_albedo": cahoy_albedo,
        "aurora_albedo": aurora_on_cahoy,
        "residual": aurora_on_cahoy - cahoy_albedo,
    }
    return metrics, arrays


def compare_nc_to_cahoy(
    nc_path: str | Path,
    *,
    reference_root: str | Path | None = None,
    manifest_row: dict[str, Any] | None = None,
) -> tuple[CahoyCompareMetrics, dict[str, np.ndarray]]:
    aurora = load_aurora_albedo_spectrum(nc_path)
    cahoy_name = (
        (manifest_row or {}).get("cahoy_reference_name")
        or aurora.get("cahoy_reference_name")
    )
    if not cahoy_name:
        raise ValueError(f"Could not determine cahoy_reference_name for {nc_path}")

    run_index = int((manifest_row or {}).get("run_index", aurora.get("run_index", -1)))
    phase_deg = float((manifest_row or {}).get("phase_deg", aurora.get("phase_deg", float("nan"))))
    cahoy = load_cahoy_reference_spectrum(str(cahoy_name), reference_root=reference_root)
    return compare_spectrum_pair(
        cahoy,
        aurora,
        cahoy_reference_name=str(cahoy_name),
        run_index=run_index,
        output_nc=str(nc_path),
        phase_deg=phase_deg,
    )


def compare_manifest_outputs(
    manifest_path: str | Path,
    nc_root: str | Path,
    *,
    reference_root: str | Path | None = None,
    max_cases: int | None = None,
) -> list[tuple[CahoyCompareMetrics, dict[str, np.ndarray] | None, str | None]]:
    lookup = _manifest_lookup(manifest_path)
    nc_root = Path(nc_root)
    results: list[tuple[CahoyCompareMetrics, dict[str, np.ndarray] | None, str | None]] = []

    run_indices = sorted(lookup)
    if max_cases is not None:
        run_indices = run_indices[: max_cases]

    for run_index in run_indices:
        row = lookup[run_index]
        nc_path = resolve_repo_path(row["output_nc"])
        if not nc_path.exists() and nc_root is not None:
            nc_path = Path(nc_root) / Path(row["output_nc"]).name
        if not nc_path.exists():
            results.append(
                (
                    CahoyCompareMetrics(
                        cahoy_reference_name=str(row.get("cahoy_reference_name", "")),
                        run_index=run_index,
                        output_nc=str(nc_path),
                        phase_deg=float(row.get("phase_deg", float("nan"))),
                        n_points=0,
                        rmse=float("nan"),
                        mae=float("nan"),
                        max_abs_diff=float("nan"),
                        mean_cahoy_albedo=float("nan"),
                        mean_aurora_albedo=float("nan"),
                        relative_rmse=float("nan"),
                        pearson_r=float("nan"),
                    ),
                    None,
                    "missing_nc",
                )
            )
            continue
        try:
            metrics, arrays = compare_nc_to_cahoy(
                nc_path,
                reference_root=reference_root,
                manifest_row=row,
            )
            results.append((metrics, arrays, None))
        except Exception as exc:
            results.append(
                (
                    CahoyCompareMetrics(
                        cahoy_reference_name=str(row.get("cahoy_reference_name", "")),
                        run_index=run_index,
                        output_nc=str(nc_path),
                        phase_deg=float(row.get("phase_deg", float("nan"))),
                        n_points=0,
                        rmse=float("nan"),
                        mae=float("nan"),
                        max_abs_diff=float("nan"),
                        mean_cahoy_albedo=float("nan"),
                        mean_aurora_albedo=float("nan"),
                        relative_rmse=float("nan"),
                        pearson_r=float("nan"),
                    ),
                    None,
                    repr(exc),
                )
            )
    return results


def metrics_to_records(
    results: list[tuple[CahoyCompareMetrics, dict[str, np.ndarray] | None, str | None]],
) -> list[dict[str, Any]]:
    records = []
    for metrics, _arrays, error in results:
        record = metrics.to_dict()
        record["status"] = "ok" if error is None else error
        records.append(record)
    return records


def default_compare_output_root(model_name: str = "aurora_cahoy2010_replication_v0") -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "outputs"
        / model_name
        / "cahoy_compare"
    )


def ensure_reference_installed(reference_root: str | Path | None = None) -> Path:
    root = resolve_reference_root(reference_root)
    if list_reference_spectra(root):
        return root
    raise FileNotFoundError(
        f"Cahoy reference spectra not found under {root}. "
        "Run scripts/install_cahoy2010_reference.sh first."
    )
