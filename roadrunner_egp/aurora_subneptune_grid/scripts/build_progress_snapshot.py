#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "aurora_mpl_cache"))
import matplotlib
import yaml

matplotlib.use("Agg")

import matplotlib.pyplot as plt


SCRIPT_PATH = Path(__file__).resolve()
GRID_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = GRID_ROOT.parents[1]
DEFAULT_PARAMS_DIR = GRID_ROOT / "params"
DEFAULT_QC_REPORTS_DIR = GRID_ROOT / "data" / "qc" / "reports"
DEFAULT_JSON_OUT = REPO_ROOT / "docs" / "_static" / "progress_snapshot.json"
DEFAULT_FIGURE_OUT = REPO_ROOT / "docs" / "_static" / "progress_snapshot.svg"
DEFAULT_TIMESTAMP_OUT = REPO_ROOT / "docs" / "_static" / "progress_snapshot_timestamp.txt"

PARAMETER_KEYS = (
    "stars",
    "planet_radius_rearth",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "phase_deg",
)
PLANET_BULK_KEYS = ("planet_mass_mearth", "gravity_ms2")


@dataclass
class GridProgress:
    model_name: str
    config_name: str
    output_root: Path
    expected_rows: int
    expected_climate_groups: int
    stage1_completed: int
    stage2_completed: int
    qc_completed: int
    qc_status_counts: Counter[str]

    @property
    def stage1_pct(self) -> float:
        return _pct(self.stage1_completed, self.expected_climate_groups)

    @property
    def stage2_pct(self) -> float:
        return _pct(self.stage2_completed, self.expected_rows)

    @property
    def qc_pct(self) -> float:
        return _pct(self.qc_completed, self.expected_rows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "config_name": self.config_name,
            "output_root": _format_path_for_snapshot(self.output_root),
            "expected": {
                "stage1_climate_groups": self.expected_climate_groups,
                "stage2_rows": self.expected_rows,
                "qc_rows": self.expected_rows,
            },
            "completed": {
                "stage1_climate_groups": self.stage1_completed,
                "stage2_rows": self.stage2_completed,
                "qc_rows": self.qc_completed,
            },
            "percent": {
                "stage1_climate_groups": round(self.stage1_pct, 3),
                "stage2_rows": round(self.stage2_pct, 3),
                "qc_rows": round(self.qc_pct, 3),
            },
            "qc_status_counts": dict(self.qc_status_counts),
        }


