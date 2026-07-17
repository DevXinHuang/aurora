#!/usr/bin/env python3
"""Rebuild the fixed climate-cache QC inventory with full brightness curves."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import textwrap
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


GRID_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = GRID_ROOT.parents[1]
SRC_ROOT = GRID_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from aurora_grid.qc.brightness_rebuild import (
    EXPECTED_BRIGHTNESS_POINTS,
    attach_qc_metadata,
    create_survival_reports,
    load_parameter_records,
    recompute_brightness_sidecar,
    sidecar_path,
    validate_brightness_case,
    validate_parameter_inventory,
    validate_sidecar,
    write_brightness_reports,
)
from aurora_grid.qc.climate_cache import climate_case_path, climate_group_index, discover_cache_files


DEFAULT_CACHE_DIR = GRID_ROOT / "outputs" / "aurora_subneptune_v1_dhuang" / "climate_cache"
DEFAULT_OPACITY_DIR = REPO_ROOT / "picaso4_reference" / "opacities"
EXPECTED_CLIMATES = 27_627
LOCAL_REFDATA = REPO_ROOT / "picaso4_reference"
if LOCAL_REFDATA.is_dir():
    os.environ.setdefault("picaso_refdata", str(LOCAL_REFDATA))
    os.environ.setdefault("PYSYN_CDBS", str(LOCAL_REFDATA / "stellar_grids"))
PALETTE = {
    "pass": "#547A64",
    "warning": "#2B6CB0",
    "fail": "#B42345",
    "rerun_recommended": "#D97706",
    "ink": "#20242A",
    "grid": "#D9DEE5",
    "brightness": "#9400A8",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--parameter-csv", type=Path, required=True)
    parser.add_argument("--opacity-dir", type=Path, default=DEFAULT_OPACITY_DIR)
    parser.add_argument("--baseline-qc-dir", type=Path, help="Default: CACHE_DIR/qc")
    parser.add_argument("--staging-dir", type=Path, help="Default: CACHE_DIR/qc.brightness-staging")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dpi", type=int, default=130)
    parser.add_argument("--limit", type=int, help="Smoke-test only; replacement is disabled when set.")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--skip-sidecars", action="store_true")
    parser.add_argument("--skip-plots", action="store_true")
    parser.add_argument(
        "--replace-only",
        action="store_true",
        help="Revalidate an already-complete staging directory and replace CACHE_DIR/qc without recomputing.",
    )
    parser.add_argument("--replace", action="store_true", help="Atomically replace CACHE_DIR/qc after validation.")
    return parser.parse_args()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_inventory(paths: list[Path], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["climate_group_index", "npz_path", "npz_bytes", "pkl_path", "pkl_bytes"])
        for path in paths:
            pkl = climate_case_path(path)
            writer.writerow([climate_group_index(path), str(path.resolve()), path.stat().st_size, str(pkl.resolve()), pkl.stat().st_size])


def _worker(task: tuple[str, str, dict[str, Any], str, bool]) -> dict[str, Any]:
    npz, output, parameters, opacity_dir, resume = task
    try:
        return recompute_brightness_sidecar(npz, output, parameters, opacity_dir, resume=resume)
    except Exception as exc:
        return {
            "climate_group_index": climate_group_index(npz),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "sidecar_path": output,
        }


def build_sidecars(
    paths: list[Path],
    parameters: dict[int, dict[str, Any]],
    opacity_dir: Path,
    sidecar_dir: Path,
    *,
    workers: int,
    resume: bool,
    error_path: Path,
) -> None:
    tasks = []
    for path in paths:
        index = climate_group_index(path)
        assert index is not None
        tasks.append((str(path), str(sidecar_path(sidecar_dir, index)), parameters[index], str(opacity_dir), resume))
    errors: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        for number, result in enumerate(executor.map(_worker, tasks, chunksize=2), start=1):
            counts[result["status"]] += 1
            if result["status"] == "error":
                errors.append(result)
            if number % 250 == 0 or number == len(tasks):
                print(f"brightness_sidecars: {number}/{len(tasks)} written={counts['written']} skipped={counts['skipped']} errors={counts['error']}", flush=True)
    error_path.write_text(json.dumps(errors, indent=2), encoding="utf-8")
    if errors:
        raise RuntimeError(f"{len(errors)} brightness sidecars failed; see {error_path}")


def run_qc(paths: list[Path], sidecar_dir: Path, output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    for number, npz_path in enumerate(paths, start=1):
        index = climate_group_index(npz_path)
        assert index is not None
        sidecar = sidecar_path(sidecar_dir, index)
        result, summary, case_flags = validate_brightness_case(
            sidecar,
            source_npz=npz_path,
            source_pkl=climate_case_path(npz_path),
        )
        attach_qc_metadata(sidecar, result)
        summary["sidecar_path"] = str(Path("diagnostics") / sidecar.name)
        for flag in case_flags:
            flag["sidecar_path"] = str(Path("diagnostics") / sidecar.name)
        summaries.append(summary)
        flags.extend(case_flags)
        if number % 1000 == 0 or number == len(paths):
            print(f"brightness_qc: {number}/{len(paths)}", flush=True)
    write_brightness_reports(summaries, flags, output_dir)
    return summaries, flags


def _fmt(value: Any, fmt: str = "g") -> str:
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "?"


def _parameter_header(index: int, params: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Climate {index:06d} | Star: T={_fmt(params.get('star_teff_k'), '.0f')} K, R={_fmt(params.get('star_radius_rsun'), '.3g')} R☉ | Planet: R={_fmt(params.get('planet_radius_rearth'), '.3g')} R⊕, M={_fmt(params.get('planet_mass_mearth'), '.4g')} M⊕, g={_fmt(params.get('gravity_ms2'), '.3g')} m s⁻²",
            f"Chemistry: metallicity={_fmt(params.get('metallicity_xsolar'), '.4g')}× solar, C/O={_fmt(params.get('c_to_o_xsolar'), '.3g')}× solar, Kzz={_fmt(params.get('kzz_cm2_s'), '.2e')} cm² s⁻¹ | Cloud: {params.get('cloud_model', '?')}, fraction={_fmt(params.get('cloud_fraction'), '.3g')}, fsed={_fmt(params.get('fsed'), '.3g')}",
            f"Orbit/thermal: S={_fmt(params.get('insolation_searth'), '.3g')} S⊕, a={_fmt(params.get('semi_major_au'), '.4g')} AU, Teq={_fmt(params.get('equilibrium_temperature_k'), '.0f')} K, Tint={_fmt(params.get('picaso_tint_k'), '.0f')} K",
        ]
    )


def render_diagnostic(task: tuple[str, dict[str, Any], list[str], dict[str, Any], str, int]) -> str:
    sidecar_name, summary, messages, params, output_name, dpi = task
    with np.load(sidecar_name, allow_pickle=False) as archive:
        p = np.asarray(archive["pressure"], dtype=float)
        t = np.asarray(archive["temperature"], dtype=float)
        dtdp = np.asarray(archive["qc_dtdp"], dtype=float)
        adiabat = np.asarray(archive["qc_adiabat"], dtype=float)
        fnet = np.asarray(archive["fnet_irfnet"], dtype=float)
        wave = np.asarray(archive["brightness_wavelength_um"], dtype=float)
        brightness = np.asarray(archive["brightness_temperature_k"], dtype=float)
        metadata = json.loads(str(archive["metadata_json"]))
    non_converged = metadata.get("climate_converged") in (False, 0, "0", "false", "False")
    index = int(summary["climate_group_index"])
    status = str(summary["status"])
    face = "#FFF0F3" if non_converged else "white"
    fig, axes = plt.subplots(2, 2, figsize=(15, 12), facecolor=face)
    slope_ax, pt_ax, flux_ax, brightness_ax = axes.ravel()
    layers = np.arange(max(dtdp.size, adiabat.size))
    if dtdp.size:
        slope_ax.plot(dtdp, layers[: dtdp.size], color="#164BFF", lw=1.8, label="model dT/dP")
    if adiabat.size:
        slope_ax.plot(adiabat, layers[: adiabat.size], color="#FF2A2A", lw=1.8, label="adiabat")
    slope_ax.axvline(0, color="#777777", ls="--", lw=0.8)
    slope_ax.invert_yaxis()
    slope_ax.set(xlabel="dT/dP", ylabel="Layer number", title="Profile slope vs adiabat")
    slope_ax.legend(loc="best", fontsize=8)

    pt_ax.plot(t, p, color="#008B8B", lw=1.8)
    pt_ax.set_yscale("log")
    pt_ax.invert_yaxis()
    pt_ax.set(xlabel="Temperature (K)", ylabel="Pressure (bar)", title="P–T profile")

    if fnet.size:
        p_fnet = p if fnet.size == p.size else p[: fnet.size]
        flux_ax.plot(np.maximum(np.abs(fnet), np.finfo(float).tiny), p_fnet, color="#FF1493", lw=1.6)
    flux_ax.axvline(1.0e-3, color="#00BFD6", ls="--", lw=1.2, label="threshold 10⁻³")
    flux_ax.set_xscale("log")
    flux_ax.set_yscale("log")
    flux_ax.invert_yaxis()
    flux_ax.set(xlabel="|Fnet / IR-Fnet|", ylabel="Pressure (bar)", title="Flux balance")
    flux_ax.legend(loc="best", fontsize=8)

    brightness_ax.plot(wave, brightness, color=PALETTE["brightness"], lw=1.5)
    brightness_ax.axhline(t[-1], color=PALETTE["ink"], ls="--", lw=1.0, label=f"T_bottom = {t[-1]:.0f} K")
    brightness_ax.set_xscale("log")
    brightness_ax.invert_yaxis()
    brightness_ax.set(xlabel="Wavelength (µm)", ylabel="Brightness temperature (K)", title="IR brightness temperature")
    brightness_ax.legend(loc="best", fontsize=8)
    for ax in axes.ravel():
        ax.grid(color=PALETTE["grid"], alpha=0.5)
        ax.set_facecolor(face)

    status_line = f"FINAL QC: {status.replace('_', ' ').upper()}"
    if non_converged:
        status_line += " — NON-CONVERGED; USING LAST CACHED P–T ITERATE"
    reason = textwrap.fill(" | ".join(messages), width=175) if messages else "No QC messages"
    fig.suptitle(
        f"{_parameter_header(index, params)}\n{status_line}\n{reason}",
        color=PALETTE["fail"] if non_converged else PALETTE["ink"],
        fontsize=10.5,
        fontweight="bold" if non_converged else "normal",
        y=0.992,
    )
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.065, top=0.80, wspace=0.17, hspace=0.23)
    output = Path(output_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight", facecolor=face)
    plt.close(fig)
    return str(output)


def build_diagnostic_plots(
    summaries: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    parameters: dict[int, dict[str, Any]],
    sidecar_dir: Path,
    plot_dir: Path,
    *,
    workers: int,
    dpi: int,
) -> Path:
    messages: dict[int, list[str]] = defaultdict(list)
    for flag in flags:
        messages[int(flag["climate_group_index"])].append(str(flag["message"]))
    tasks = []
    manifest_rows = []
    for summary in summaries:
        if summary["status"] == "pass":
            continue
        index = int(summary["climate_group_index"])
        folder = str(summary["status"])
        output = plot_dir / "individual" / folder / f"climate_{index:06d}_diagnostic.png"
        tasks.append((str(sidecar_path(sidecar_dir, index)), summary, messages[index], parameters[index], str(output), dpi))
        manifest_rows.append(
            {
                "climate_group_index": index,
                "status": summary["status"],
                "non_converged": summary["climate_converged"] in (False, 0, "0", "false", "False"),
                "plot_path": str(Path("plots") / "individual" / folder / output.name),
            }
        )
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        for number, _ in enumerate(executor.map(render_diagnostic, tasks, chunksize=4), start=1):
            if number % 100 == 0 or number == len(tasks):
                print(f"diagnostic_plots: {number}/{len(tasks)}", flush=True)
    manifest = plot_dir / "individual_plot_manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["climate_group_index", "status", "non_converged", "plot_path"])
        writer.writeheader()
        writer.writerows(manifest_rows)
    return manifest


def save_survival_charts(report_dir: Path, plot_dir: Path, *, dpi: int) -> None:
    comparison = _read_csv(report_dir / "survival_rate_comparison.csv")
    labels = ["Strict pass", "Usable\n(pass + warning)"]
    before = [float(row["before_percent"]) for row in comparison]
    after = [float(row["after_percent"]) for row in comparison]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(8.5, 5.3))
    width = 0.34
    bars1 = ax.bar(x - width / 2, before, width, label="Before brightness QC", color="#8A96A3", edgecolor=PALETTE["ink"])
    bars2 = ax.bar(x + width / 2, after, width, label="After brightness QC", color="#7551C2", edgecolor=PALETTE["ink"])
    for bars in (bars1, bars2):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{bar.get_height():.2f}%", ha="center", va="bottom")
    ax.set(xticks=x, xticklabels=labels, ylabel="Share of 27,627 climates (%)", title="Climate survival before and after brightness-aware QC", ylim=(0, 105))
    ax.legend(frameon=False)
    ax.grid(axis="y", color=PALETTE["grid"], alpha=0.6)
    fig.tight_layout()
    plot_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(plot_dir / "survival_rate_comparison.png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    rows = _read_csv(report_dir / "old_to_new_status_transition.csv")
    statuses = ["pass", "warning", "fail", "rerun_recommended"]
    matrix = np.asarray([[int(row[status]) for status in statuses] for row in rows], dtype=int)
    fig, ax = plt.subplots(figsize=(8.5, 7.0))
    image = ax.imshow(matrix, cmap="Purples")
    display = ["Pass", "Warning", "Fail", "Rerun"]
    ax.set(xticks=np.arange(4), xticklabels=display, yticks=np.arange(4), yticklabels=display, xlabel="New brightness-aware status", ylabel="Baseline status", title="Old → new QC status transition (counts)")
    threshold = matrix.max() * 0.45 if matrix.size else 0
    for i in range(4):
        for j in range(4):
            ax.text(j, i, f"{matrix[i, j]:,}", ha="center", va="center", color="white" if matrix[i, j] > threshold else PALETTE["ink"], fontweight="bold")
    fig.colorbar(image, ax=ax, label="Climate groups")
    fig.tight_layout()
    fig.savefig(plot_dir / "old_to_new_status_transition_heatmap.png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def validate_rebuild(
    paths: list[Path],
    parameters: dict[int, dict[str, Any]],
    staging_dir: Path,
    opacity_dir: Path,
    *,
    expected_count: int,
    plots_required: bool,
) -> dict[str, Any]:
    indices = {int(climate_group_index(path)) for path in paths if climate_group_index(path) is not None}
    validate_parameter_inventory(parameters, indices)
    invalid_sidecars = []
    opacity_names = set()
    for path in paths:
        index = int(climate_group_index(path))
        sidecar = sidecar_path(staging_dir / "diagnostics", index)
        validation = validate_sidecar(
            sidecar,
            source_npz=path,
            source_pkl=climate_case_path(path),
            require_qc=True,
        )
        if not validation.valid:
            invalid_sidecars.append({"index": index, "message": validation.message})
        else:
            with np.load(sidecar, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["metadata_json"]))
            opacity_names.add(metadata["opacity_filename"])
    summaries = _read_csv(staging_dir / "climate_cache_qc_summary.csv")
    if len(summaries) != expected_count:
        raise ValueError(f"QC result count {len(summaries)} != expected {expected_count}")
    nonpass = sum(row["status"] != "pass" for row in summaries)
    pngs = list((staging_dir / "plots" / "individual").rglob("climate_*_diagnostic.png")) if plots_required else []
    missing_opacities = sorted(name for name in opacity_names if not (opacity_dir / name).is_file())
    checks = {
        "expected_climates": expected_count,
        "source_npz": len(paths),
        "source_pkl": sum(climate_case_path(path).is_file() for path in paths),
        "parameter_records": len(parameters),
        "valid_sidecars": expected_count - len(invalid_sidecars),
        "brightness_points_per_sidecar": EXPECTED_BRIGHTNESS_POINTS,
        "qc_results": len(summaries),
        "final_nonpass": nonpass,
        "diagnostic_pngs": len(pngs),
        "opacity_files": sorted(opacity_names),
        "missing_opacity_files": missing_opacities,
        "invalid_sidecars": invalid_sidecars[:20],
    }
    required = (
        len(paths) == expected_count
        and checks["source_pkl"] == expected_count
        and len(parameters) == expected_count
        and checks["valid_sidecars"] == expected_count
        and len(summaries) == expected_count
        and not missing_opacities
        and (not plots_required or len(pngs) == nonpass)
    )
    checks["passed"] = required
    (staging_dir / "rebuild_validation.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    if not required:
        raise RuntimeError(f"rebuild validation failed; see {staging_dir / 'rebuild_validation.json'}")
    return checks


def atomic_replace(staging_dir: Path, target_dir: Path) -> None:
    backup = target_dir.with_name(f"{target_dir.name}.superseded-{os.getpid()}")
    if backup.exists():
        raise FileExistsError(backup)
    if target_dir.exists():
        os.replace(target_dir, backup)
    try:
        os.replace(staging_dir, target_dir)
    except Exception:
        if backup.exists() and not target_dir.exists():
            os.replace(backup, target_dir)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def main() -> int:
    args = parse_args()
    cache_dir = args.cache_dir.resolve()
    baseline_qc = (args.baseline_qc_dir or cache_dir / "qc").resolve()
    staging = (args.staging_dir or cache_dir / "qc.brightness-staging").resolve()
    if staging == baseline_qc:
        raise ValueError("staging directory must differ from the existing QC directory")
    inventory = discover_cache_files(cache_dir, limit=args.limit)
    paths = inventory.npz_paths
    expected_count = len(paths) if args.limit is not None else EXPECTED_CLIMATES
    if len(paths) != expected_count or inventory.orphan_pkl_paths:
        raise ValueError(f"fixed inventory check failed: npz={len(paths)}, orphan_pkl={len(inventory.orphan_pkl_paths)}, expected={expected_count}")
    missing_pkl = [path for path in paths if not climate_case_path(path).is_file()]
    if missing_pkl:
        raise ValueError(f"fixed inventory has {len(missing_pkl)} missing pickle pairs")
    parameters = load_parameter_records(args.parameter_csv)
    indices = {int(climate_group_index(path)) for path in paths}
    if args.limit is not None:
        parameters = {index: parameters[index] for index in indices}
    validate_parameter_inventory(parameters, indices)

    if args.replace_only:
        if not args.replace or args.limit is not None:
            raise ValueError("--replace-only requires --replace and the complete inventory")
        checks = validate_rebuild(
            paths,
            parameters,
            staging,
            args.opacity_dir.resolve(),
            expected_count=expected_count,
            plots_required=True,
        )
        print(json.dumps({"validation": checks}, indent=2))
        atomic_replace(staging, cache_dir / "qc")
        print(f"replaced_qc: {cache_dir / 'qc'}")
        return 0

    staging.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.parameter_csv, staging / "climate_parameters.csv")
    _write_inventory(paths, staging / "frozen_inventory.csv")
    if not args.skip_sidecars:
        build_sidecars(
            paths,
            parameters,
            args.opacity_dir.resolve(),
            staging / "diagnostics",
            workers=args.workers,
            resume=not args.no_resume,
            error_path=staging / "sidecar_errors.json",
        )
    summaries, flags = run_qc(paths, staging / "diagnostics", staging)
    baseline_rows = _read_csv(baseline_qc / "climate_cache_qc_summary.csv")
    if args.limit is not None:
        baseline_rows = [row for row in baseline_rows if int(row["climate_group_index"]) in indices]
    shutil.copy2(baseline_qc / "climate_cache_qc_summary.csv", staging / "baseline_climate_cache_qc_summary.csv")
    survival = create_survival_reports(baseline_rows, summaries, flags, staging)
    save_survival_charts(staging, staging / "plots", dpi=args.dpi)
    if not args.skip_plots:
        build_diagnostic_plots(
            summaries,
            flags,
            parameters,
            staging / "diagnostics",
            staging / "plots",
            workers=args.workers,
            dpi=args.dpi,
        )
    checks = validate_rebuild(
        paths,
        parameters,
        staging,
        args.opacity_dir.resolve(),
        expected_count=expected_count,
        plots_required=not args.skip_plots,
    )
    print(json.dumps({"survival": survival, "validation": checks}, indent=2))
    if args.replace:
        if args.limit is not None or args.skip_plots:
            raise ValueError("replacement requires the complete inventory and all diagnostic plots")
        atomic_replace(staging, cache_dir / "qc")
        print(f"replaced_qc: {cache_dir / 'qc'}")
    else:
        print(f"validated_staging: {staging}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
