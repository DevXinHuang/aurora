from __future__ import annotations

import csv
import contextlib
import importlib.metadata
import json
import os
import pickle
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import xarray as xr

from . import QCFlag, QCResult, SEVERITY_ORDER
from .climate_cache import climate_case_path, climate_group_index
from .science_checks import BRIGHTNESS_BOTTOM_FRACTION, validate_science


EXPECTED_BRIGHTNESS_POINTS = 196
SIDECAR_SCHEMA_VERSION = 1
SIDECAR_REQUIRED_ARRAYS = {
    "pressure",
    "temperature",
    "qc_dtdp",
    "qc_adiabat",
    "qc_adiabat_pressure",
    "fnet_irfnet",
    "brightness_wavelength_um",
    "brightness_temperature_k",
    "metadata_json",
}

PARAMETER_COLUMNS = [
    "climate_group_index",
    "star_teff_k",
    "star_radius_rsun",
    "planet_radius_rearth",
    "planet_mass_mearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_model",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "semi_major_au",
    "equilibrium_temperature_k",
    "picaso_tint_k",
]

BRIGHTNESS_SUMMARY_COLUMNS = [
    "climate_group_index",
    "npz_path",
    "pkl_path",
    "sidecar_path",
    "status",
    "severity",
    "rerun_recommended",
    "fail_reasons",
    "warning_reasons",
    "climate_converged",
    "n_levels",
    "n_brightness_points",
    "brightness_min_wavelength_um",
    "brightness_max_wavelength_um",
    "brightness_min_temperature_k",
    "brightness_max_temperature_k",
    "bottom_temperature_k",
    "max_brightness_bottom_ratio",
    "brightness_depth_rerun",
    "max_adiabat_ratio",
    "n_adiabat_violations",
    "max_abs_fnet_irfnet",
    "opacity_filename",
    "picaso_version",
]

BRIGHTNESS_FLAG_COLUMNS = [
    "climate_group_index",
    "npz_path",
    "pkl_path",
    "sidecar_path",
    "check",
    "severity",
    "message",
    "metric",
    "value",
]


@dataclass(frozen=True)
class SidecarValidation:
    valid: bool
    message: str = ""


_OPACITY_CACHE: dict[str, Any] = {}


def sidecar_path(sidecar_dir: Path | str, index: int) -> Path:
    return Path(sidecar_dir) / f"climate_{index:06d}_diagnostics.npz"


def _array(value: Any) -> np.ndarray:
    if value is None or isinstance(value, dict):
        return np.asarray([], dtype=float)
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return np.asarray([], dtype=float)
    return np.ravel(result)


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def _typed_parameter(value: str) -> Any:
    if value == "":
        return ""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def load_parameter_records(path: Path | str) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(PARAMETER_COLUMNS).difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"parameter table is missing columns: {', '.join(sorted(missing))}")
        for raw in reader:
            index = int(raw["climate_group_index"])
            if index in records:
                raise ValueError(f"duplicate parameter record for climate {index}")
            records[index] = {name: _typed_parameter(raw.get(name, "")) for name in PARAMETER_COLUMNS}
    return records


def validate_parameter_inventory(records: Mapping[int, Any], expected_indices: set[int]) -> None:
    actual = set(records)
    missing = sorted(expected_indices.difference(actual))
    extra = sorted(actual.difference(expected_indices))
    if missing or extra:
        raise ValueError(
            f"parameter inventory mismatch: missing={len(missing)} extra={len(extra)}; "
            f"missing_sample={missing[:5]} extra_sample={extra[:5]}"
        )


