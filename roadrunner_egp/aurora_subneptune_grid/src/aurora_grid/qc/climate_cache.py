from __future__ import annotations

import csv
import json
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import xarray as xr

from . import QCFlag, QCResult, combine_flags
from .science_checks import validate_science


_CACHE_NAME = re.compile(r"^climate_(\d+)\.npz$")
_CASE_NAME = re.compile(r"^climate_(\d+)_case\.pkl$")

CACHE_SUMMARY_COLUMNS = [
    "climate_group_index",
    "npz_path",
    "pkl_path",
    "status",
    "severity",
    "rerun_recommended",
    "fail_reasons",
    "warning_reasons",
    "npz_bytes",
    "pkl_bytes",
    "pkl_exists",
    "pkl_unpickle_checked",
    "pkl_unpickle_ok",
    "climate_converged",
    "n_levels",
    "pressure_min_bar",
    "pressure_max_bar",
    "temperature_min_k",
    "temperature_max_k",
    "max_temperature_jump_k",
    "max_abs_dtdlogp",
    "max_adiabat_ratio",
    "n_adiabat_violations",
    "max_abs_fnet_irfnet",
    "max_brightness_temperature_k",
    "bottom_temperature_k",
    "selected_ck_file",
    "schema_warnings",
    "open_error",
]

CACHE_FLAG_COLUMNS = [
    "climate_group_index",
    "npz_path",
    "pkl_path",
    "check",
    "severity",
    "message",
    "metric",
    "value",
]


@dataclass(frozen=True)
class CacheInventory:
    npz_paths: list[Path]
    orphan_pkl_paths: list[Path]


def climate_group_index(path: Path | str) -> int | None:
    match = _CACHE_NAME.match(Path(path).name) or _CASE_NAME.match(Path(path).name)
    return int(match.group(1)) if match else None


def climate_case_path(npz_path: Path | str) -> Path:
    path = Path(npz_path)
    return path.with_name(f"{path.stem}_case.pkl")


def discover_cache_files(cache_dir: Path | str, *, limit: int | None = None) -> CacheInventory:
    cache_dir = Path(cache_dir)
    npz_paths = sorted(
        (path for path in cache_dir.glob("climate_*.npz") if _CACHE_NAME.match(path.name)),
        key=lambda path: int(_CACHE_NAME.match(path.name).group(1)),  # type: ignore[union-attr]
    )
    pkl_paths = sorted(
        (path for path in cache_dir.glob("climate_*_case.pkl") if _CASE_NAME.match(path.name)),
        key=lambda path: int(_CASE_NAME.match(path.name).group(1)),  # type: ignore[union-attr]
    )
    npz_indices = {climate_group_index(path) for path in npz_paths}
    orphan_pkl_paths = [path for path in pkl_paths if climate_group_index(path) not in npz_indices]
    if limit is not None:
        npz_paths = npz_paths[: max(0, int(limit))]
    return CacheInventory(npz_paths=npz_paths, orphan_pkl_paths=orphan_pkl_paths)


def _as_numeric_array(value: Any) -> np.ndarray | None:
    if isinstance(value, dict) or value is None:
        return None
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    return array if array.ndim > 0 else None


def _diagnostic_dataset(pressure: np.ndarray, temperature: np.ndarray, diagnostics: dict[str, Any]) -> xr.Dataset:
    ds = xr.Dataset(
        data_vars={"temperature": ("level", np.asarray(temperature, dtype=float))},
        coords={"pressure": ("level", np.asarray(pressure, dtype=float))},
    )
    for name in ("qc_dtdp", "qc_adiabat", "qc_adiabat_pressure", "fnet_irfnet"):
        values = _as_numeric_array(diagnostics.get(name))
        if values is None:
            continue
        if values.size == pressure.size:
            dim = "level"
        elif values.size == max(0, pressure.size - 1):
            dim = "layer"
        else:
            dim = f"{name}_index"
        ds[name] = (dim, np.ravel(values))

    brightness = _as_numeric_array(diagnostics.get("qc_brightness_temperature"))
    if brightness is not None:
        ds["qc_brightness_temperature"] = ("brightness_wavelength", np.ravel(brightness))
    return ds


def _finite_range(values: np.ndarray) -> tuple[Any, Any]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return "", ""
    return float(np.nanmin(finite)), float(np.nanmax(finite))


