#!/usr/bin/env python3
"""Audit Aurora climate-cache coverage and render a collaborator-ready progress chart."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = (
    ROOT
    / "roadrunner_egp"
    / "aurora_subneptune_grid"
    / "params"
    / "aurora_subneptune_v1_dhuang.yaml"
)
DEFAULT_CACHE = (
    ROOT
    / "roadrunner_egp"
    / "aurora_subneptune_grid"
    / "outputs"
    / "aurora_subneptune_v1_dhuang"
    / "climate_cache"
)
DEFAULT_OUT = Path(__file__).resolve().parent

NPZ_RE = re.compile(r"^climate_(\d+)\.npz$")
PKL_RE = re.compile(r"^climate_(\d+)_case\.pkl$")

BLUE = "#3166D5"
BLUE_DARK = "#17458F"
BLUE_LIGHT = "#DCE7F8"
BLUE_OPEN = "#F1F5FC"
INK = "#172033"
MUTED = "#667085"
GRID = "#D7DDE8"
WHITE = "#FFFFFF"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Config did not parse to a mapping: {path}")
    return config


def climate_axes(config: dict[str, Any]) -> list[tuple[str, str, list[Any]]]:
    stars = config["stars"]
    star_labels = [
        f"{float(star['teff_k']):g} K / {float(star['radius_rsun']):g} R_sun"
        for star in stars
    ]
    if "planet_mass_mearth" in config:
        planet_key = "planet_mass_mearth"
        planet_label = "Planet mass"
    else:
        planet_key = "gravity_ms2"
        planet_label = "Gravity"
    return [
        ("stars", "Stellar anchor", star_labels),
        ("planet_radius_rearth", "Planet radius", list(config["planet_radius_rearth"])),
        (planet_key, planet_label, list(config[planet_key])),
        ("metallicity_xsolar", "Metallicity", list(config["metallicity_xsolar"])),
        ("c_to_o_xsolar", "C/O", list(config["c_to_o_xsolar"])),
        ("kzz_cm2_s", "Kzz", list(config["kzz_cm2_s"])),
        ("cloud_fraction", "Cloud fraction", list(config["cloud_fraction"])),
        ("fsed", "f_sed", list(config["fsed"])),
        ("insolation_searth", "Insolation", list(config["insolation_searth"])),
    ]


def file_indices(cache_dir: Path, pattern: re.Pattern[str], glob_pattern: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for path in cache_dir.glob(glob_pattern):
        match = pattern.match(path.name)
        if match:
            result[int(match.group(1))] = path
    return result


def converged_flag(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return bool(value == 1)
    return str(value).strip().lower() in {"1", "true", "yes"}


def audit_npz(
    npz_paths: dict[int, Path], expected_total: int
) -> tuple[set[int], list[dict[str, Any]], dict[str, int]]:
    usable: set[int] = set()
    problems: list[dict[str, Any]] = []
    counts = {
        "opened": 0,
        "valid_schema": 0,
        "metadata_index_match": 0,
        "finite_profiles": 0,
        "converged": 0,
        "out_of_range": 0,
    }
    required = {"pressure", "temperature", "metadata_json"}

    for filename_index, path in sorted(npz_paths.items()):
        issue: list[str] = []
        if not 0 <= filename_index < expected_total:
            counts["out_of_range"] += 1
            issue.append("filename index outside configured grid")
        try:
            with np.load(path, allow_pickle=False) as archive:
                counts["opened"] += 1
                missing = sorted(required.difference(archive.files))
                if missing:
                    issue.append(f"missing keys: {', '.join(missing)}")
                    raise ValueError(issue[-1])
                counts["valid_schema"] += 1
                pressure = np.asarray(archive["pressure"], dtype=float)
                temperature = np.asarray(archive["temperature"], dtype=float)
                metadata = json.loads(str(archive["metadata_json"]))
        except Exception as exc:
            problems.append(
                {
                    "climate_group_index": filename_index,
                    "path": str(path),
                    "issues": issue or [f"open failed: {type(exc).__name__}: {exc}"],
                }
            )
            continue

        metadata_index = metadata.get("climate_group_index")
        if metadata_index is None or int(metadata_index) != filename_index:
            issue.append(f"metadata index {metadata_index!r} does not match filename")
        else:
            counts["metadata_index_match"] += 1

        profiles_ok = (
            pressure.ndim == 1
            and temperature.ndim == 1
            and pressure.size == temperature.size
            and pressure.size > 1
            and np.all(np.isfinite(pressure))
            and np.all(np.isfinite(temperature))
            and np.all(pressure > 0)
        )
        if profiles_ok:
            counts["finite_profiles"] += 1
        else:
            issue.append("pressure/temperature profiles are not matching finite 1-D arrays")

        diagnostics = metadata.get("diagnostics")
        convergence_value = diagnostics.get("climate_converged") if isinstance(diagnostics, dict) else None
        if converged_flag(convergence_value):
            counts["converged"] += 1
        else:
            issue.append(f"climate_converged is {convergence_value!r}")

        if not issue and 0 <= filename_index < expected_total:
            usable.add(filename_index)
        else:
            problems.append(
                {
                    "climate_group_index": filename_index,
                    "path": str(path),
                    "issues": issue,
                }
            )
    return usable, problems, counts


def value_label(axis_key: str, value: Any) -> str:
    if axis_key == "stars":
        return str(value)
    number = float(value)
    if axis_key == "planet_radius_rearth":
        return f"{number:g} R_earth"
    if axis_key == "planet_mass_mearth":
        return f"{number:g} M_earth"
    if axis_key == "gravity_ms2":
        return f"{number:g} m/s^2"
    if axis_key in {"metallicity_xsolar", "c_to_o_xsolar"}:
        return f"{number:g}x solar"
    if axis_key == "kzz_cm2_s":
        return f"{number:.0e} cm^2/s"
    if axis_key == "cloud_fraction":
        return f"{number:g}"
    if axis_key == "fsed":
        return f"{number:g}"
    if axis_key == "insolation_searth":
        return f"{number:g} S_earth"
    return str(value)


def build_coverage_rows(
    usable_indices: set[int], axes: list[tuple[str, str, list[Any]]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], np.ndarray]:
    dims = tuple(len(values) for _, _, values in axes)
    expected_total = math.prod(dims)
    index_array = np.asarray(sorted(usable_indices), dtype=int)
    if index_array.size:
        coordinates = np.column_stack(np.unravel_index(index_array, dims))
    else:
        coordinates = np.empty((0, len(dims)), dtype=int)

    level_rows: list[dict[str, Any]] = []
    reach_rows: list[dict[str, Any]] = []
    for axis_position, (axis_key, axis_label, values) in enumerate(axes):
        expected_per_level = expected_total // len(values)
        touched = 0
        for value_position, value in enumerate(values):
            completed = int(np.count_nonzero(coordinates[:, axis_position] == value_position))
            touched += int(completed > 0)
            level_rows.append(
                {
                    "axis_key": axis_key,
                    "axis_label": axis_label,
                    "value_index": value_position,
                    "value": value_label(axis_key, value),
                    "completed_climates": completed,
                    "expected_climates": expected_per_level,
                    "completion_percent": round(100.0 * completed / expected_per_level, 6),
                    "touched": completed > 0,
                }
            )
        reach_rows.append(
            {
                "axis_key": axis_key,
                "axis_label": axis_label,
                "values_touched": touched,
                "values_total": len(values),
                "reach_percent": round(100.0 * touched / len(values), 6),
            }
        )
    return level_rows, reach_rows, coordinates


def render_chart(summary: dict[str, Any], reach_rows: list[dict[str, Any]], level_rows: list[dict[str, Any]], out_dir: Path) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "text.color": INK,
            "axes.labelcolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": INK,
        }
    )
    fig = plt.figure(figsize=(14, 9), facecolor=WHITE)
    grid = fig.add_gridspec(
        nrows=3,
        ncols=2,
        height_ratios=[1.05, 3.9, 0.65],
        width_ratios=[1.18, 1.0],
        hspace=0.48,
        wspace=0.38,
        left=0.08,
        right=0.95,
        top=0.82,
        bottom=0.08,
    )

    fig.text(0.08, 0.935, "Aurora climate-grid parameter-space coverage", fontsize=22, fontweight="bold", color=INK)
    fig.text(
        0.08,
        0.898,
        f"Validated converged climate caches • {summary['snapshot_utc']} • configured climate grid = {summary['expected_climate_groups']:,} combinations",
        fontsize=10.5,
        color=MUTED,
    )

    # Small single-root research blossom locked to the header's top-right corner.
    center_x, center_y, radius = 0.965, 0.938, 0.010
    for angle in np.linspace(0, 2 * np.pi, 6)[:-1]:
        fig.add_artist(
            Circle(
                (center_x + radius * np.cos(angle), center_y + radius * np.sin(angle)),
                0.0047,
                transform=fig.transFigure,
                facecolor=BLUE_LIGHT,
                edgecolor=BLUE_DARK,
                linewidth=0.7,
            )
        )
    fig.add_artist(Circle((center_x, center_y), 0.0042, transform=fig.transFigure, facecolor=BLUE, edgecolor=BLUE_DARK, linewidth=0.7))

    ax_overall = fig.add_subplot(grid[0, :])
    ax_overall.set_axis_off()
    overall_pct = summary["usable_coverage_percent"]
    x0, y0, width, height = 0.0, 0.30, 1.0, 0.30
    ax_overall.add_patch(
        FancyBboxPatch(
            (x0, y0), width, height, boxstyle="round,pad=0,rounding_size=0.04", facecolor=BLUE_OPEN, edgecolor=GRID, linewidth=1.0
        )
    )
    ax_overall.add_patch(
        FancyBboxPatch(
            (x0, y0), width * overall_pct / 100.0, height, boxstyle="round,pad=0,rounding_size=0.04", facecolor=BLUE, edgecolor=BLUE_DARK, linewidth=0.8
        )
    )
    ax_overall.text(0.0, 0.84, "Overall climate-combination completion", fontsize=12, fontweight="bold", va="center")
    ax_overall.text(1.0, 0.84, f"{overall_pct:.2f}%", fontsize=20, fontweight="bold", ha="right", va="center", color=BLUE_DARK)
    ax_overall.text(
        0.0,
        0.03,
        f"{summary['usable_climate_groups']:,} validated, converged NPZ caches / {summary['expected_climate_groups']:,} expected climate groups",
        fontsize=10,
        color=MUTED,
        va="bottom",
    )
    ax_overall.set_xlim(0, 1)
    ax_overall.set_ylim(0, 1)

    ax_reach = fig.add_subplot(grid[1, 0])
    labels = [row["axis_label"] for row in reach_rows][::-1]
    percents = [row["reach_percent"] for row in reach_rows][::-1]
    ratios = [f"{row['values_touched']}/{row['values_total']}" for row in reach_rows][::-1]
    y = np.arange(len(labels))
    ax_reach.barh(y, [100] * len(y), color=BLUE_OPEN, edgecolor=GRID, height=0.58, linewidth=0.7)
    ax_reach.barh(y, percents, color=BLUE, edgecolor=BLUE_DARK, height=0.58, linewidth=0.7)
    for yi, pct, ratio in zip(y, percents, ratios):
        ax_reach.text(min(pct + 2.0, 103.0), yi, f"{ratio} ({pct:.0f}%)", va="center", fontsize=9, color=INK)
    ax_reach.set_yticks(y, labels)
    ax_reach.set_xlim(0, 116)
    ax_reach.set_xticks([0, 25, 50, 75, 100])
    ax_reach.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax_reach.grid(axis="x", color=GRID, linewidth=0.7, alpha=0.75)
    ax_reach.set_axisbelow(True)
    ax_reach.text(
        0,
        1.10,
        "Discrete parameter values reached",
        transform=ax_reach.transAxes,
        fontsize=12,
        fontweight="bold",
        color=INK,
        va="bottom",
    )
    ax_reach.text(
        0,
        1.035,
        "A value counts as reached after at least one validated climate at that value.",
        transform=ax_reach.transAxes,
        fontsize=9,
        color=MUTED,
        va="bottom",
    )
    for spine in ax_reach.spines.values():
        spine.set_visible(False)
    ax_reach.tick_params(axis="y", length=0)
    ax_reach.tick_params(axis="x", length=0)

    ax_star = fig.add_subplot(grid[1, 1])
    star_rows = [row for row in level_rows if row["axis_key"] == "stars"]
    star_labels = [row["value"].replace(" R_sun", " R☉") for row in star_rows][::-1]
    star_pct = [row["completion_percent"] for row in star_rows][::-1]
    star_counts = [row["completed_climates"] for row in star_rows][::-1]
    y2 = np.arange(len(star_labels))
    ax_star.barh(y2, [100] * len(y2), color=BLUE_OPEN, edgecolor=GRID, height=0.56, linewidth=0.7)
    ax_star.barh(y2, star_pct, color=BLUE, edgecolor=BLUE_DARK, height=0.56, linewidth=0.7)
    for yi, pct, count in zip(y2, star_pct, star_counts):
        ax_star.text(min(pct + 2.0, 103.0), yi, f"{pct:.1f}%  ({count:,})", va="center", fontsize=9, color=INK)
    ax_star.set_yticks(y2, star_labels)
    ax_star.set_xlim(0, 116)
    ax_star.set_xticks([0, 25, 50, 75, 100])
    ax_star.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax_star.grid(axis="x", color=GRID, linewidth=0.7, alpha=0.75)
    ax_star.set_axisbelow(True)
    ax_star.text(
        0,
        1.10,
        "Completion within each stellar anchor",
        transform=ax_star.transAxes,
        fontsize=12,
        fontweight="bold",
        color=INK,
        va="bottom",
    )
    ax_star.text(
        0,
        1.035,
        "Each star has 36,000 expected climate combinations.",
        transform=ax_star.transAxes,
        fontsize=9,
        color=MUTED,
        va="bottom",
    )
    for spine in ax_star.spines.values():
        spine.set_visible(False)
    ax_star.tick_params(axis="y", length=0)
    ax_star.tick_params(axis="x", length=0)

    ax_note = fig.add_subplot(grid[2, :])
    ax_note.set_axis_off()
    pairing_pct = 100.0 * summary["paired_npz_pkl"] / summary["npz_files"] if summary["npz_files"] else 0.0
    note = (
        f"File inventory: {summary['npz_files']:,} NPZ + {summary['pkl_files']:,} PKL; "
        f"{summary['paired_npz_pkl']:,} matched pairs ({pairing_pct:.1f}% of NPZ).  "
        f"{summary['problem_npz_files']:,} paired caches are present but non-converged.  "
        f"Index frontier: 0–{summary['highest_usable_index']:,}, with {summary['missing_within_frontier']:,} missing usable climates inside that range.  "
        "Phase angle is excluded because it reuses the converged climate profile."
    )
    ax_note.text(0, 0.64, note, fontsize=9.5, color=MUTED, va="center", wrap=True)
    ax_note.text(
        0,
        0.08,
        "Source: local aurora_subneptune_v1_dhuang climate_cache and configured Cartesian grid. PKL files were checked for pairing and size, not unpickled.",
        fontsize=8.5,
        color=MUTED,
        va="bottom",
    )

    for suffix in ("png", "svg"):
        fig.savefig(out_dir / f"climate_parameter_coverage.{suffix}", dpi=180, facecolor=WHITE)
    plt.close(fig)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_summary_markdown(summary: dict[str, Any], reach_rows: list[dict[str, Any]], out_dir: Path) -> None:
    reached = {row["axis_label"]: f"{row['values_touched']}/{row['values_total']}" for row in reach_rows}
    lines = [
        "# Climate parameter-space coverage snapshot",
        "",
        f"Snapshot: {summary['snapshot_utc']}",
        "",
        f"- Overall validated climate coverage: **{summary['usable_climate_groups']:,} / {summary['expected_climate_groups']:,} ({summary['usable_coverage_percent']:.2f}%)**.",
        f"- File inventory: **{summary['npz_files']:,} NPZ** and **{summary['pkl_files']:,} PKL**, with **{summary['paired_npz_pkl']:,} matched pairs**.",
        f"- NPZ validation: **{summary['usable_climate_groups']:,} usable**, **{summary['problem_npz_files']:,} with a validation or convergence issue**.",
        f"- The usable index frontier is **0–{summary['highest_usable_index']:,}**, with **{summary['missing_within_frontier']:,} missing climates inside that range**.",
        f"- Stellar coverage is currently concentrated at the first anchor: **{summary['first_star_completed']:,} / {summary['expected_per_star']:,} ({summary['first_star_completion_percent']:.2f}%)** for {summary['first_star_label']}.",
        "",
        "Discrete parameter values reached (at least one validated climate):",
        "",
    ]
    lines.extend(f"- {label}: {ratio}" for label, ratio in reached.items())
    lines.extend(
        [
            "",
            "Interpretation: the run has reached every configured value on eight of the nine climate axes, but it has not yet reached the other four stellar anchors. Reaching a value does not mean all cross-combinations at that value are complete.",
            "",
            "Phase angle is not a climate axis in this count: all six phases reuse each converged pressure–temperature profile. Gravity is derived from planet mass and radius in this configuration.",
            "",
            "PKL files were checked for filename/index pairing and nonzero size only; they were not unpickled during this coverage audit.",
        ]
    )
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    config = read_config(args.config)
    axes = climate_axes(config)
    dims = tuple(len(values) for _, _, values in axes)
    expected_total = math.prod(dims)

    npz_paths = file_indices(args.cache_dir, NPZ_RE, "climate_*.npz")
    pkl_paths = file_indices(args.cache_dir, PKL_RE, "climate_*_case.pkl")
    usable, problems, audit_counts = audit_npz(npz_paths, expected_total)
    level_rows, reach_rows, _ = build_coverage_rows(usable, axes)
    paired = set(npz_paths).intersection(pkl_paths)
    nonzero_pkls = {index for index, path in pkl_paths.items() if path.stat().st_size > 0}
    usable_paired = usable.intersection(nonzero_pkls)
    highest = max(usable) if usable else -1
    missing_within_frontier = (highest + 1 - len({index for index in usable if index <= highest})) if highest >= 0 else 0
    first_star_rows = [row for row in level_rows if row["axis_key"] == "stars"]

    snapshot = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = {
        "snapshot_utc": snapshot,
        "model_name": config.get("model_name", ""),
        "config_path": str(args.config.resolve()),
        "cache_dir": str(args.cache_dir.resolve()),
        "climate_axis_order": [key for key, _, _ in axes],
        "climate_axis_sizes": list(dims),
        "expected_climate_groups": expected_total,
        "expected_spectral_rows": expected_total * len(config.get("phase_deg", [])),
        "phase_values_excluded_from_climate": list(config.get("phase_deg", [])),
        "npz_files": len(npz_paths),
        "pkl_files": len(pkl_paths),
        "paired_npz_pkl": len(paired),
        "usable_paired_npz_pkl": len(usable_paired),
        "orphan_npz_files": len(set(npz_paths).difference(pkl_paths)),
        "orphan_pkl_files": len(set(pkl_paths).difference(npz_paths)),
        "zero_byte_pkl_files": len(set(pkl_paths).difference(nonzero_pkls)),
        "usable_climate_groups": len(usable),
        "usable_coverage_percent": round(100.0 * len(usable) / expected_total, 6),
        "problem_npz_files": len(problems),
        "highest_usable_index": highest,
        "frontier_percent": round(100.0 * (highest + 1) / expected_total, 6) if highest >= 0 else 0.0,
        "missing_within_frontier": missing_within_frontier,
        "audit_counts": audit_counts,
        "first_star_label": first_star_rows[0]["value"] if first_star_rows else "",
        "first_star_completed": first_star_rows[0]["completed_climates"] if first_star_rows else 0,
        "expected_per_star": first_star_rows[0]["expected_climates"] if first_star_rows else 0,
        "first_star_completion_percent": first_star_rows[0]["completion_percent"] if first_star_rows else 0.0,
        "parameter_value_reach": reach_rows,
        "npz_problems": problems,
    }

    (args.out_dir / "coverage_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (args.out_dir / "nonconverged_climate_group_indices.txt").write_text(
        "".join(f"{row['climate_group_index']}\n" for row in problems),
        encoding="utf-8",
    )
    write_csv(args.out_dir / "parameter_level_coverage.csv", level_rows)
    write_csv(args.out_dir / "parameter_value_reach.csv", reach_rows)
    write_summary_markdown(summary, reach_rows, args.out_dir)
    render_chart(summary, reach_rows, level_rows, args.out_dir)

    print(json.dumps({key: summary[key] for key in (
        "expected_climate_groups",
        "npz_files",
        "pkl_files",
        "paired_npz_pkl",
        "usable_climate_groups",
        "usable_coverage_percent",
        "problem_npz_files",
        "highest_usable_index",
        "missing_within_frontier",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
