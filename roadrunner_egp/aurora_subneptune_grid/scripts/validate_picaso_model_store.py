#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import sys
import typing
from pathlib import Path
from typing import Any

if not hasattr(typing, "Self"):
    try:
        from typing_extensions import Self
    except Exception:
        Self = typing.TypeVar("Self")
    typing.Self = Self

import numpy as np
import xarray as xr


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


DEFAULT_VALIDATION_CSV = GRID_ROOT / "data" / "validation" / "picaso_model_store_validation.csv"

OUTPUT_COLUMNS = [
    "run_index",
    "run_id",
    "file_path",
    "status",
    "storage_level",
    "fail_reasons",
    "warning_reasons",
    "has_wavelength",
    "has_pressure",
    "has_temperature",
    "n_chemistry_vars",
    "has_cloud_opd",
    "has_cloud_ssa",
    "has_cloud_asy",
    "has_fpfs_reflected",
    "has_fpfs_reflection",
    "has_albedo",
    "wavelength_min",
    "wavelength_max",
]

REQUIRED_ATTRS = [
    "author",
    "contact",
    "code",
    "model_name",
    "run_id",
    "run_index",
    "created_utc",
    "git_commit",
    "picaso_version",
    "aurora_schema_version",
    "planet_params",
    "stellar_params",
    "orbit_params",
    "cld_params",
    "grid_params",
    "source_manifest_row",
]