def _profile_metrics(pressure: np.ndarray, temperature: np.ndarray, ds: xr.Dataset) -> dict[str, Any]:
    metrics: dict[str, Any] = {"n_levels": int(np.asarray(pressure).size)}
    metrics["pressure_min_bar"], metrics["pressure_max_bar"] = _finite_range(pressure)
    metrics["temperature_min_k"], metrics["temperature_max_k"] = _finite_range(temperature)
    if temperature.size > 1:
        metrics["max_temperature_jump_k"] = float(np.nanmax(np.abs(np.diff(temperature))))
    finite = np.isfinite(pressure) & np.isfinite(temperature) & (pressure > 0)
    if np.count_nonzero(finite) >= 3:
        with np.errstate(divide="ignore", invalid="ignore"):
            slopes = np.abs(np.diff(temperature[finite]) / np.diff(np.log10(pressure[finite])))
        slopes = slopes[np.isfinite(slopes)]
        if slopes.size:
            metrics["max_abs_dtdlogp"] = float(np.nanmax(slopes))

    if "qc_adiabat" in ds and "qc_dtdp" in ds and ds["qc_adiabat"].size == ds["qc_dtdp"].size:
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.asarray(ds["qc_dtdp"]) / np.asarray(ds["qc_adiabat"])
        finite_ratio = ratio[np.isfinite(ratio)]
        if finite_ratio.size:
            metrics["max_adiabat_ratio"] = float(np.nanmax(finite_ratio))
            metrics["n_adiabat_violations"] = int(np.count_nonzero(finite_ratio > 1.05))
    if "fnet_irfnet" in ds:
        values = np.abs(np.asarray(ds["fnet_irfnet"]))
        values = values[np.isfinite(values)]
        if values.size:
            metrics["max_abs_fnet_irfnet"] = float(np.nanmax(values))
    if "qc_brightness_temperature" in ds:
        values = np.asarray(ds["qc_brightness_temperature"])
        values = values[np.isfinite(values)]
        if values.size:
            metrics["max_brightness_temperature_k"] = float(np.nanmax(values))
    if temperature.size:
        metrics["bottom_temperature_k"] = float(np.ravel(temperature)[-1])
    return metrics


def _load_pickle(path: Path) -> tuple[bool, str]:
    try:
        with path.open("rb") as handle:
            pickle.load(handle)
    except Exception as exc:  # the exception type depends on the PICASO/pandas environment
        return False, f"pickle open failed: {type(exc).__name__}: {exc}"
    return True, ""