def _pct(done: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return 100.0 * float(done) / float(total)


def _format_path_for_snapshot(path_value: Path) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Aurora docs progress snapshot and chart.")
    parser.add_argument("--params-dir", default=str(DEFAULT_PARAMS_DIR), help="Directory with grid YAML configs.")
    parser.add_argument("--qc-reports-dir", default=str(DEFAULT_QC_REPORTS_DIR), help="Directory with QC CSV reports.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT), help="Output progress JSON path.")
    parser.add_argument("--figure-out", default=str(DEFAULT_FIGURE_OUT), help="Output progress SVG/PNG path.")
    parser.add_argument(
        "--timestamp-out",
        default=str(DEFAULT_TIMESTAMP_OUT),
        help="Output text file containing snapshot timestamp.",
    )
    return parser.parse_args()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse to a mapping.")
    return data


def _param_len(config: dict[str, Any], key: str) -> int:
    value = config.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list in config {config.get('model_name', '<unknown>')}")
    return len(value)


def _cartesian_parameter_keys(config: dict[str, Any]) -> tuple[str, ...]:
    planet_bulk_key = next((key for key in PLANET_BULK_KEYS if key in config), None)
    if planet_bulk_key is None:
        raise ValueError(
            "Cartesian grid config must define planet_mass_mearth or gravity_ms2"
        )
    return (*PARAMETER_KEYS, planet_bulk_key)


def _expected_rows(config: dict[str, Any]) -> int:
    total = 1
    for key in _cartesian_parameter_keys(config):
        total *= _param_len(config, key)
    return _subtract_unsupported_chemistry(config, total)


def _expected_climate_groups(config: dict[str, Any]) -> int:
    total_rows = _expected_rows(config)
    spectrum_axes = config.get("climate_spectrum_axes", ["phase_deg"])
    if not isinstance(spectrum_axes, list) or not spectrum_axes:
        raise ValueError("climate_spectrum_axes must be a non-empty list")
    spectra_per_climate = 1
    for key in spectrum_axes:
        if key not in PARAMETER_KEYS:
            raise ValueError(f"Unsupported climate spectrum axis: {key}")
        spectra_per_climate *= _param_len(config, key)
    if total_rows % spectra_per_climate:
        raise ValueError(
            f"Expected row count {total_rows} is not divisible by {spectra_per_climate} spectra per climate"
        )
    return total_rows // spectra_per_climate


def _subtract_unsupported_chemistry(config: dict[str, Any], total: int) -> int:

    unsupported_pairs = config.get("unsupported_chemistry_pairs", [])
    if unsupported_pairs in (None, []):
        return int(total)
    if not isinstance(unsupported_pairs, list):
        raise ValueError("unsupported_chemistry_pairs must be a list")

    metallicities = set(config.get("metallicity_xsolar", []))
    c_to_o_values = set(config.get("c_to_o_xsolar", []))
    unique_pairs: set[tuple[Any, Any]] = set()
    for pair in unsupported_pairs:
        if not isinstance(pair, dict):
            raise ValueError("each unsupported chemistry pair must be a mapping")
        metallicity = pair.get("metallicity_xsolar")
        c_to_o = pair.get("c_to_o_xsolar")
        if metallicity not in metallicities or c_to_o not in c_to_o_values:
            raise ValueError(
                "unsupported chemistry pair is outside the configured axes: "
                f"metallicity_xsolar={metallicity}, c_to_o_xsolar={c_to_o}"
            )
        unique_pairs.add((metallicity, c_to_o))

    chemistry_pair_count = _param_len(config, "metallicity_xsolar") * _param_len(
        config, "c_to_o_xsolar"
    )
    if len(unique_pairs) >= chemistry_pair_count:
        raise ValueError("unsupported chemistry pairs exclude the entire chemistry grid")

    groups_per_chemistry_pair = total // chemistry_pair_count
    return int(total - len(unique_pairs) * groups_per_chemistry_pair)


def _is_aurora_model(model_name: str) -> bool:
    return model_name.startswith("aurora_") or model_name in {
        "smoke_test_aurora_subneptune",
        "hpc_validation_aurora_subneptune",
    }


def _expected_counts(config: dict[str, Any]) -> tuple[int, int]:
    if all(key in config for key in PARAMETER_KEYS) and any(
        key in config for key in PLANET_BULK_KEYS
    ):
        return _expected_rows(config), _expected_climate_groups(config)

    factorization = config.get("factorization")
    if isinstance(factorization, dict):
        expected_spectra = factorization.get("expected_spectra")
        expected_climates = factorization.get("expected_climates")
        if expected_spectra is not None and expected_climates is not None:
            return int(expected_spectra), int(expected_climates)

    # Cahoy et al. 2010 replication config uses a dedicated manifest builder.
    if str(config.get("model_name")) == "aurora_cahoy2010_replication_v0":
        return 304, 16

    raise ValueError(f"Unsupported config shape for model {config.get('model_name')}")


def _count_stage_files(config: dict[str, Any], output_root: Path) -> tuple[int, int]:
    cache_root = config.get("cache_root")
    if cache_root:
        climate_dir = _resolve_output_root(str(cache_root))
    else:
        climate_dir = output_root / "climate_cache"
    spectra_dir = output_root / "nc"
    stage1_completed = len(list(climate_dir.glob("*.npz"))) if climate_dir.exists() else 0
    stage2_completed = len(list(spectra_dir.glob("*.nc"))) if spectra_dir.exists() else 0
    return stage1_completed, stage2_completed


def _collect_qc_rows(qc_reports_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not qc_reports_dir.exists():
        return rows
    for csv_path in sorted(qc_reports_dir.glob("*.csv")):
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                continue
            if "status" not in reader.fieldnames:
                continue
            for row in reader:
                rows.append(row)
    return rows


def _match_qc_rows(
    model_name: str,
    output_root: Path,
    qc_rows: list[dict[str, str]],
) -> tuple[int, Counter[str]]:
    path_seen: set[str] = set()
    run_seen: set[str] = set()
    status_counts: Counter[str] = Counter()
    output_marker = output_root.as_posix().strip("/")
    model_marker = f"/outputs/{model_name}/"

    for row in qc_rows:
        file_path = (row.get("file_path") or "").replace("\\", "/")
        status = (row.get("status") or "").strip().lower()
        run_id = (row.get("run_id") or "").strip()
        if not status:
            continue

        matched = False
        if file_path and model_marker in file_path:
            matched = True
        elif file_path and output_marker and output_marker in file_path:
            matched = True
        if not matched:
            continue

        dedupe_key = ""
        if file_path:
            dedupe_key = f"file:{file_path}"
            if dedupe_key in path_seen:
                continue
            path_seen.add(dedupe_key)
        elif run_id:
            dedupe_key = f"run:{run_id}"
            if dedupe_key in run_seen:
                continue
            run_seen.add(dedupe_key)

        status_counts[status] += 1

    return sum(status_counts.values()), status_counts


def _iter_grid_configs(params_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    configs: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(params_dir.glob("*.yaml")):
        config = _load_yaml(path)
        if "model_name" not in config or "output_root" not in config:
            continue
        model_name = str(config["model_name"])
        if not _is_aurora_model(model_name):
            continue
        try:
            _expected_counts(config)
        except ValueError:
            continue
        configs.append((path, config))
    return configs


def _resolve_output_root(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _build_progress_rows(params_dir: Path, qc_reports_dir: Path) -> list[GridProgress]:
    qc_rows = _collect_qc_rows(qc_reports_dir)
    progress_rows: list[GridProgress] = []
    for config_path, config in _iter_grid_configs(params_dir):
        model_name = str(config["model_name"])
        output_root = _resolve_output_root(str(config["output_root"]))
        expected_rows, expected_climate_groups = _expected_counts(config)
        stage1_completed, stage2_completed = _count_stage_files(config, output_root)
        qc_completed, qc_status_counts = _match_qc_rows(model_name, output_root, qc_rows)

        progress_rows.append(
            GridProgress(
                model_name=model_name,
                config_name=config_path.name,
                output_root=output_root,
                expected_rows=expected_rows,
                expected_climate_groups=expected_climate_groups,
                stage1_completed=stage1_completed,
                stage2_completed=stage2_completed,
                qc_completed=qc_completed,
                qc_status_counts=qc_status_counts,
            )
        )
    progress_rows.sort(key=lambda row: row.expected_rows, reverse=True)
    return progress_rows


def _write_chart(rows: list[GridProgress], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "No Aurora grid configs found", ha="center", va="center", fontsize=12)
        ax.axis("off")
        fig.savefig(out_path, bbox_inches="tight")
        plt.close(fig)
        return

    labels = [row.model_name for row in rows]
    y_positions = list(range(len(rows)))
    stage1 = [row.stage1_pct for row in rows]
    stage2 = [row.stage2_pct for row in rows]
    qc = [row.qc_pct for row in rows]

    fig_height = max(4.0, 0.8 * len(rows) + 2.0)
    fig, ax = plt.subplots(figsize=(13.5, fig_height))
    bar_h = 0.22

    ax.barh([y + bar_h for y in y_positions], stage1, height=bar_h, color="#4c78a8", label="Stage 1 Climate")
    ax.barh(y_positions, stage2, height=bar_h, color="#59a14f", label="Stage 2 Spectra")
    ax.barh([y - bar_h for y in y_positions], qc, height=bar_h, color="#f28e2b", label="QC Evaluated")

    for y, row in zip(y_positions, rows):
        ax.text(
            min(row.stage1_pct + 1.0, 99.0),
            y + bar_h,
            f"{row.stage1_completed}/{row.expected_climate_groups}",
            va="center",
            fontsize=8,
        )
        ax.text(
            min(row.stage2_pct + 1.0, 99.0),
            y,
            f"{row.stage2_completed}/{row.expected_rows}",
            va="center",
            fontsize=8,
        )
        ax.text(
            min(row.qc_pct + 1.0, 99.0),
            y - bar_h,
            f"{row.qc_completed}/{row.expected_rows}",
            va="center",
            fontsize=8,
        )

    ax.set_xlim(0, 100)
    ax.set_xlabel("Completion (%)")
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_title("Aurora Grid Progress: Stage 1 / Stage 2 / QC")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _write_snapshot(
    rows: list[GridProgress],
    json_out: Path,
    timestamp_out: Path,
    params_dir: Path,
    qc_reports_dir: Path,
) -> None:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    snapshot = {
        "generated_at_utc": generated_at,
        "sources": {
            "params_dir": _format_path_for_snapshot(params_dir),
            "qc_reports_dir": _format_path_for_snapshot(qc_reports_dir),
        },
        "summary": {
            "grid_count": len(rows),
            "expected_stage1_climate_groups": int(sum(row.expected_climate_groups for row in rows)),
            "expected_stage2_rows": int(sum(row.expected_rows for row in rows)),
            "completed_stage1_climate_groups": int(sum(row.stage1_completed for row in rows)),
            "completed_stage2_rows": int(sum(row.stage2_completed for row in rows)),
            "completed_qc_rows": int(sum(row.qc_completed for row in rows)),
        },
        "grids": [row.as_dict() for row in rows],
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

    timestamp_out.parent.mkdir(parents=True, exist_ok=True)
    timestamp_out.write_text(f"Last snapshot update (UTC): {generated_at}\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    params_dir = Path(args.params_dir)
    qc_reports_dir = Path(args.qc_reports_dir)
    json_out = Path(args.json_out)
    figure_out = Path(args.figure_out)
    timestamp_out = Path(args.timestamp_out)

    rows = _build_progress_rows(params_dir, qc_reports_dir)
    _write_snapshot(rows, json_out, timestamp_out, params_dir, qc_reports_dir)
    _write_chart(rows, figure_out)

    print(f"grids: {len(rows)}")
    print(f"json: {json_out}")
    print(f"figure: {figure_out}")
    print(f"timestamp: {timestamp_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