CHEMISTRY_NAMES = {
    "H2O",
    "CH4",
    "CO2",
    "CO",
    "NH3",
    "Na",
    "K",
    "TiO",
    "VO",
    "FeH",
    "H2S",
    "HCN",
    "PH3",
    "H2",
    "He",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Aurora PICASO model-store NetCDF outputs.")
    parser.add_argument("--output-root", required=True, help="Directory containing per-run .nc files.")
    parser.add_argument("--out", default=str(DEFAULT_VALIDATION_CSV), help="Validation CSV path.")
    return parser.parse_args()


def _manifest_row(dataset: xr.Dataset) -> dict[str, Any]:
    try:
        return json.loads(str(dataset.attrs.get("source_manifest_row", "{}")))
    except Exception:
        return {}


def _array_values(dataset: xr.Dataset, name: str) -> np.ndarray | None:
    if name not in dataset:
        return None
    try:
        return np.asarray(dataset[name].values, dtype=float)
    except Exception:
        return None


def _mostly_between(values: np.ndarray, lo: float, hi: float, tolerance: float = 1.0e-6) -> bool:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return False
    in_range = (finite >= lo - tolerance) & (finite <= hi + tolerance)
    return float(np.count_nonzero(in_range)) / float(finite.size) >= 0.95


def _storage_level(dataset: xr.Dataset, failed: bool) -> str:
    if failed:
        return "failed"
    attr_level = str(dataset.attrs.get("storage_level", "")).strip()
    if attr_level in {"spectrum_only", "picaso_reusable", "aurora_extended"}:
        return attr_level
    if "pressure" in dataset and "temperature" in dataset:
        return "aurora_extended"
    if "pressure" in dataset:
        return "picaso_reusable"
    return "spectrum_only"


def validate_file(path: Path) -> dict[str, Any]:
    fail_reasons: list[str] = []
    warning_reasons: list[str] = []
    row: dict[str, Any] = {
        "run_index": "",
        "run_id": "",
        "file_path": str(path),
        "status": "failed",
        "storage_level": "failed",
        "fail_reasons": "",
        "warning_reasons": "",
        "has_wavelength": False,
        "has_pressure": False,
        "has_temperature": False,
        "n_chemistry_vars": 0,
        "has_cloud_opd": False,
        "has_cloud_ssa": False,
        "has_cloud_asy": False,
        "has_fpfs_reflected": False,
        "has_fpfs_reflection": False,
        "has_albedo": False,
        "wavelength_min": "",
        "wavelength_max": "",
    }

    try:
        with xr.open_dataset(path) as dataset:
            manifest_row = _manifest_row(dataset)
            row["run_index"] = dataset.attrs.get("run_index", manifest_row.get("run_index", ""))
            row["run_id"] = dataset.attrs.get("run_id", manifest_row.get("run_id", ""))

            row["has_wavelength"] = "wavelength" in dataset.coords or "wavelength" in dataset.dims
            row["has_pressure"] = "pressure" in dataset.coords or "pressure" in dataset.dims
            row["has_temperature"] = "temperature" in dataset.data_vars
            row["has_fpfs_reflected"] = "fpfs_reflected" in dataset.data_vars
            row["has_fpfs_reflection"] = "fpfs_reflection" in dataset.data_vars
            row["has_albedo"] = "albedo" in dataset.data_vars
            row["has_cloud_opd"] = "opd" in dataset.data_vars
            row["has_cloud_ssa"] = "ssa" in dataset.data_vars
            row["has_cloud_asy"] = "asy" in dataset.data_vars

            if not row["has_wavelength"]:
                fail_reasons.append("missing wavelength coordinate")
            else:
                wavelength = _array_values(dataset, "wavelength")
                if wavelength is None or wavelength.ndim != 1:
                    fail_reasons.append("wavelength is not 1D numeric")
                elif not np.all(np.isfinite(wavelength)):
                    fail_reasons.append("wavelength contains nonfinite values")
                elif wavelength.size > 1 and not np.all(np.diff(wavelength) > 0):
                    fail_reasons.append("wavelength is not strictly increasing")
                else:
                    row["wavelength_min"] = float(np.nanmin(wavelength))
                    row["wavelength_max"] = float(np.nanmax(wavelength))

            if not row["has_albedo"]:
                fail_reasons.append("missing albedo")
            if not (row["has_fpfs_reflected"] or row["has_fpfs_reflection"]):
                fail_reasons.append("missing reflected fpfs variable")
            if row["has_pressure"] and not row["has_temperature"]:
                warning_reasons.append("pressure exists without temperature")

            for spectrum_name in ("fpfs_reflected", "fpfs_reflection", "albedo"):
                values = _array_values(dataset, spectrum_name)
                if values is None:
                    continue
                if not np.all(np.isfinite(values)):
                    fail_reasons.append(f"{spectrum_name} contains nonfinite values")
                if not np.any(np.asarray(values) != 0.0):
                    fail_reasons.append(f"{spectrum_name} is all zeros")
            albedo = _array_values(dataset, "albedo")
            if albedo is not None and not _mostly_between(albedo, 0.0, 1.0):
                warning_reasons.append("albedo mostly outside [0, 1]")

            chemistry_vars = [name for name in dataset.data_vars if name in CHEMISTRY_NAMES]
            row["n_chemistry_vars"] = len(chemistry_vars)
            for name in chemistry_vars:
                values = _array_values(dataset, name)
                if values is None:
                    warning_reasons.append(f"{name} chemistry not numeric")
                elif not np.all(np.isfinite(values)):
                    fail_reasons.append(f"{name} chemistry contains nonfinite values")
                elif np.nanmin(values) < -1.0e-12:
                    fail_reasons.append(f"{name} chemistry contains negative values")

            for cloud_name in ("opd", "ssa", "asy"):
                if cloud_name not in dataset.data_vars:
                    continue
                dims = dataset[cloud_name].dims
                if not dims:
                    warning_reasons.append(f"{cloud_name} has no dimensions")
                if not all(dim in dataset.sizes for dim in dims):
                    fail_reasons.append(f"{cloud_name} has invalid dimensions")

            missing_attrs = [name for name in REQUIRED_ATTRS if name not in dataset.attrs]
            if missing_attrs:
                fail_reasons.append(f"missing attrs: {'|'.join(missing_attrs)}")

            row["storage_level"] = _storage_level(dataset, bool(fail_reasons))
    except Exception as exc:
        fail_reasons.append(f"open failed: {exc}")

    row["status"] = "failed" if fail_reasons else ("warning" if warning_reasons else "passed")
    if row["status"] == "failed":
        row["storage_level"] = "failed"
    row["fail_reasons"] = "; ".join(fail_reasons)
    row["warning_reasons"] = "; ".join(warning_reasons)
    return row


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    rows = [
        validate_file(path)
        for path in sorted(output_root.rglob("*.nc"))
        if not path.name.endswith(".tmp.nc")
    ]

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    failed = sum(1 for row in rows if row["status"] == "failed")
    warnings = sum(1 for row in rows if row["status"] == "warning")
    print(f"validated_files: {len(rows)}")
    print(f"failed: {failed}")
    print(f"warnings: {warnings}")
    print(f"validation_csv: {output_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
