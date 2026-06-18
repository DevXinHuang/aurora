from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from . import QCFlag
from .schema_checks import array_values, manifest_row


GROUP_KEYS = [
    "star_teff_k",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_fraction",
    "fsed",
    "phase_deg",
]


def _row_value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key, "")
    try:
        return round(float(value), 8)
    except Exception:
        return str(value)


def _group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(_row_value(row, key) for key in GROUP_KEYS)


def _sort_value(row: dict[str, Any]) -> float:
    for key in ("insolation_searth", "picaso_tint_k"):
        try:
            return float(row[key])
        except Exception:
            continue
    return 0.0


def _interp_profile(pressure: np.ndarray, temperature: np.ndarray, logp_grid: np.ndarray) -> np.ndarray:
    order = np.argsort(np.log10(pressure))
    return np.interp(logp_grid, np.log10(pressure)[order], temperature[order])


def find_crossings(paths: list[Path]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        try:
            with xr.open_dataset(path) as ds:
                row = manifest_row(ds)
                row.setdefault("run_id", ds.attrs.get("run_id", path.stem))
                row.setdefault("run_index", ds.attrs.get("run_index", ""))
                pressure = array_values(ds, "pressure")
                temperature = array_values(ds, "temperature")
                if pressure is None or temperature is None or pressure.size != temperature.size:
                    continue
                finite = np.isfinite(pressure) & np.isfinite(temperature) & (pressure > 0)
                if np.count_nonzero(finite) < 3:
                    continue
                groups[_group_key(row)].append(
                    {
                        "path": str(path),
                        "row": row,
                        "pressure": pressure[finite],
                        "temperature": temperature[finite],
                    }
                )
        except Exception:
            continue

    findings: list[dict[str, Any]] = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda item: _sort_value(item["row"]))
        p_min = max(float(np.nanmin(member["pressure"])) for member in members)
        p_max = min(float(np.nanmax(member["pressure"])) for member in members)
        if not (p_min > 0 and p_max > p_min):
            continue
        logp_grid = np.linspace(np.log10(p_min), np.log10(p_max), 160)
        profiles = [_interp_profile(member["pressure"], member["temperature"], logp_grid) for member in members]
        for left, right, left_profile, right_profile in zip(members, members[1:], profiles, profiles[1:], strict=False):
            diff = right_profile - left_profile
            if np.any(np.diff(np.signbit(diff))):
                findings.append(
                    {
                        "check": "crossing",
                        "severity": "warning",
                        "message": "neighboring PT profiles cross",
                        "left_run_id": left["row"].get("run_id", ""),
                        "right_run_id": right["row"].get("run_id", ""),
                        "left_file": left["path"],
                        "right_file": right["path"],
                        "group_key": json.dumps(dict(zip(GROUP_KEYS, key, strict=False))),
                    }
                )
    return findings


def crossing_flags(paths: list[Path]) -> list[QCFlag]:
    return [QCFlag("crossing", "warning", f"{row['left_run_id']} crosses {row['right_run_id']}") for row in find_crossings(paths)]


def write_crossing_summary(findings: list[dict[str, Any]], out_csv: Path) -> None:
    if not findings:
        return
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    columns = ["check", "severity", "message", "left_run_id", "right_run_id", "left_file", "right_file", "group_key"]
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(findings)


def make_crossing_overlay_plot(finding: dict[str, Any], out_png: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 7), constrained_layout=True)
    for label_key, file_key in (("left_run_id", "left_file"), ("right_run_id", "right_file")):
        with xr.open_dataset(finding[file_key]) as ds:
            pressure = array_values(ds, "pressure")
            temperature = array_values(ds, "temperature")
            if pressure is None or temperature is None:
                continue
            finite = np.isfinite(pressure) & np.isfinite(temperature) & (pressure > 0)
            ax.plot(temperature[finite], pressure[finite], label=str(finding.get(label_key, file_key)))
    ax.set_xlabel("Temperature [K]")
    ax.set_ylabel("Pressure [bar]")
    ax.set_yscale("log")
    ax.invert_yaxis()
    ax.legend()
    ax.set_title("PT Crossing Check")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    return out_png
