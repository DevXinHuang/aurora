from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from . import QCResult, combine_flags
from .schema_checks import array_values, classify_storage, has_pressure, has_wavelength, manifest_row, pressure_dependent_vars, validate_schema
from .science_checks import validate_science


SUMMARY_COLUMNS = [
    "run_index",
    "run_id",
    "file_path",
    "status",
    "storage_level",
    "severity",
    "fail_reasons",
    "warning_reasons",
    "rerun_recommended",
    "has_wavelength",
    "has_pressure",
    "has_temperature",
    "n_chemistry_vars",
    "has_cloud_opd",
    "has_cloud_ssa",
    "has_cloud_asy",
    "has_reflected_planet_star_flux_ratio",
    "has_geometric_albedo",
    "wavelength_min",
    "wavelength_max",
    "pressure_min",
    "pressure_max",
    "temperature_min",
    "temperature_max",
    "max_adiabat_ratio",
    "n_adiabat_violations",
    "max_abs_fnet_irfnet",
    "max_brightness_temperature",
    "bottom_temperature",
]

FLAG_COLUMNS = [
    "run_index",
    "run_id",
    "file_path",
    "check",
    "severity",
    "message",
    "metric",
    "value",
    "diagnostic_plot_path",
    "spectrum_plot_path",
]


def _range_metrics(ds: xr.Dataset, name: str) -> tuple[Any, Any]:
    values = array_values(ds, name)
    if values is None:
        return "", ""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return "", ""
    return float(np.nanmin(finite)), float(np.nanmax(finite))


def _qc_metrics(ds: xr.Dataset) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if "qc_adiabat" in ds and "qc_dtdp" in ds:
        adiabat = array_values(ds, "qc_adiabat")
        dtdp = array_values(ds, "qc_dtdp")
        if adiabat is not None and dtdp is not None:
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = dtdp / adiabat
            finite = ratio[np.isfinite(ratio)]
            if finite.size:
                metrics["max_adiabat_ratio"] = float(np.nanmax(finite))
                metrics["n_adiabat_violations"] = int(np.count_nonzero(finite > 1.05))
    if "qc_brightness_temperature" in ds:
        values = array_values(ds, "qc_brightness_temperature")
        if values is not None:
            finite = values[np.isfinite(values)]
            if finite.size:
                metrics["max_brightness_temperature"] = float(np.nanmax(finite))
    values = array_values(ds, "temperature")
    if values is not None and values.size:
        metrics["bottom_temperature"] = float(np.ravel(values)[-1])
    fnet = array_values(ds, "fnet_irfnet")
    if fnet is not None:
        finite = np.abs(fnet[np.isfinite(fnet)])
        if finite.size:
            metrics["max_abs_fnet_irfnet"] = float(np.nanmax(finite))
    for name in ("max_abs_fnet_irfnet",):
        if name in ds.attrs:
            metrics[name] = ds.attrs[name]
    return metrics


def validate_dataset(ds: xr.Dataset, path: Path | str = "", row: dict[str, Any] | None = None) -> QCResult:
    row = row or manifest_row(ds)
    schema_flags = validate_schema(ds, row)
    science_flags = validate_science(ds, row)
    flags = combine_flags(schema_flags, science_flags)
    storage_level = classify_storage(ds, flags)
    metrics = _qc_metrics(ds)
    return QCResult(
        run_index=ds.attrs.get("run_index", row.get("run_index", "")),
        run_id=str(ds.attrs.get("run_id", row.get("run_id", ""))),
        file_path=str(path),
        storage_level=storage_level,
        flags=flags,
        metrics=metrics,
    )


def validate_file(path: Path | str) -> QCResult:
    path = Path(path)
    try:
        with xr.open_dataset(path) as ds:
            return validate_dataset(ds, path)
    except Exception as exc:
        return QCResult(
            file_path=str(path),
            storage_level="failed",
            flags=[],
            metrics={"open_error": str(exc)},
        )


def result_to_row(result: QCResult, ds: xr.Dataset | None = None) -> dict[str, Any]:
    row = {column: "" for column in SUMMARY_COLUMNS}
    row.update(
        {
            "run_index": result.run_index,
            "run_id": result.run_id,
            "file_path": result.file_path,
            "status": result.status,
            "storage_level": result.storage_level,
            "severity": result.severity,
            "fail_reasons": "; ".join(result.fail_reasons),
            "warning_reasons": "; ".join(result.warning_reasons),
            "rerun_recommended": bool(result.rerun_recommended),
        }
    )
    if "open_error" in result.metrics:
        row["status"] = "fail"
        row["severity"] = "fail"
        row["storage_level"] = "failed"
        row["fail_reasons"] = f"open failed: {result.metrics['open_error']}"
        row["rerun_recommended"] = True
    if ds is not None:
        row["has_wavelength"] = has_wavelength(ds)
        row["has_pressure"] = has_pressure(ds)
        row["has_temperature"] = array_values(ds, "temperature") is not None
        row["n_chemistry_vars"] = len(pressure_dependent_vars(ds))
        row["has_cloud_opd"] = "cloud_optical_depth" in ds.data_vars or "opd" in ds.data_vars
        row["has_cloud_ssa"] = "single_scattering_albedo" in ds.data_vars or "ssa" in ds.data_vars
        row["has_cloud_asy"] = "asymmetry_factor" in ds.data_vars or "asy" in ds.data_vars
        row["has_reflected_planet_star_flux_ratio"] = "reflected_planet_star_flux_ratio" in ds.data_vars
        row["has_geometric_albedo"] = "geometric_albedo" in ds.data_vars
        row["wavelength_min"], row["wavelength_max"] = _range_metrics(ds, "wavelength")
        row["pressure_min"], row["pressure_max"] = _range_metrics(ds, "pressure")
        row["temperature_min"], row["temperature_max"] = _range_metrics(ds, "temperature")
    for key, value in result.metrics.items():
        if key in row:
            row[key] = value
    return row


def validate_paths(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            with xr.open_dataset(path) as ds:
                result = validate_dataset(ds, path)
                rows.append(result_to_row(result, ds))
        except Exception as exc:
            result = QCResult(file_path=str(path), storage_level="failed", metrics={"open_error": str(exc)})
            rows.append(result_to_row(result, None))
    return rows


def flags_to_rows(
    result: QCResult,
    plot_paths_by_check: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    plot_paths_by_check = plot_paths_by_check or {}
    flags = result.flags
    if not flags and "open_error" in result.metrics:
        from . import QCFlag

        flags = [QCFlag("open", "fail", f"open failed: {result.metrics['open_error']}")]

    rows: list[dict[str, Any]] = []
    for flag in flags:
        plot_paths = plot_paths_by_check.get(flag.check, {})
        rows.append(
            {
                "run_index": result.run_index,
                "run_id": result.run_id,
                "file_path": result.file_path,
                "check": flag.check,
                "severity": flag.severity,
                "message": flag.message,
                "metric": flag.metric or "",
                "value": "" if flag.value is None else flag.value,
                "diagnostic_plot_path": plot_paths.get("diagnostic", ""),
                "spectrum_plot_path": plot_paths.get("spectrum", ""),
            }
        )
    return rows


def write_summary(rows: list[dict[str, Any]], csv_path: Path, json_path: Path | None = None) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(rows, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_flags(rows: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FLAG_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