def _source_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _sidecar_metadata(
    *,
    index: int,
    npz_path: Path,
    pkl_path: Path,
    opacity_path: Path,
    parameters: Mapping[str, Any],
    original_metadata: Mapping[str, Any],
    converged: Any,
    bottom_temperature: float,
    max_brightness: float,
    picaso_version: str,
) -> dict[str, Any]:
    ratio = max_brightness / bottom_temperature if bottom_temperature > 0 else float("nan")
    return {
        "sidecar_schema_version": SIDECAR_SCHEMA_VERSION,
        "climate_group_index": index,
        "parameters": {key: _json_value(value) for key, value in parameters.items()},
        "climate_converged": _json_value(converged),
        "bottom_temperature_k": bottom_temperature,
        "max_brightness_temperature_k": max_brightness,
        "max_brightness_bottom_ratio": ratio,
        "brightness_depth_fraction": BRIGHTNESS_BOTTOM_FRACTION,
        "brightness_depth_rerun": bool(max_brightness >= BRIGHTNESS_BOTTOM_FRACTION * bottom_temperature),
        "picaso_version": picaso_version,
        "opacity_filename": opacity_path.name,
        "opacity_path": str(opacity_path.resolve()),
        "source_npz": _source_signature(npz_path),
        "source_pkl": _source_signature(pkl_path),
        "original_selected_ck_file": original_metadata.get("selected_ck_file", ""),
        "original_schema_warnings": original_metadata.get("diagnostics", {}).get("schema_warnings", []),
    }


def _first_scalar(value: Any) -> float:
    array = np.asarray(value, dtype=float).ravel()
    if not array.size:
        raise ValueError("expected a numeric scalar")
    return float(array[0])


def _get_opacity(opacity_path: Path) -> Any:
    key = str(opacity_path.resolve())
    opacity = _OPACITY_CACHE.get(key)
    if opacity is None:
        from picaso import justdoit as jdi

        opacity = jdi.opannection(
            ck_db=key,
            wave_range=[0.3, 15.0],
            method="preweighted",
        )
        _OPACITY_CACHE[key] = opacity
    return opacity


def validate_sidecar(
    path: Path | str,
    *,
    source_npz: Path | None = None,
    source_pkl: Path | None = None,
    expected_points: int = EXPECTED_BRIGHTNESS_POINTS,
    require_qc: bool = False,
) -> SidecarValidation:
    path = Path(path)
    if not path.is_file():
        return SidecarValidation(False, "sidecar is missing")
    try:
        with np.load(path, allow_pickle=False) as archive:
            missing = SIDECAR_REQUIRED_ARRAYS.difference(archive.files)
            if missing:
                return SidecarValidation(False, f"missing arrays: {', '.join(sorted(missing))}")
            wavelength = np.asarray(archive["brightness_wavelength_um"], dtype=float).ravel()
            brightness = np.asarray(archive["brightness_temperature_k"], dtype=float).ravel()
            pressure = np.asarray(archive["pressure"], dtype=float).ravel()
            temperature = np.asarray(archive["temperature"], dtype=float).ravel()
            metadata = json.loads(str(archive["metadata_json"]))
    except Exception as exc:
        return SidecarValidation(False, f"open failed: {type(exc).__name__}: {exc}")
    if wavelength.size != expected_points or brightness.size != expected_points:
        return SidecarValidation(False, f"brightness length is {wavelength.size}/{brightness.size}, expected {expected_points}")
    if wavelength.size != brightness.size:
        return SidecarValidation(False, "brightness wavelength and temperature lengths differ")
    if not np.all(np.isfinite(wavelength)) or not np.all(wavelength > 0):
        return SidecarValidation(False, "brightness wavelength is nonfinite or nonpositive")
    if not np.all(np.isfinite(brightness)) or not np.all(brightness > 0):
        return SidecarValidation(False, "brightness temperature is nonfinite or nonpositive")
    if pressure.size != temperature.size or pressure.size < 2:
        return SidecarValidation(False, "P-T arrays are missing or mismatched")
    if metadata.get("sidecar_schema_version") != SIDECAR_SCHEMA_VERSION:
        return SidecarValidation(False, "sidecar schema version differs")
    if require_qc:
        qc = metadata.get("qc")
        if not isinstance(qc, dict) or not isinstance(qc.get("flags"), list) or not qc.get("status"):
            return SidecarValidation(False, "final QC status and flags are missing from sidecar metadata")
    index = climate_group_index(source_npz) if source_npz is not None else None
    if index is not None and int(metadata.get("climate_group_index", -1)) != index:
        return SidecarValidation(False, "sidecar climate index differs from source")
    for label, source in (("source_npz", source_npz), ("source_pkl", source_pkl)):
        if source is None:
            continue
        if not source.is_file():
            return SidecarValidation(False, f"{label} is missing")
        signature = metadata.get(label, {})
        current = _source_signature(source)
        if signature.get("bytes") != current["bytes"] or signature.get("mtime_ns") != current["mtime_ns"]:
            return SidecarValidation(False, f"{label} changed after sidecar creation")
    return SidecarValidation(True)


