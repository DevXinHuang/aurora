#!/usr/bin/env python
"""Save aggregate and per-climate graphs from cache-native QC reports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import textwrap
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


GRID_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = GRID_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from aurora_grid.qc.climate_cache import climate_group_index, discover_cache_files


DEFAULT_CACHE_DIR = GRID_ROOT / "outputs" / "aurora_subneptune_v1_dhuang" / "climate_cache"

PALETTE = {
    "pass": "#6B7280",
    "warning": "#2B6CB0",
    "rerun_recommended": "#D97706",
    "non_converged": "#B42345",
    "ink": "#20242A",
    "grid": "#D9DEE5",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--qc-dir", type=Path, help="Default: CACHE_DIR/qc")
    parser.add_argument("--plot-dir", type=Path, help="Default: QC_DIR/plots")
    parser.add_argument(
        "--individual",
        action="store_true",
        help="Save a three-panel plot for every warning/fail/rerun climate.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dpi", type=int, default=130)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    return parser.parse_args()


def _read_reports(qc_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_path = qc_dir / "climate_cache_qc_summary.csv"
    flags_path = qc_dir / "climate_cache_qc_flags.csv"
    if not summary_path.exists() or not flags_path.exists():
        raise FileNotFoundError(f"Run qc_climate_cache.py first; reports are missing in {qc_dir}")
    return pd.read_csv(summary_path), pd.read_csv(flags_path)


def _flag_sets(flags: pd.DataFrame) -> tuple[set[int], set[int], set[int]]:
    non_converged = set(
        flags.loc[flags["check"].eq("convergence"), "climate_group_index"].astype(int)
    )
    rerun_adiabat = set(
        flags.loc[
            flags["check"].eq("adiabat") & flags["severity"].eq("rerun_recommended"),
            "climate_group_index",
        ].astype(int)
    )
    warning = set(
        flags.loc[flags["severity"].eq("warning"), "climate_group_index"].astype(int)
    )
    return non_converged, rerun_adiabat, warning


def save_overview(summary: pd.DataFrame, flags: pd.DataFrame, output_path: Path, *, dpi: int) -> None:
    non_converged, rerun_adiabat, warning = _flag_sets(flags)
    status_order = ["pass", "warning", "rerun_recommended"]
    status_counts = summary["status"].value_counts()
    reason_counts = {
        "Flux-balance warning": int(
            flags.loc[flags["check"].eq("flux_balance") & flags["severity"].eq("warning"), "climate_group_index"].nunique()
        ),
        "Mild adiabat warning": int(
            flags.loc[flags["check"].eq("adiabat") & flags["severity"].eq("warning"), "climate_group_index"].nunique()
        ),
        "Strong adiabat rerun": len(rerun_adiabat),
        "Non-converged rerun": len(non_converged),
    }

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [0.9, 1.3]})
    left = axes[0]
    counts = [int(status_counts.get(status, 0)) for status in status_order]
    bars = left.bar(
        ["Pass", "Warning", "Rerun"],
        counts,
        color=[PALETTE[status] for status in status_order],
        edgecolor=PALETTE["ink"],
        linewidth=0.7,
    )
    for bar, count in zip(bars, counts):
        left.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{count:,}", ha="center", va="bottom", fontsize=10)
    left.set(title="QC status", ylabel="Climate groups")
    left.grid(axis="y", color=PALETTE["grid"], alpha=0.7)

    right = axes[1]
    labels = list(reason_counts)
    values = [reason_counts[label] for label in labels]
    colors = [PALETTE["warning"], PALETTE["warning"], PALETTE["rerun_recommended"], PALETTE["non_converged"]]
    bars = right.barh(labels, values, color=colors, edgecolor=PALETTE["ink"], linewidth=0.7)
    bars[-1].set_hatch("xx")
    right.invert_yaxis()
    for bar, value in zip(bars, values):
        right.text(value, bar.get_y() + bar.get_height() / 2, f"  {value:,}", va="center", fontsize=10)
    right.set(title="Flagged groups by diagnostic", xlabel="Unique climate groups")
    right.grid(axis="x", color=PALETTE["grid"], alpha=0.7)

    fig.suptitle(
        "Stage 1 climate-cache QC overview",
        fontsize=15,
        fontweight="bold",
        color=PALETTE["ink"],
    )
    fig.text(
        0.5,
        0.01,
        f"{len(summary):,} NPZ/PKL climate pairs. Warning reasons may overlap; non-converged uses hatched emphasis.",
        ha="center",
        color="#555B65",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def save_flag_index_map(summary: pd.DataFrame, flags: pd.DataFrame, output_path: Path, *, dpi: int) -> None:
    non_converged, rerun_adiabat, warning = _flag_sets(flags)
    warning_only = warning.difference(non_converged).difference(rerun_adiabat)
    groups = [
        ("Warning", warning_only, 0, "o", PALETTE["warning"]),
        ("Strong adiabat — rerun", rerun_adiabat, 1, "^", PALETTE["rerun_recommended"]),
        ("NON-CONVERGED — rerun", non_converged, 2, "X", PALETTE["non_converged"]),
    ]
    fig, ax = plt.subplots(figsize=(15, 5.2))
    for label, indices, y_value, marker, color in groups:
        ordered = sorted(indices)
        ax.scatter(
            ordered,
            np.full(len(ordered), y_value),
            label=f"{label} ({len(ordered):,})",
            marker=marker,
            color=color,
            edgecolor="white" if marker != "X" else PALETTE["ink"],
            linewidth=0.45,
            s=24 if marker != "X" else 70,
            alpha=0.8,
            zorder=3 if marker == "X" else 2,
        )
    ax.set(
        title="Every warning and rerun climate group by cache index",
        xlabel="climate_group_index",
        yticks=[0, 1, 2],
        yticklabels=["Warning", "Strong adiabat", "NON-CONVERGED"],
        ylim=(-0.65, 2.65),
    )
    ax.grid(axis="x", color=PALETTE["grid"], alpha=0.55)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False)
    fig.text(
        0.5,
        0.01,
        f"Source: cache-native QC summary and flags for {len(summary):,} downloaded climate groups.",
        ha="center",
        color="#555B65",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _numeric_list(value: object) -> np.ndarray | None:
    if not isinstance(value, list):
        return None
    try:
        return np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None


def _individual_folder(status: str, non_converged: bool) -> str:
    if non_converged:
        return "non_converged"
    if status == "rerun_recommended":
        return "rerun_adiabat"
    if status == "fail":
        return "failed"
    return "warning"


def save_individual_plot(
    npz_path: Path,
    row: pd.Series,
    messages: list[str],
    output_path: Path,
    *,
    non_converged: bool,
    dpi: int,
) -> None:
    with np.load(npz_path, allow_pickle=False) as archive:
        pressure = np.asarray(archive["pressure"], dtype=float)
        temperature = np.asarray(archive["temperature"], dtype=float)
        metadata = json.loads(str(archive["metadata_json"]))
    diagnostics = metadata.get("diagnostics", {})

    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    slope_ax, pt_ax, flux_ax, brightness_ax = axes.ravel()
    dtdp = _numeric_list(diagnostics.get("qc_dtdp"))
    adiabat = _numeric_list(diagnostics.get("qc_adiabat"))
    if dtdp is not None and adiabat is not None and dtdp.size == adiabat.size:
        layers = np.arange(dtdp.size)
        slope_ax.plot(dtdp, layers, color="#164BFF", lw=1.8, label="model dT/dP")
        slope_ax.plot(adiabat, layers, color="#FF2A2A", lw=1.8, label="adiabat")
        slope_ax.invert_yaxis()
    else:
        slope_ax.text(0.5, 0.5, "Adiabat arrays unavailable", transform=slope_ax.transAxes, ha="center")
    slope_ax.axvline(0, color="#777777", ls="--", lw=0.8)
    slope_ax.set(xlabel="dT/dP", ylabel="Layer number", title="Profile slope vs adiabat")
    if dtdp is not None and adiabat is not None:
        slope_ax.legend(loc="best", fontsize=8)
    slope_ax.grid(color=PALETTE["grid"], alpha=0.5)

    pt_ax.plot(temperature, pressure, color="#008B8B", lw=1.8)
    pt_ax.set_yscale("log")
    pt_ax.invert_yaxis()
    pt_ax.set(xlabel="Temperature (K)", ylabel="Pressure (bar)", title="P–T profile")
    pt_ax.grid(color=PALETTE["grid"], alpha=0.5)

    fnet = _numeric_list(diagnostics.get("fnet_irfnet"))
    if fnet is not None:
        p_fnet = pressure if fnet.size == pressure.size else pressure[: fnet.size]
        absolute_fnet = np.maximum(np.abs(fnet), np.finfo(float).tiny)
        flux_ax.plot(absolute_fnet, p_fnet, color="#FF1493", lw=1.6)
    else:
        flux_ax.text(0.5, 0.5, "Flux-balance array unavailable", transform=flux_ax.transAxes, ha="center")
    flux_ax.axvline(1.0e-3, color="#00CFE8", ls="--", lw=1.2, label="threshold 1e-03")
    flux_ax.set_xscale("log")
    flux_ax.set_yscale("log")
    flux_ax.invert_yaxis()
    flux_ax.set(xlabel="|Fnet / IR-Fnet|", ylabel="Pressure (bar)", title="Fnet / IR-Fnet")
    flux_ax.legend(loc="best", fontsize=8)
    flux_ax.grid(color=PALETTE["grid"], alpha=0.5)

    brightness = diagnostics.get("qc_brightness_temperature")
    brightness_wavelength = diagnostics.get("qc_brightness_wavelength")
    brightness_array = _numeric_list(brightness)
    wavelength_array = _numeric_list(brightness_wavelength)
    bottom_temperature = float(temperature[-1])
    if (
        brightness_array is not None
        and wavelength_array is not None
        and brightness_array.size == wavelength_array.size
    ):
        brightness_ax.plot(wavelength_array, brightness_array, color="#9400A8", lw=1.5)
        brightness_ax.axhline(bottom_temperature, color=PALETTE["ink"], ls="--", lw=1.0, label=f"T_bottom = {bottom_temperature:.0f} K")
        brightness_ax.set_xscale("log")
        brightness_ax.invert_yaxis()
        brightness_ax.set(xlabel="Wavelength (µm)", ylabel="Brightness temperature (K)")
        brightness_ax.legend(loc="best", fontsize=8)
        brightness_ax.grid(color=PALETTE["grid"], alpha=0.5)
    else:
        brightness_ax.axis("off")
        lines = [
            "Full IR brightness curve unavailable",
            "Stage 1 cache retained summary statistics only.",
            f"T_bottom = {bottom_temperature:.1f} K",
        ]
        if isinstance(brightness, dict):
            lines.extend(
                [
                    f"Cached points: {brightness.get('shape', ['?'])[0]}",
                    f"T_brt min / mean / max: {brightness.get('min', float('nan')):.1f} / {brightness.get('mean', float('nan')):.1f} / {brightness.get('max', float('nan')):.1f} K",
                ]
            )
        brightness_ax.text(0.5, 0.53, "\n".join(lines), transform=brightness_ax.transAxes, ha="center", va="center", fontsize=11)
    brightness_ax.set_title("IR brightness temperature")

    index = int(row["climate_group_index"])
    status = str(row["status"])
    title = f"Climate {index} — {status.replace('_', ' ').upper()}"
    if non_converged:
        title = f"Climate {index} — NON-CONVERGED — RERUN REQUIRED"
        fig.patch.set_facecolor("#FFF4F6")
    message_text = " | ".join(messages) if messages else "Flagged by cache-native QC"
    fig.suptitle(
        f"{title}\n{textwrap.fill(message_text, width=150)}",
        color=PALETTE["non_converged"] if non_converged else PALETTE["ink"],
        fontsize=12,
        fontweight="bold" if non_converged else "normal",
        y=0.985,
    )
    fig.subplots_adjust(left=0.07, right=0.985, bottom=0.07, top=0.88, wspace=0.16, hspace=0.22)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def _render_individual_task(task: tuple[Path, dict[str, object], list[str], Path, bool, int]) -> str:
    npz_path, row, messages, output_path, non_converged, dpi = task
    save_individual_plot(
        npz_path,
        pd.Series(row),
        messages,
        output_path,
        non_converged=non_converged,
        dpi=dpi,
    )
    return str(output_path)


def save_individual_plots(
    cache_dir: Path,
    summary: pd.DataFrame,
    flags: pd.DataFrame,
    plot_dir: Path,
    *,
    overwrite: bool,
    dpi: int,
    workers: int,
) -> Path:
    non_converged, _, _ = _flag_sets(flags)
    flagged = summary.loc[summary["status"].ne("pass")].sort_values("climate_group_index")
    messages_by_index = (
        flags.groupby("climate_group_index")["message"].apply(lambda values: [str(value) for value in values]).to_dict()
    )
    paths_by_index = {
        climate_group_index(path): path
        for path in discover_cache_files(cache_dir).npz_paths
    }
    manifest_path = plot_dir / "individual_plot_manifest.csv"
    manifest_rows: list[dict[str, object]] = []
    render_tasks: list[tuple[Path, dict[str, object], list[str], Path, bool, int]] = []
    for _, row in flagged.iterrows():
        index = int(row["climate_group_index"])
        npz_path = paths_by_index.get(index)
        if npz_path is None:
            continue
        is_non_converged = index in non_converged
        folder = _individual_folder(str(row["status"]), is_non_converged)
        output_path = plot_dir / "individual" / folder / f"climate_{index}_diagnostic.png"
        if overwrite or not output_path.exists():
            render_tasks.append(
                (
                    npz_path,
                    row.to_dict(),
                    messages_by_index.get(index, []),
                    output_path,
                    is_non_converged,
                    dpi,
                )
            )
        manifest_rows.append(
            {
                "climate_group_index": index,
                "status": row["status"],
                "non_converged": is_non_converged,
                "plot_path": str(output_path),
            }
        )

    if workers <= 1:
        rendered = map(_render_individual_task, render_tasks)
        for number, _ in enumerate(rendered, start=1):
            if number % 250 == 0 or number == len(render_tasks):
                print(f"individual_plots: {number}/{len(render_tasks)}")
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            rendered = executor.map(_render_individual_task, render_tasks, chunksize=8)
            for number, _ in enumerate(rendered, start=1):
                if number % 250 == 0 or number == len(render_tasks):
                    print(f"individual_plots: {number}/{len(render_tasks)}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["climate_group_index", "status", "non_converged", "plot_path"],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    return manifest_path


def main() -> int:
    args = parse_args()
    qc_dir = args.qc_dir or args.cache_dir / "qc"
    plot_dir = args.plot_dir or qc_dir / "plots"
    summary, flags = _read_reports(qc_dir)

    overview_path = plot_dir / "climate_cache_qc_overview.png"
    index_map_path = plot_dir / "climate_cache_flag_index_map.png"
    save_overview(summary, flags, overview_path, dpi=args.dpi)
    save_flag_index_map(summary, flags, index_map_path, dpi=args.dpi)
    print(f"overview_plot: {overview_path}")
    print(f"flag_index_map: {index_map_path}")

    if args.individual:
        manifest_path = save_individual_plots(
            args.cache_dir,
            summary,
            flags,
            plot_dir,
            overwrite=args.overwrite,
            dpi=args.dpi,
            workers=max(1, args.workers),
        )
        print(f"individual_manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
