#!/usr/bin/env python
"""Batch-compare Aurora Cahoy replication NetCDF files against Cahoy et al. 2010 reference albedos."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.cahoy_compare import (  # noqa: E402
    compare_manifest_outputs,
    compare_nc_to_cahoy,
    default_compare_output_root,
    ensure_reference_installed,
    metrics_to_records,
)
from aurora_grid.cahoy_reference import resolve_reference_root  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Aurora Cahoy grid NetCDF outputs to Cahoy 2010 reference spectra.")
    parser.add_argument(
        "--manifest",
        default=str(GRID_ROOT / "manifests" / "aurora_cahoy2010_replication_v0_manifest.csv"),
    )
    parser.add_argument(
        "--nc-root",
        default=str(GRID_ROOT / "outputs" / "aurora_cahoy2010_replication_v0" / "nc"),
        help="Directory containing run_*.nc (used if manifest paths are missing).",
    )
    parser.add_argument(
        "--reference-root",
        default=None,
        help="Cahoy albedo_spectra directory (default: data/cahoy2010_reference/.../albedo_spectra).",
    )
    parser.add_argument(
        "--out-dir",
        default=str(default_compare_output_root()),
        help="Write metrics CSV/JSON and optional plots here.",
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Limit number of manifest rows (debug).")
    parser.add_argument("--plot", action="store_true", help="Write per-case overlay plots for compared spectra.")
    parser.add_argument("--plot-limit", type=int, default=24, help="Max number of plots when --plot is set.")
    parser.add_argument("--single-nc", default=None, help="Compare one NetCDF instead of scanning the manifest.")
    return parser.parse_args()


def _write_metrics_csv(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def _plot_case(out_path: Path, metrics, arrays) -> None:
    import matplotlib.pyplot as plt

    wave = arrays["wavelength_um"]
    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax0, ax1 = axes
    ax0.plot(wave, arrays["cahoy_albedo"], label="Cahoy 2010", color="0.25", lw=1.5)
    ax0.plot(wave, arrays["aurora_albedo"], label="Aurora PICASO", color="C0", lw=1.2, alpha=0.9)
    ax0.set_ylabel("Albedo")
    ax0.set_title(metrics.cahoy_reference_name)
    ax0.legend(loc="best")
    ax0.grid(alpha=0.25)
    ax0.set_xlim(wave.min(), wave.max())

    ax1.axhline(0.0, color="0.4", lw=0.8)
    ax1.plot(wave, arrays["residual"], color="C3", lw=1.0)
    ax1.set_xlabel("Wavelength (um)")
    ax1.set_ylabel("Aurora - Cahoy")
    ax1.grid(alpha=0.25)

    text = (
        f"phase={metrics.phase_deg:.0f} deg  "
        f"RMSE={metrics.rmse:.4f}  MAE={metrics.mae:.4f}  r={metrics.pearson_r:.3f}"
    )
    fig.suptitle(text, fontsize=10)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    reference_root = resolve_reference_root(args.reference_root)
    ensure_reference_installed(reference_root)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_dir = out_dir / "plots"

    if args.single_nc:
        metrics, arrays = compare_nc_to_cahoy(args.single_nc, reference_root=reference_root)
        records = [{**metrics.to_dict(), "status": "ok"}]
        _write_metrics_csv(out_dir / "cahoy_compare_single.csv", records)
        if args.plot:
            _plot_case(plot_dir / f"{metrics.cahoy_reference_name.replace('.dat', '')}.png", metrics, arrays)
        print(json.dumps(metrics.to_dict(), indent=2))
        return 0

    results = compare_manifest_outputs(
        args.manifest,
        args.nc_root,
        reference_root=reference_root,
        max_cases=args.max_cases,
    )
    records = metrics_to_records(results)
    _write_metrics_csv(out_dir / "cahoy_compare_metrics.csv", records)

    ok = [item for item in results if item[2] is None]
    missing = sum(1 for item in results if item[2] == "missing_nc")
    failed = sum(1 for item in results if item[2] not in (None, "missing_nc"))

    summary = {
        "manifest": str(args.manifest),
        "reference_root": str(reference_root),
        "nc_root": str(args.nc_root),
        "n_rows": len(results),
        "n_compared": len(ok),
        "n_missing_nc": missing,
        "n_failed": failed,
    }
    if ok:
        rmses = [item[0].rmse for item in ok]
        summary["median_rmse"] = float(sorted(rmses)[len(rmses) // 2])
        summary["max_rmse"] = float(max(rmses))
        summary["worst_case"] = max(ok, key=lambda item: item[0].rmse)[0].cahoy_reference_name

    summary_path = out_dir / "cahoy_compare_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.plot:
        plotted = 0
        for metrics, arrays, error in sorted(ok, key=lambda item: item[0].rmse, reverse=True):
            if arrays is None or plotted >= args.plot_limit:
                break
            stem = metrics.cahoy_reference_name.replace(".dat", "")
            _plot_case(plot_dir / f"{stem}.png", metrics, arrays)
            plotted += 1

    print(json.dumps(summary, indent=2))
    print(f"metrics: {out_dir / 'cahoy_compare_metrics.csv'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