def attach_qc_metadata(path: Path | str, result: QCResult) -> None:
    path = Path(path)
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: np.asarray(archive[name]) for name in archive.files if name != "metadata_json"}
        metadata = json.loads(str(archive["metadata_json"]))
    metadata["qc"] = {
        "status": result.status,
        "severity": result.severity,
        "rerun_recommended": result.rerun_recommended,
        "flags": [
            {
                "check": flag.check,
                "severity": flag.severity,
                "message": flag.message,
                "metric": flag.metric or "",
                "value": _json_value(flag.value),
            }
            for flag in result.flags
        ],
    }
    arrays["metadata_json"] = np.asarray(json.dumps(metadata, sort_keys=True))
    temporary = path.with_suffix(".qc.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)


def recompute_brightness_sidecar(
    npz_path: Path | str,
    output_path: Path | str,
    parameters: Mapping[str, Any],
    opacity_dir: Path | str,
    *,
    resume: bool = True,
) -> dict[str, Any]:
    npz_path = Path(npz_path)
    output_path = Path(output_path)
    pkl_path = climate_case_path(npz_path)
    index = climate_group_index(npz_path)
    if index is None:
        raise ValueError(f"not a climate cache filename: {npz_path}")
    if not pkl_path.is_file():
        raise FileNotFoundError(f"missing paired pickle: {pkl_path}")
    if resume:
        validation = validate_sidecar(output_path, source_npz=npz_path, source_pkl=pkl_path)
        if validation.valid:
            return {"climate_group_index": index, "status": "skipped", "sidecar_path": str(output_path)}

    with np.load(npz_path, allow_pickle=False) as archive:
        pressure = np.asarray(archive["pressure"], dtype=float).ravel()
        temperature = np.asarray(archive["temperature"], dtype=float).ravel()
        original_metadata = json.loads(str(archive["metadata_json"]))
    diagnostics = original_metadata.get("diagnostics", {})
    opacity_name = Path(str(original_metadata.get("selected_ck_file", ""))).name
    if not opacity_name:
        raise ValueError(f"selected_ck_file is missing for climate {index}")
    opacity_path = Path(opacity_dir) / opacity_name
    if not opacity_path.is_file():
        raise FileNotFoundError(f"required opacity is missing: {opacity_path}")

    with pkl_path.open("rb") as handle:
        case = pickle.load(handle)
    opacity = _get_opacity(opacity_path)
    star = case.inputs.get("star", {})
    from astropy import units as u

    # PICASO prints one cloud-thinning line per spectrum for fractional-cloud
    # cases. Suppress that library chatter while allowing exceptions to
    # propagate to the per-case error report.
    with Path(os.devnull).open("w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink):
        case.star(
            opacity,
            temp=_first_scalar(star["temp"]),
            metal=_first_scalar(star["metal"]),
            logg=_first_scalar(star["logg"]),
            radius=_first_scalar(star["radius"]),
            radius_unit=u.cm,
            semi_major=_first_scalar(star["semi_major"]),
            semi_major_unit=u.cm,
        )
        case.phase_angle(0.0, num_gangle=5, num_tangle=1)
        spectrum = case.spectrum(opacity, calculation="thermal", as_dict=True, full_output=True)
        from picaso import justplotit as jpi

        brightness = np.asarray(jpi.brightness_temperature(spectrum, plot=False), dtype=float).ravel()
    wavenumber = np.asarray(spectrum["wavenumber"], dtype=float).ravel()
    with np.errstate(divide="ignore", invalid="ignore"):
        wavelength = 1.0e4 / wavenumber
    if brightness.size != EXPECTED_BRIGHTNESS_POINTS or wavelength.size != EXPECTED_BRIGHTNESS_POINTS:
        raise ValueError(
            f"climate {index} returned {wavelength.size}/{brightness.size} brightness points; "
            f"expected {EXPECTED_BRIGHTNESS_POINTS}"
        )
    if not np.all(np.isfinite(brightness)) or not np.all(np.isfinite(wavelength)):
        raise ValueError(f"climate {index} returned nonfinite brightness arrays")

    picaso_version = importlib.metadata.version("picaso")
    bottom_temperature = float(temperature[-1])
    max_brightness = float(np.max(brightness))
    metadata = _sidecar_metadata(
        index=index,
        npz_path=npz_path,
        pkl_path=pkl_path,
        opacity_path=opacity_path,
        parameters=parameters,
        original_metadata=original_metadata,
        converged=diagnostics.get("climate_converged"),
        bottom_temperature=bottom_temperature,
        max_brightness=max_brightness,
        picaso_version=picaso_version,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.npz")
    np.savez_compressed(
        temporary,
        pressure=pressure,
        temperature=temperature,
        qc_dtdp=_array(diagnostics.get("qc_dtdp", diagnostics.get("dtdp"))),
        qc_adiabat=_array(diagnostics.get("qc_adiabat", diagnostics.get("adiabat"))),
        qc_adiabat_pressure=_array(diagnostics.get("qc_adiabat_pressure", diagnostics.get("adiabat_pressure"))),
        fnet_irfnet=_array(diagnostics.get("fnet_irfnet")),
        brightness_wavelength_um=wavelength,
        brightness_temperature_k=brightness,
        metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)),
    )
    os.replace(temporary, output_path)
    validation = validate_sidecar(output_path, source_npz=npz_path, source_pkl=pkl_path)
    if not validation.valid:
        output_path.unlink(missing_ok=True)
        raise ValueError(f"new sidecar failed validation: {validation.message}")
    return {"climate_group_index": index, "status": "written", "sidecar_path": str(output_path)}


def _sidecar_dataset(archive: Any) -> xr.Dataset:
    pressure = np.asarray(archive["pressure"], dtype=float).ravel()
    temperature = np.asarray(archive["temperature"], dtype=float).ravel()
    ds = xr.Dataset(
        data_vars={"temperature": ("level", temperature)},
        coords={"pressure": ("level", pressure)},
    )
    for name in ("qc_dtdp", "qc_adiabat", "qc_adiabat_pressure", "fnet_irfnet"):
        values = np.asarray(archive[name], dtype=float).ravel()
        if values.size:
            dim = "level" if values.size == pressure.size else "layer" if values.size == pressure.size - 1 else f"{name}_index"
            ds[name] = (dim, values)
    wavelength = np.asarray(archive["brightness_wavelength_um"], dtype=float).ravel()
    brightness = np.asarray(archive["brightness_temperature_k"], dtype=float).ravel()
    ds = ds.assign_coords(brightness_wavelength_um=("brightness_wavelength", wavelength))
    ds["qc_brightness_temperature"] = ("brightness_wavelength", brightness)
    return ds


def validate_brightness_case(
    sidecar: Path | str,
    *,
    source_npz: Path | None = None,
    source_pkl: Path | None = None,
) -> tuple[QCResult, dict[str, Any], list[dict[str, Any]]]:
    sidecar = Path(sidecar)
    flags: list[QCFlag] = []
    metadata: dict[str, Any] = {}
    ds: xr.Dataset | None = None
    structural = validate_sidecar(sidecar, source_npz=source_npz, source_pkl=source_pkl)
    if not structural.valid:
        flags.append(QCFlag("brightness_arrays", "fail", structural.message))
    try:
        with np.load(sidecar, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata_json"]))
            ds = _sidecar_dataset(archive)
    except Exception as exc:
        if structural.valid:
            flags.append(QCFlag("sidecar", "fail", f"sidecar open failed: {type(exc).__name__}: {exc}"))
    index = int(metadata.get("climate_group_index", climate_group_index(source_npz) or -1))
    converged = metadata.get("climate_converged")
    if converged in (False, 0, "0", "false", "False"):
        flags.append(QCFlag("convergence", "rerun_recommended", "PICASO climate did not converge; diagnostics use the last cached P-T iterate"))
    elif converged is None:
        flags.append(QCFlag("convergence", "warning", "climate_converged diagnostic is missing"))
    schema_warnings = metadata.get("original_schema_warnings", [])
    if schema_warnings:
        flags.append(QCFlag("diagnostics", "warning", " | ".join(str(item) for item in schema_warnings)))
    if ds is not None:
        flags.extend(validate_science(ds))

    metrics: dict[str, Any] = {
        "pkl_path": str(source_pkl or ""),
        "sidecar_path": str(sidecar),
        "climate_converged": converged,
        "opacity_filename": metadata.get("opacity_filename", ""),
        "picaso_version": metadata.get("picaso_version", ""),
    }
    if ds is not None:
        p = np.asarray(ds["pressure"], dtype=float)
        t = np.asarray(ds["temperature"], dtype=float)
        w = np.asarray(ds["brightness_wavelength_um"], dtype=float)
        b = np.asarray(ds["qc_brightness_temperature"], dtype=float)
        metrics.update(
            {
                "n_levels": p.size,
                "n_brightness_points": b.size,
                "brightness_min_wavelength_um": float(np.nanmin(w)),
                "brightness_max_wavelength_um": float(np.nanmax(w)),
                "brightness_min_temperature_k": float(np.nanmin(b)),
                "brightness_max_temperature_k": float(np.nanmax(b)),
                "bottom_temperature_k": float(t[-1]),
                "max_brightness_bottom_ratio": float(np.nanmax(b) / t[-1]),
            }
        )
        metrics["brightness_depth_rerun"] = bool(
            metrics["brightness_max_temperature_k"] >= BRIGHTNESS_BOTTOM_FRACTION * metrics["bottom_temperature_k"]
        )
        if "qc_adiabat" in ds and "qc_dtdp" in ds and ds["qc_adiabat"].size == ds["qc_dtdp"].size:
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.asarray(ds["qc_dtdp"]) / np.asarray(ds["qc_adiabat"])
            finite = ratio[np.isfinite(ratio)]
            if finite.size:
                metrics["max_adiabat_ratio"] = float(np.max(finite))
                metrics["n_adiabat_violations"] = int(np.count_nonzero(finite > 1.05))
        if "fnet_irfnet" in ds:
            finite_fnet = np.abs(np.asarray(ds["fnet_irfnet"], dtype=float))
            finite_fnet = finite_fnet[np.isfinite(finite_fnet)]
            if finite_fnet.size:
                metrics["max_abs_fnet_irfnet"] = float(np.max(finite_fnet))

    result = QCResult(
        run_index=index,
        run_id=f"climate_{index}",
        file_path=str(source_npz or ""),
        storage_level="brightness_sidecar",
        flags=flags,
        metrics=metrics,
    )
    summary = {column: "" for column in BRIGHTNESS_SUMMARY_COLUMNS}
    summary.update(
        {
            "climate_group_index": index,
            "npz_path": str(source_npz or ""),
            "pkl_path": str(source_pkl or ""),
            "sidecar_path": str(sidecar),
            "status": result.status,
            "severity": result.severity,
            "rerun_recommended": result.rerun_recommended,
            "fail_reasons": "; ".join(result.fail_reasons),
            "warning_reasons": "; ".join(result.warning_reasons),
        }
    )
    for key, value in metrics.items():
        if key in summary:
            summary[key] = value
    flag_rows = [
        {
            "climate_group_index": index,
            "npz_path": str(source_npz or ""),
            "pkl_path": str(source_pkl or ""),
            "sidecar_path": str(sidecar),
            "check": flag.check,
            "severity": flag.severity,
            "message": flag.message,
            "metric": flag.metric or "",
            "value": "" if flag.value is None else flag.value,
        }
        for flag in result.flags
    ]
    return result, summary, flag_rows


def write_brightness_reports(
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
        writer = csv.DictWriter(handle, fieldnames=BRIGHTNESS_SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(summaries)
    with flags_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BRIGHTNESS_FLAG_COLUMNS)
        writer.writeheader()
        writer.writerows(flags)
    summary_json.write_text(json.dumps(summaries, indent=2, default=str), encoding="utf-8")
    rerun = sorted(int(row["climate_group_index"]) for row in summaries if bool(row["rerun_recommended"]))
    (output_dir / "rerun_climate_group_indices.txt").write_text("".join(f"{index}\n" for index in rerun), encoding="utf-8")
    return summary_csv, flags_csv, summary_json


def _status_rank(status: str) -> int:
    return SEVERITY_ORDER.get(status, 0)


def create_survival_reports(
    old_rows: Iterable[Mapping[str, Any]],
    new_rows: Iterable[Mapping[str, Any]],
    new_flags: Iterable[Mapping[str, Any]],
    output_dir: Path | str,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    old = {int(row["climate_group_index"]): str(row["status"]) for row in old_rows}
    new = {int(row["climate_group_index"]): str(row["status"]) for row in new_rows}
    if old.keys() != new.keys():
        raise ValueError("old/new QC inventories differ")
    statuses = ["pass", "warning", "fail", "rerun_recommended"]
    transition = Counter((old[index], new[index]) for index in old)
    transition_path = output_dir / "old_to_new_status_transition.csv"
    with transition_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["old_status", *statuses])
        for old_status in statuses:
            writer.writerow([old_status, *(transition[(old_status, new_status)] for new_status in statuses)])

    total = len(old)
    old_counts = Counter(old.values())
    new_counts = Counter(new.values())
    old_strict = old_counts["pass"]
    new_strict = new_counts["pass"]
    old_usable = old_counts["pass"] + old_counts["warning"]
    new_usable = new_counts["pass"] + new_counts["warning"]
    comparison_rows = []
    for metric, before, after in (
        ("strict_pass", old_strict, new_strict),
        ("usable_pass_plus_warning", old_usable, new_usable),
    ):
        before_rate = 100.0 * before / total
        after_rate = 100.0 * after / total
        comparison_rows.append(
            {
                "metric": metric,
                "before_count": before,
                "after_count": after,
                "count_change": after - before,
                "before_percent": before_rate,
                "after_percent": after_rate,
                "percentage_point_change": after_rate - before_rate,
            }
        )
    comparison_path = output_dir / "survival_rate_comparison.csv"
    with comparison_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison_rows[0]))
        writer.writeheader()
        writer.writerows(comparison_rows)

    brightness_flagged = {
        int(row["climate_group_index"])
        for row in new_flags
        if str(row.get("check")) in {"brightness_temperature", "brightness_arrays"}
        and str(row.get("severity")) in {"fail", "rerun_recommended"}
    }
    downgraded = sorted(index for index in brightness_flagged if _status_rank(new[index]) > _status_rank(old[index]))
    downgraded_path = output_dir / "newly_downgraded_by_brightness.csv"
    with downgraded_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["climate_group_index", "old_status", "new_status"])
        writer.writeheader()
        writer.writerows(
            {"climate_group_index": index, "old_status": old[index], "new_status": new[index]}
            for index in downgraded
        )
    result = {
        "total_climates": total,
        "old_status_counts": dict(old_counts),
        "new_status_counts": dict(new_counts),
        "survival": comparison_rows,
        "newly_downgraded_by_brightness_count": len(downgraded),
        "transition_csv": transition_path.name,
        "comparison_csv": comparison_path.name,
        "newly_downgraded_csv": downgraded_path.name,
    }
    (output_dir / "survival_analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