def validate_cache_file(path: Path | str, *, unpickle: bool = False) -> tuple[QCResult, dict[str, Any]]:
    path = Path(path)
    pkl_path = climate_case_path(path)
    index = climate_group_index(path)
    flags: list[QCFlag] = []
    metrics: dict[str, Any] = {
        "npz_bytes": path.stat().st_size if path.exists() else 0,
        "pkl_path": str(pkl_path),
        "pkl_exists": pkl_path.exists(),
        "pkl_bytes": pkl_path.stat().st_size if pkl_path.exists() else 0,
        "pkl_unpickle_checked": bool(unpickle and pkl_path.exists()),
        "pkl_unpickle_ok": "",
    }
    if not pkl_path.exists():
        flags.append(QCFlag("cache_pair", "fail", "matching PICASO case pickle is missing"))
    elif unpickle:
        ok, message = _load_pickle(pkl_path)
        metrics["pkl_unpickle_ok"] = ok
        if not ok:
            flags.append(QCFlag("pickle", "fail", message))

    try:
        with np.load(path, allow_pickle=False) as archive:
            required = {"pressure", "temperature", "metadata_json"}
            missing = sorted(required.difference(archive.files))
            if missing:
                raise ValueError(f"missing NPZ keys: {', '.join(missing)}")
            pressure = np.asarray(archive["pressure"], dtype=float)
            temperature = np.asarray(archive["temperature"], dtype=float)
            metadata = json.loads(str(archive["metadata_json"]))
    except Exception as exc:
        metrics["open_error"] = f"{type(exc).__name__}: {exc}"
        flags.append(QCFlag("open", "fail", f"cache open failed: {metrics['open_error']}"))
        result = QCResult(
            run_index=index if index is not None else "",
            run_id=f"climate_{index}" if index is not None else path.stem,
            file_path=str(path),
            storage_level="failed",
            flags=flags,
            metrics=metrics,
        )
        return result, _summary_row(result)

    metadata_index = metadata.get("climate_group_index")
    if index is not None and metadata_index is not None and int(metadata_index) != index:
        flags.append(
            QCFlag(
                "metadata",
                "fail",
                f"filename index {index} does not match metadata index {metadata_index}",
            )
        )
    diagnostics = metadata.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        flags.append(QCFlag("diagnostics", "fail", "metadata diagnostics mapping is missing"))

    converged = diagnostics.get("climate_converged")
    metrics["climate_converged"] = converged
    if converged in (False, 0, "0", "false", "False"):
        flags.append(QCFlag("convergence", "rerun_recommended", "PICASO climate did not converge"))
    elif converged is None:
        flags.append(QCFlag("convergence", "warning", "climate_converged diagnostic is missing"))

    schema_warnings = diagnostics.get("schema_warnings", [])
    if not isinstance(schema_warnings, list):
        schema_warnings = [schema_warnings]
    metrics["schema_warnings"] = " | ".join(str(item) for item in schema_warnings if item)
    if metrics["schema_warnings"]:
        flags.append(QCFlag("diagnostics", "warning", metrics["schema_warnings"]))
    metrics["selected_ck_file"] = metadata.get("selected_ck_file", "")

    ds = _diagnostic_dataset(pressure, temperature, diagnostics)
    flags = combine_flags(flags, validate_science(ds))
    metrics.update(_profile_metrics(pressure, temperature, ds))
    result = QCResult(
        run_index=index if index is not None else metadata_index or "",
        run_id=f"climate_{index}" if index is not None else path.stem,
        file_path=str(path),
        storage_level="climate_cache",
        flags=flags,
        metrics=metrics,
    )
    return result, _summary_row(result)


def _summary_row(result: QCResult) -> dict[str, Any]:
    row = {column: "" for column in CACHE_SUMMARY_COLUMNS}
    row.update(
        {
            "climate_group_index": result.run_index,
            "npz_path": result.file_path,
            "pkl_path": result.metrics.get("pkl_path", ""),
            "status": result.status,
            "severity": result.severity,
            "rerun_recommended": result.rerun_recommended,
            "fail_reasons": "; ".join(result.fail_reasons),
            "warning_reasons": "; ".join(result.warning_reasons),
        }
    )
    for key, value in result.metrics.items():
        if key in row:
            row[key] = value
    return row


def flag_rows(result: QCResult) -> list[dict[str, Any]]:
    return [
        {
            "climate_group_index": result.run_index,
            "npz_path": result.file_path,
            "pkl_path": result.metrics.get("pkl_path", ""),
            "check": flag.check,
            "severity": flag.severity,
            "message": flag.message,
            "metric": flag.metric or "",
            "value": "" if flag.value is None else flag.value,
        }
        for flag in result.flags
    ]


def validate_cache_paths(
    paths: Iterable[Path],
    *,
    unpickle_indices: set[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    unpickle_indices = unpickle_indices or set()
    for path in paths:
        index = climate_group_index(path)
        result, summary = validate_cache_file(path, unpickle=index in unpickle_indices)
        summaries.append(summary)
        flags.extend(flag_rows(result))
    return summaries, flags


def write_cache_reports(
    summaries: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    output_dir: Path | str,
) -> tuple[Path, Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = output_dir / "climate_cache_qc_summary.csv"
    flags_csv = output_dir / "climate_cache_qc_flags.csv"
    summary_json = output_dir / "climate_cache_qc_summary.json"
    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CACHE_SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(summaries)
    with flags_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CACHE_FLAG_COLUMNS)
        writer.writeheader()
        writer.writerows(flags)
    summary_json.write_text(json.dumps(summaries, indent=2, default=str), encoding="utf-8")
    rerun_indices = sorted(
        int(row["climate_group_index"])
        for row in summaries
        if bool(row.get("rerun_recommended"))
    )
    (output_dir / "rerun_climate_group_indices.txt").write_text(
        "".join(f"{index}\n" for index in rerun_indices),
        encoding="utf-8",
    )
    return summary_csv, flags_csv, summary_json
