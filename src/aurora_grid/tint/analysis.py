from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from .config import QUENCH_FAMILIES, REQUIRED_SPECIES, load_experiment, manifests
from .netcdf import SCHEMA_NAME, SCHEMA_VERSION, validate_file


CASE_ORDER = ("k2_18b_observed", "gj_1214b_low", "gj_1214b_observed")
CASE_SHORT = {
    "k2_18b_observed": "K2-18 b observed",
    "gj_1214b_low": "GJ 1214 b low",
    "gj_1214b_observed": "GJ 1214 b observed",
}
TINTS = (25.0, 50.0, 100.0)
CLOUD_ORDER = ("cloud_free", "fully_cloudy_virga")
METALLICITIES = (1.0, 100.0)
PANEL_ORDER = tuple((cloud, metallicity) for cloud in CLOUD_ORDER for metallicity in METALLICITIES)
TINT_COLORS = {25.0: "#2563A6", 50.0: "#C58B1B", 100.0: "#D95F02"}
QUENCH_MARKERS = {
    "CO-CH4-H2O": "o",
    "CO2": "s",
    "NH3-N2": "^",
    "HCN": "D",
}
SPECIES_QUENCH_FAMILY = {
    "CH4": "CO-CH4-H2O",
    "CO": "CO-CH4-H2O",
    "H2O": "CO-CH4-H2O",
    "CO2": "CO2",
    "NH3": "NH3-N2",
    "HCN": "HCN",
}
OBSERVABLES = {
    "transmission": ("transmission_depth", "Transit depth (ppm)"),
    "thermal": ("thermal_planet_star_flux_ratio", "Thermal planet/star ratio (ppm)"),
    "reflected": ("reflected_planet_star_flux_ratio", "Reflected planet/star ratio (ppm)"),
}


@dataclass
class ModelData:
    row: dict[str, Any]
    path: Path
    pressure_bar: np.ndarray
    temperature_k: np.ndarray
    mole_fraction: np.ndarray
    equilibrium_mole_fraction: np.ndarray | None
    quench_pressures_bar: dict[str, float]
    wavelength_um: np.ndarray
    spectra: dict[str, np.ndarray | None]
    climate_converged: bool
    thermal_corrected: bool
    schema_version: str
    chemistry_mode: str

    @property
    def key(self) -> tuple[str, str, float, float]:
        return (
            self.row["case_id"],
            self.row["cloud_id"],
            float(self.row["metallicity_xsolar"]),
            float(self.row["tint_k"]),
        )


@dataclass
class InputDiscovery:
    paths_by_index: dict[int, Path]
    issues_by_index: dict[int, list[str]]
    records: list[dict[str, Any]]
    global_issues: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_input_files(
    rows: list[dict[str, Any]], input_directory: str | Path | None = None
) -> InputDiscovery:
    expected = {str(row["run_id"]): row for row in rows}
    records: list[dict[str, Any]] = []
    global_issues: list[str] = []
    paths_by_index: dict[int, Path] = {}
    issues_by_index: dict[int, list[str]] = {}

    if input_directory is None:
        for row in rows:
            path = Path(row["output_path"])
            if path.is_file():
                paths_by_index[int(row["run_index"])] = path
            else:
                issues_by_index[int(row["run_index"])] = ["missing NetCDF"]
            records.append(
                {
                    "run_index": int(row["run_index"]),
                    "run_id": str(row["run_id"]),
                    "path": str(path),
                    "discovery_status": "matched" if path.is_file() else "missing",
                    "schema_name": None,
                    "schema_version": None,
                    "issues": issues_by_index.get(int(row["run_index"]), []),
                }
            )
        return InputDiscovery(paths_by_index, issues_by_index, records, global_issues)

    root = Path(input_directory).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Tint input directory does not exist: {root}")
    candidates = sorted(path for path in root.rglob("*.nc") if path.is_file())
    by_run_id: dict[str, list[tuple[Path, str | None, str | None]]] = {}
    unreadable: list[dict[str, Any]] = []
    for path in candidates:
        try:
            with xr.open_dataset(path, decode_cf=False) as ds:
                run_id = str(ds.attrs.get("run_id", "")).strip()
                schema_name = ds.attrs.get("schema_name")
                schema_version = ds.attrs.get("schema_version")
        except Exception as exc:
            unreadable.append(
                {
                    "run_index": None,
                    "run_id": None,
                    "path": str(path),
                    "discovery_status": "unreadable",
                    "schema_name": None,
                    "schema_version": None,
                    "issues": [f"cannot read NetCDF metadata: {exc}"],
                }
            )
            continue
        if not run_id:
            unreadable.append(
                {
                    "run_index": None,
                    "run_id": None,
                    "path": str(path),
                    "discovery_status": "missing_run_id",
                    "schema_name": schema_name,
                    "schema_version": schema_version,
                    "issues": ["missing run_id attribute"],
                }
            )
            continue
        by_run_id.setdefault(run_id, []).append((path, schema_name, schema_version))

    records.extend(unreadable)
    if unreadable:
        global_issues.append(f"{len(unreadable)} unreadable or unidentified NetCDF file(s)")
    for run_id, row in expected.items():
        index = int(row["run_index"])
        matches = by_run_id.pop(run_id, [])
        if len(matches) == 1:
            path, schema_name, schema_version = matches[0]
            paths_by_index[index] = path
            status = "matched"
            issues: list[str] = []
        elif not matches:
            path, schema_name, schema_version = Path(""), None, None
            status = "missing"
            issues = ["missing NetCDF"]
            issues_by_index[index] = issues
        else:
            path, schema_name, schema_version = matches[0]
            status = "duplicate_run_id"
            issues = [f"duplicate run_id found in {len(matches)} files"]
            issues_by_index[index] = issues
        records.append(
            {
                "run_index": index,
                "run_id": run_id,
                "path": str(path) if matches else None,
                "discovery_status": status,
                "schema_name": schema_name,
                "schema_version": schema_version,
                "issues": issues,
            }
        )
    for run_id, matches in sorted(by_run_id.items()):
        for path, schema_name, schema_version in matches:
            records.append(
                {
                    "run_index": None,
                    "run_id": run_id,
                    "path": str(path),
                    "discovery_status": "unexpected_run_id",
                    "schema_name": schema_name,
                    "schema_version": schema_version,
                    "issues": ["run_id is not part of the configured 36-run experiment"],
                }
            )
        global_issues.append(f"unexpected run_id {run_id!r}")
    return InputDiscovery(paths_by_index, issues_by_index, records, global_issues)


def _partial_validation_issues(path: Path, row: dict[str, Any]) -> list[str]:
    return [
        issue
        for issue in validate_file(path, row)
        if issue != "climate solution is not converged"
    ]


def load_models(
    config_path: str | Path,
    mode: str,
    input_directory: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[ModelData], dict[int, list[str]], InputDiscovery]:
    rows = manifests(load_experiment(config_path))
    discovery = discover_input_files(rows, input_directory)
    loaded: list[ModelData] = []
    excluded: dict[int, list[str]] = dict(discovery.issues_by_index)
    for row in rows:
        run_index = int(row["run_index"])
        if run_index in excluded:
            continue
        path = discovery.paths_by_index[run_index]
        issues = validate_file(path, row) if mode == "final" else _partial_validation_issues(path, row)
        if issues:
            excluded[run_index] = issues
            continue
        with xr.open_dataset(path) as source:
            ds = source.load()
        equilibrium = (
            np.asarray(ds["equilibrium_mole_fraction"].values, dtype=float)
            if "equilibrium_mole_fraction" in ds else None
        )
        quench = {}
        if "quench_pressure_bar" in ds and "quench_family" in ds:
            quench = {
                str(name): float(value)
                for name, value in zip(ds["quench_family"].values, ds["quench_pressure_bar"].values)
                if np.isfinite(float(value))
            }
        thermal_corrected = (
            "thermal_flux_ratio_corrected" in ds
            and int(ds["thermal_flux_ratio_corrected"].item()) == 1
        )
        spectra: dict[str, np.ndarray | None] = {
            "transmission": np.asarray(ds["transmission_depth"].values, dtype=float),
            "reflected": np.asarray(ds["reflected_planet_star_flux_ratio"].values, dtype=float),
            "thermal": (
                np.asarray(ds["thermal_planet_star_flux_ratio"].values, dtype=float)
                if thermal_corrected else None
            ),
        }
        loaded.append(ModelData(
            row=row,
            path=path,
            pressure_bar=np.asarray(ds["pressure_bar"].values, dtype=float),
            temperature_k=np.asarray(ds["temperature_k"].values, dtype=float),
            mole_fraction=np.asarray(ds["mole_fraction"].values, dtype=float),
            equilibrium_mole_fraction=equilibrium,
            quench_pressures_bar=quench,
            wavelength_um=np.asarray(ds["wavelength_um"].values, dtype=float),
            spectra=spectra,
            climate_converged=bool(ds["climate_converged"].item()),
            thermal_corrected=thermal_corrected,
            schema_version=str(ds.attrs.get("schema_version", "unknown")),
            chemistry_mode=str(ds.attrs.get("chemistry_mode", row.get("chemistry_mode", "unknown"))),
        ))
    for record in discovery.records:
        index = record.get("run_index")
        if index is not None and int(index) in excluded:
            record["issues"] = excluded[int(index)]
            record["discovery_status"] = "excluded"
    if mode == "final":
        if discovery.global_issues:
            raise RuntimeError(
                f"Final package input discovery failed: {discovery.global_issues}"
            )
        if excluded or len(loaded) != 36:
            raise RuntimeError(
                f"Final package requires 36 valid models; loaded={len(loaded)}, excluded={excluded}"
            )
        nonconverged = [model.row["run_index"] for model in loaded if not model.climate_converged]
        if nonconverged:
            raise RuntimeError(f"Final package requires climate convergence; nonconverged={nonconverged}")
        pairs = tint_endpoint_pairs(loaded)
        if len(pairs) != 12:
            raise RuntimeError(f"Final package requires 12 Tint endpoint pairs; found {len(pairs)}")
    elif not loaded:
        raise RuntimeError("No valid model outputs are available for plotting")
    return rows, loaded, excluded, discovery


def model_index(models: Iterable[ModelData]) -> dict[tuple[str, str, float, float], ModelData]:
    return {model.key: model for model in models}


def tint_endpoint_pairs(models: Iterable[ModelData]) -> dict[tuple[str, str, float], tuple[ModelData, ModelData]]:
    index = model_index(models)
    pairs = {}
    for case_id in CASE_ORDER:
        for cloud_id, metallicity in PANEL_ORDER:
            low = index.get((case_id, cloud_id, metallicity, 25.0))
            high = index.get((case_id, cloud_id, metallicity, 100.0))
            if low is not None and high is not None:
                pairs[(case_id, cloud_id, metallicity)] = (low, high)
    return pairs


def _interpolate_log_pressure(model: ModelData, values: np.ndarray, pressure_bar: float) -> float:
    order = np.argsort(model.pressure_bar)
    log_pressure = np.log10(model.pressure_bar[order])
    log_values = np.log10(np.maximum(np.asarray(values, dtype=float)[order], 1.0e-300))
    return float(10.0 ** np.interp(math.log10(pressure_bar), log_pressure, log_values))


def pressure_weighted_column_mean(model: ModelData, values: np.ndarray) -> float:
    pressure = np.asarray(model.pressure_bar, dtype=float)
    abundance = np.asarray(values, dtype=float)
    valid = np.isfinite(pressure) & (pressure > 0) & np.isfinite(abundance) & (abundance >= 0)
    if np.count_nonzero(valid) < 2:
        return float("nan")
    order = np.argsort(pressure[valid])
    pressure = pressure[valid][order]
    abundance = abundance[valid][order]
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(integrate(abundance, pressure) / (pressure[-1] - pressure[0]))


def spectral_residual_ppm(low: ModelData, high: ModelData, observable: str) -> np.ndarray:
    low_values = low.spectra.get(observable)
    high_values = high.spectra.get(observable)
    if low_values is None or high_values is None:
        raise ValueError(f"{observable} is unavailable for a Tint endpoint")
    if low.wavelength_um.shape != high.wavelength_um.shape or not np.array_equal(
        low.wavelength_um, high.wavelength_um
    ):
        raise ValueError("Tint endpoints do not share an identical wavelength grid")
    return (
        np.asarray(high_values, dtype=float) - np.asarray(low_values, dtype=float)
    ) * 1.0e6


def rms_residual_ppm(low: ModelData, high: ModelData, observable: str) -> float:
    residual = spectral_residual_ppm(low, high, observable)
    return float(np.sqrt(np.mean(residual**2)))


def _panel_title(cloud_id: str, metallicity: float) -> str:
    cloud = "Cloud-free" if cloud_id == "cloud_free" else "Virga cloudy, fsed=3"
    return f"{cloud} · {metallicity:g}× solar"


def _style_axis(ax: plt.Axes) -> None:
    ax.grid(True, color="#D9DEE7", linewidth=0.6, alpha=0.7)
    ax.tick_params(colors="#323A46", labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#697386")
    ax.spines["bottom"].set_color("#697386")


def _set_pressure_axis(ax: plt.Axes) -> None:
    ax.set_yscale("log")
    # ``invert_yaxis`` toggles the current direction.  That is unsafe for
    # figures whose panels share a y-axis because styling each panel can
    # toggle the shared axis back to its original direction.  Set explicit
    # limits instead so this helper is idempotent.
    lower, upper = ax.get_ylim()
    ax.set_ylim(max(lower, upper), min(lower, upper))


def _watermark(fig: plt.Figure, mode: str, loaded_count: int) -> None:
    if mode == "partial":
        fig.text(
            0.5, 0.5, f"PARTIAL — {loaded_count}/36 — NOT FOR SCIENTIFIC CITATION",
            ha="center", va="center", rotation=25, fontsize=22, color="#B42318",
            alpha=0.12, weight="bold", zorder=1000,
        )


def _save_figure(fig: plt.Figure, stem: Path, mode: str, loaded_count: int) -> None:
    _watermark(fig, mode, loaded_count)
    stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(stem.with_suffix(".png"), dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _missing_panel(ax: plt.Axes, text: str = "No model output") -> None:
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", color="#697386")
    ax.set_xticks([])
    ax.set_yticks([])


def plot_pt_case(case_id: str, index: dict[tuple[str, str, float, float], ModelData], mode: str, count: int, stem: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 9), sharex=False, sharey=True)
    for ax, (cloud_id, metallicity) in zip(axes.flat, PANEL_ORDER):
        found = 0
        for tint in TINTS:
            model = index.get((case_id, cloud_id, metallicity, tint))
            if model is None:
                continue
            found += 1
            style = "-" if model.climate_converged else "--"
            ax.plot(model.temperature_k, model.pressure_bar, color=TINT_COLORS[tint], linestyle=style, linewidth=1.8, label=f"Tint={tint:g} K")
            for family, pressure in model.quench_pressures_bar.items():
                if family not in QUENCH_MARKERS or pressure < model.pressure_bar.min() or pressure > model.pressure_bar.max():
                    continue
                temperature = np.interp(
                    np.log10(pressure), np.log10(model.pressure_bar), model.temperature_k
                )
                ax.scatter(temperature, pressure, marker=QUENCH_MARKERS[family], s=22,
                           facecolor="white", edgecolor=TINT_COLORS[tint], linewidth=0.9, zorder=4)
        if not found:
            _missing_panel(ax)
        else:
            _set_pressure_axis(ax)
            ax.set_xlabel("Temperature (K)")
            ax.set_ylabel("Pressure (bar)")
            _style_axis(ax)
        ax.set_title(_panel_title(cloud_id, metallicity), fontsize=10, color="#1F2937")
    handles = [plt.Line2D([0], [0], color=TINT_COLORS[t], lw=2, label=f"Tint={t:g} K") for t in TINTS]
    fig.legend(handles=handles, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.94))
    fig.suptitle(f"P–T profiles — {CASE_SHORT[case_id]}", fontsize=15, y=0.99)
    chemistry_mode = next((model.chemistry_mode for model in index.values()), "unknown")
    note = (
        "Dashed curves are not climate-converged; open markers show saved PICASO quench pressures."
        if chemistry_mode == "disequilibrium_quench"
        else "Visscher 2121 equilibrium-only chemistry; dashed curves are not climate-converged."
    )
    fig.text(0.5, 0.955, note, ha="center", fontsize=9, color="#596273")
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    _save_figure(fig, stem, mode, count)


def plot_spectra_case(observable: str, case_id: str, index: dict[tuple[str, str, float, float], ModelData], mode: str, count: int, stem: Path) -> None:
    _, ylabel = OBSERVABLES[observable]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    for ax, (cloud_id, metallicity) in zip(axes.flat, PANEL_ORDER):
        found = 0
        for tint in TINTS:
            model = index.get((case_id, cloud_id, metallicity, tint))
            if model is None or model.spectra[observable] is None:
                continue
            found += 1
            ax.plot(model.wavelength_um, np.asarray(model.spectra[observable]) * 1.0e6,
                    color=TINT_COLORS[tint], linestyle="-" if model.climate_converged else "--",
                    linewidth=1.2, label=f"Tint={tint:g} K")
        if not found:
            message = "Corrected thermal output unavailable" if observable == "thermal" else "No model output"
            _missing_panel(ax, message)
        else:
            ax.set_xscale("log")
            ax.set_xlim(0.6, 15.0)
            ax.set_xlabel("Wavelength (µm)")
            ax.set_ylabel(ylabel)
            _style_axis(ax)
        ax.set_title(_panel_title(cloud_id, metallicity), fontsize=10)
    handles = [plt.Line2D([0], [0], color=TINT_COLORS[t], lw=2, label=f"Tint={t:g} K") for t in TINTS]
    fig.legend(handles=handles, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.94))
    fig.suptitle(f"{observable.capitalize()} spectra — {CASE_SHORT[case_id]}", fontsize=15, y=0.99)
    fig.text(0.5, 0.955, "Planet/star ratios and transit depths are shown in ppm; dashed curves are not climate-converged.", ha="center", fontsize=9, color="#596273")
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    _save_figure(fig, stem, mode, count)


def plot_abundance_combination(case_id: str, cloud_id: str, metallicity: float, index: dict[tuple[str, str, float, float], ModelData], mode: str, count: int, stem: Path) -> None:
    chemistry_mode = next((model.chemistry_mode for model in index.values()), "unknown")
    fig, axes = plt.subplots(2, 3, figsize=(13, 9), sharey=True)
    for ax, species_index in zip(axes.flat, range(len(REQUIRED_SPECIES))):
        species = REQUIRED_SPECIES[species_index]
        found = 0
        for tint in TINTS:
            model = index.get((case_id, cloud_id, metallicity, tint))
            if model is None:
                continue
            found += 1
            style = "-" if model.climate_converged else "--"
            ax.plot(np.maximum(model.mole_fraction[:, species_index], 1e-300), model.pressure_bar,
                    color=TINT_COLORS[tint], linestyle=style, linewidth=1.7,
                    label=f"Tint={tint:g} K {'quenched' if chemistry_mode == 'disequilibrium_quench' else 'equilibrium'}")
            if chemistry_mode == "disequilibrium_quench" and model.equilibrium_mole_fraction is not None:
                ax.plot(np.maximum(model.equilibrium_mole_fraction[:, species_index], 1e-300), model.pressure_bar,
                        color=TINT_COLORS[tint], linestyle=":", linewidth=1.0, alpha=0.45)
            family = SPECIES_QUENCH_FAMILY[species]
            pressure = model.quench_pressures_bar.get(family)
            if pressure is not None:
                ax.axhline(pressure, color=TINT_COLORS[tint], linewidth=0.7, alpha=0.35)
        if not found:
            _missing_panel(ax)
        else:
            ax.set_xscale("log")
            _set_pressure_axis(ax)
            ax.set_xlabel("Mole fraction (v/v)")
            ax.set_ylabel("Pressure (bar)")
            _style_axis(ax)
        ax.set_title(species, fontsize=11)
    chemistry_label = "Quenched" if chemistry_mode == "disequilibrium_quench" else "Equilibrium"
    fig.suptitle(f"{chemistry_label} abundances — {CASE_SHORT[case_id]} — {_panel_title(cloud_id, metallicity)}", fontsize=14, y=0.99)
    note = (
        "Solid/dashed: final quenched profile (converged/non-converged); dotted: equilibrium; horizontal guides: PICASO quench pressure."
        if chemistry_mode == "disequilibrium_quench"
        else "Solid/dashed: Visscher 2121 equilibrium profile (converged/non-converged); no quench adjustment."
    )
    fig.text(0.5, 0.953, note, ha="center", fontsize=8.5, color="#596273")
    handles = [plt.Line2D([0], [0], color=TINT_COLORS[t], lw=2, label=f"Tint={t:g} K") for t in TINTS]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.005))
    fig.tight_layout(rect=(0, 0.04, 1, 0.92))
    _save_figure(fig, stem, mode, count)


def plot_residuals(
    observable: str,
    pairs: dict[tuple[str, str, float], tuple[ModelData, ModelData]],
    mode: str,
    count: int,
    stem: Path,
    precision_guide: dict[str, Any] | None = None,
) -> None:
    _, ylabel = OBSERVABLES[observable]
    fig, ax = plt.subplots(figsize=(12, 7))
    colors = {case: color for case, color in zip(CASE_ORDER, ("#2563A6", "#C58B1B", "#D95F02"))}
    line_styles = {("cloud_free", 1.0): "-", ("cloud_free", 100.0): "--", ("fully_cloudy_virga", 1.0): "-.", ("fully_cloudy_virga", 100.0): ":"}
    plotted = 0
    for case_id in CASE_ORDER:
        for cloud_id, metallicity in PANEL_ORDER:
            pair = pairs.get((case_id, cloud_id, metallicity))
            if pair is None or pair[0].spectra[observable] is None or pair[1].spectra[observable] is None:
                continue
            low, high = pair
            residual = np.abs(spectral_residual_ppm(low, high, observable))
            label = f"{CASE_SHORT[case_id]} · {'clear' if cloud_id == 'cloud_free' else 'cloudy'} · {metallicity:g}×"
            ax.plot(low.wavelength_um, residual, color=colors[case_id], linestyle=line_styles[(cloud_id, metallicity)], linewidth=1.4, alpha=1.0 if low.climate_converged and high.climate_converged else 0.55, label=label)
            plotted += 1
    precision_guide = precision_guide or {}
    enabled_for = tuple(precision_guide.get("observables", ("transmission",)))
    if observable in enabled_for:
        band = tuple(float(value) for value in precision_guide.get("band_ppm", (20.0, 50.0)))
        reference = float(precision_guide.get("reference_ppm", 30.0))
        ax.axhspan(
            band[0], band[1], color="#697386", alpha=0.10,
            label=f"Illustrative {band[0]:g}–{band[1]:g} ppm guide (not a detectability claim)",
        )
        ax.axhline(
            reference, color="#323A46", linewidth=1.0, linestyle="--",
            label=f"Illustrative {reference:g} ppm reference",
        )
    ax.set_xscale("log")
    ax.set_xlim(0.6, 15.0)
    ax.set_yscale("symlog", linthresh=0.1)
    ax.set_ylim(bottom=0.0)
    ax.set_xlabel("Wavelength (µm)")
    ax.set_ylabel(f"Absolute Tint 25–100 K residual in {ylabel.lower()}")
    _style_axis(ax)
    if plotted:
        ax.legend(fontsize=7, ncol=2, frameon=False, loc="upper left")
    else:
        _missing_panel(ax, "No complete corrected Tint=25/100 endpoint pairs")
    fig.suptitle(f"Tint endpoint spectral residuals — {observable}", fontsize=15)
    fig.text(0.5, 0.94, "Twelve case/cloud/metallicity lines when complete; faded lines include a non-converged endpoint.", ha="center", fontsize=9, color="#596273")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    _save_figure(fig, stem, mode, count)


def plot_case_metric(observable: str, pairs: dict[tuple[str, str, float], tuple[ModelData, ModelData]], mode: str, count: int, stem: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharey=True)
    bar_colors = ["#2563A6", "#C58B1B", "#D95F02"]
    for ax, (cloud_id, metallicity) in zip(axes.flat, PANEL_ORDER):
        values = []
        valid = []
        for case_id in CASE_ORDER:
            pair = pairs.get((case_id, cloud_id, metallicity))
            if pair is None or pair[0].spectra[observable] is None or pair[1].spectra[observable] is None:
                values.append(np.nan)
                valid.append(False)
                continue
            low, high = pair
            values.append(rms_residual_ppm(low, high, observable))
            valid.append(low.climate_converged and high.climate_converged)
        x = np.arange(3)
        bars = ax.bar(x, np.nan_to_num(values, nan=0.0), color=bar_colors, edgecolor="#323A46", linewidth=0.6)
        for bar, value, is_valid in zip(bars, values, valid):
            if np.isnan(value):
                bar.set_alpha(0.08)
                ax.text(bar.get_x() + bar.get_width()/2, 0, "missing", rotation=90, ha="center", va="bottom", fontsize=7)
            elif not is_valid:
                bar.set_hatch("//")
                bar.set_alpha(0.6)
        ax.set_xticks(x, ["K2-18b\n255 K", "GJ1214b\n255 K", "GJ1214b\n500 K"])
        ax.set_ylabel("RMS Tint 25–100 K residual (ppm)")
        ax.set_title(_panel_title(cloud_id, metallicity), fontsize=10)
        ax.set_ylim(bottom=0)
        _style_axis(ax)
    fig.suptitle(f"Insolation versus gravity Tint sensitivity — {observable}", fontsize=15)
    fig.text(0.5, 0.94, "Hatched bars include a non-converged endpoint; faint bars are missing.", ha="center", fontsize=9, color="#596273")
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    _save_figure(fig, stem, mode, count)


def plot_headline_case_metric(
    observable: str,
    pairs: dict[tuple[str, str, float], tuple[ModelData, ModelData]],
    mode: str,
    count: int,
    stem: Path,
    *,
    cloud_id: str = "fully_cloudy_virga",
    metallicity: float = 100.0,
) -> None:
    values: list[float] = []
    valid: list[bool] = []
    for case_id in CASE_ORDER:
        pair = pairs.get((case_id, cloud_id, metallicity))
        if pair is None or pair[0].spectra[observable] is None or pair[1].spectra[observable] is None:
            values.append(float("nan"))
            valid.append(False)
            continue
        low, high = pair
        values.append(rms_residual_ppm(low, high, observable))
        valid.append(low.climate_converged and high.climate_converged)
    fig, ax = plt.subplots(figsize=(8.5, 6.0))
    x = np.arange(3)
    bars = ax.bar(
        x,
        np.nan_to_num(values, nan=0.0),
        color=("#2563A6", "#C58B1B", "#D95F02"),
        edgecolor="#323A46",
        linewidth=0.7,
    )
    for bar, value, is_valid in zip(bars, values, valid):
        if np.isnan(value):
            bar.set_alpha(0.08)
            ax.text(bar.get_x() + bar.get_width() / 2, 0, "missing", ha="center", va="bottom")
        elif not is_valid:
            bar.set_hatch("//")
            bar.set_alpha(0.6)
    ax.set_xticks(x, ["K2-18 b\n255 K", "GJ 1214 b\n255 K", "GJ 1214 b\n500 K"])
    ax.set_ylabel("RMS Tint 25–100 K residual (ppm)")
    ax.set_ylim(bottom=0)
    _style_axis(ax)
    fig.suptitle(f"Headline Tint comparison — {observable}", fontsize=15)
    fig.text(
        0.5,
        0.94,
        f"{_panel_title(cloud_id, metallicity)}; hatched bars include a non-converged endpoint.",
        ha="center",
        fontsize=9,
        color="#596273",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    _save_figure(fig, stem, mode, count)


def plot_chemistry_metric(pairs: dict[tuple[str, str, float], tuple[ModelData, ModelData]], mode: str, count: int, stem: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharey=True)
    species_indices = {name: REQUIRED_SPECIES.index(name) for name in ("CO", "CO2")}
    for ax, (cloud_id, metallicity) in zip(axes.flat, PANEL_ORDER):
        x = np.arange(3)
        width = 0.34
        for offset, (species, color) in zip((-width/2, width/2), (("CO", "#2563A6"), ("CO2", "#D95F02"))):
            values = []
            for case_id in CASE_ORDER:
                pair = pairs.get((case_id, cloud_id, metallicity))
                if pair is None:
                    values.append(np.nan)
                    continue
                low, high = pair
                i = species_indices[species]
                values.append(float(np.max(np.abs(
                    np.log10(np.maximum(high.mole_fraction[:, i], 1e-300))
                    - np.log10(np.maximum(low.mole_fraction[:, i], 1e-300))
                ))))
            ax.bar(x + offset, np.nan_to_num(values, nan=0.0), width, label=species,
                   color=color, edgecolor="#323A46", linewidth=0.5)
        ax.set_xticks(x, ["K2-18b\n255 K", "GJ1214b\n255 K", "GJ1214b\n500 K"])
        ax.set_ylabel("Maximum |Δ log10 mole fraction|")
        ax.set_title(_panel_title(cloud_id, metallicity), fontsize=10)
        ax.set_ylim(bottom=0)
        _style_axis(ax)
    fig.legend(loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.94))
    fig.suptitle("CO and CO2 Tint sensitivity across cases", fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    _save_figure(fig, stem, mode, count)


def build_summary_table(
    rows: list[dict[str, Any]],
    models: Iterable[ModelData],
    abundance_pressure_bar: float = 1.0e-3,
) -> pd.DataFrame:
    index = {model.row["run_index"]: model for model in models}
    output = []
    for row in rows:
        model = index.get(row["run_index"])
        record: dict[str, Any] = {
            "run_index": row["run_index"], "run_id": row["run_id"], "case_id": row["case_id"],
            "teq_k": row["equilibrium_temperature_k"], "tint_k": row["tint_k"],
            "cloud_id": row["cloud_id"], "metallicity_xsolar": row["metallicity_xsolar"],
            "chemistry_mode": row["chemistry_mode"],
            "status": "included" if model is not None else "missing_or_invalid",
            "climate_converged": model.climate_converged if model is not None else np.nan,
            "abundance_pressure_bar": abundance_pressure_bar,
            "column_mean_definition": "integral(x dP) / (P_bottom - P_top)",
        }
        for species_index, species in enumerate(REQUIRED_SPECIES):
            record[f"{species}_mole_fraction_at_1mbar"] = (
                _interpolate_log_pressure(
                    model, model.mole_fraction[:, species_index], abundance_pressure_bar
                )
                if model is not None else np.nan
            )
            record[f"{species}_pressure_weighted_column_mean_mole_fraction"] = (
                pressure_weighted_column_mean(model, model.mole_fraction[:, species_index])
                if model is not None else np.nan
            )
        for family in QUENCH_FAMILIES:
            slug = family.lower().replace("-", "_")
            record[f"quench_pressure_{slug}_bar"] = (
                model.quench_pressures_bar.get(family, np.nan) if model is not None else np.nan
            )
        output.append(record)
    return pd.DataFrame(output)


def build_sanity_tables(models: Iterable[ModelData]) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = tint_endpoint_pairs(models)
    h2o_index = REQUIRED_SPECIES.index("H2O")
    h2o_rows = []
    for (case_id, cloud_id, metallicity), (low, high) in pairs.items():
        low_value = _interpolate_log_pressure(low, low.mole_fraction[:, h2o_index], 1e-3)
        high_value = _interpolate_log_pressure(high, high.mole_fraction[:, h2o_index], 1e-3)
        change = abs(math.log10(high_value) - math.log10(low_value))
        h2o_rows.append({
            "case_id": case_id, "cloud_id": cloud_id, "metallicity_xsolar": metallicity,
            "chemistry_mode": low.chemistry_mode,
            "h2o_abs_change_dex_at_1mbar": change, "advisory_over_0p1_dex": change > 0.1,
            "both_endpoints_converged": low.climate_converged and high.climate_converged,
        })
    by_key = model_index(models)
    wogan_rows = []
    for cloud_id in CLOUD_ORDER:
        record: dict[str, Any] = {
            "case_id": "k2_18b_observed", "cloud_id": cloud_id,
            "metallicity_xsolar": 100.0,
            "chemistry_mode": next(
                (
                    model.chemistry_mode for model in by_key.values()
                    if model.row["case_id"] == "k2_18b_observed"
                ),
                "unknown",
            ),
            "benchmark_applicability": (
                "directional_only; Wogan benchmark invokes disequilibrium quenching"
            ),
        }
        for species in ("CO", "CO2"):
            values = []
            for tint in TINTS:
                model = by_key.get(("k2_18b_observed", cloud_id, 100.0, tint))
                value = np.nan if model is None else _interpolate_log_pressure(
                    model, model.mole_fraction[:, REQUIRED_SPECIES.index(species)], 1e-3
                )
                record[f"{species}_at_1mbar_tint{int(tint)}"] = value
                values.append(value)
            record[f"{species}_monotonic_increase_25_50_100"] = bool(
                np.all(np.isfinite(values)) and values[0] < values[1] < values[2]
            )
        wogan_rows.append(record)
    return pd.DataFrame(h2o_rows), pd.DataFrame(wogan_rows)


def build_sensitivity_metrics(
    pairs: dict[tuple[str, str, float], tuple[ModelData, ModelData]]
) -> pd.DataFrame:
    columns = [
        "observable",
        "case_id",
        "cloud_id",
        "metallicity_xsolar",
        "rms_residual_ppm",
        "maximum_absolute_residual_ppm",
        "wavelength_at_maximum_um",
        "both_endpoints_converged",
    ]
    records: list[dict[str, Any]] = []
    for observable in OBSERVABLES:
        for case_id in CASE_ORDER:
            for cloud_id, metallicity in PANEL_ORDER:
                pair = pairs.get((case_id, cloud_id, metallicity))
                if pair is None or pair[0].spectra[observable] is None or pair[1].spectra[observable] is None:
                    continue
                low, high = pair
                residual = spectral_residual_ppm(low, high, observable)
                maximum_index = int(np.nanargmax(np.abs(residual)))
                records.append(
                    {
                        "observable": observable,
                        "case_id": case_id,
                        "cloud_id": cloud_id,
                        "metallicity_xsolar": metallicity,
                        "rms_residual_ppm": float(np.sqrt(np.mean(residual**2))),
                        "maximum_absolute_residual_ppm": float(np.abs(residual[maximum_index])),
                        "wavelength_at_maximum_um": float(low.wavelength_um[maximum_index]),
                        "both_endpoints_converged": low.climate_converged and high.climate_converged,
                    }
                )
    return pd.DataFrame(records, columns=columns)


def build_case_ranking(metrics: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for observable in OBSERVABLES:
        subset = metrics[metrics["observable"] == observable]
        medians = {
            case_id: (
                float(subset.loc[subset["case_id"] == case_id, "rms_residual_ppm"].median())
                if not subset.loc[subset["case_id"] == case_id].empty
                else float("nan")
            )
            for case_id in CASE_ORDER
        }
        hot = medians["gj_1214b_observed"]
        expected = bool(
            np.isfinite(hot)
            and np.isfinite(medians["k2_18b_observed"])
            and np.isfinite(medians["gj_1214b_low"])
            and medians["k2_18b_observed"] > hot
            and medians["gj_1214b_low"] > hot
        )
        records.append(
            {
                "observable": observable,
                "k2_18b_observed_median_rms_ppm": medians["k2_18b_observed"],
                "gj_1214b_low_median_rms_ppm": medians["gj_1214b_low"],
                "gj_1214b_observed_median_rms_ppm": hot,
                "both_255k_cases_exceed_gj1214b_observed": expected,
            }
        )
    return pd.DataFrame(records)


def expected_figure_stems() -> list[str]:
    stems = [f"pt_{case}" for case in CASE_ORDER]
    stems += [f"spectra_{observable}_{case}" for observable in OBSERVABLES for case in CASE_ORDER]
    stems += [f"abundance_{case}_{cloud}_{int(metallicity):03d}x" for case in CASE_ORDER for cloud, metallicity in PANEL_ORDER]
    stems += [f"residual_{observable}" for observable in OBSERVABLES]
    stems += [f"case_metric_{observable}" for observable in OBSERVABLES]
    stems += [f"headline_case_metric_{observable}" for observable in OBSERVABLES]
    stems += ["case_metric_co_co2"]
    return stems


FIGURE_GROUPS = (
    ("01_pt_profiles", "P-T profiles", "Three case-specific figures; each compares Tint across the four cloud/metallicity combinations."),
    ("02_spectra", "Emergent spectra", "Transmission, thermal-emission, and reflected-light spectra for all three cases."),
    ("03_abundances", "Abundance profiles", "One six-molecule figure for every case, cloud, and metallicity combination."),
    ("04_residuals", "Spectral residuals", "Tint=25 K versus Tint=100 K residuals for each observable."),
    ("05_comparisons", "Sensitivity comparisons", "Case-ranking, headline cloudy/100x, and CO/CO2 comparison figures."),
)


def figure_group(stem: str) -> str:
    if stem.startswith("pt_"):
        return "01_pt_profiles"
    if stem.startswith("spectra_"):
        return "02_spectra"
    if stem.startswith("abundance_"):
        return "03_abundances"
    if stem.startswith("residual_"):
        return "04_residuals"
    return "05_comparisons"


def figure_relative_stem(stem: str) -> Path:
    return Path(figure_group(stem)) / stem


def write_preflight_report(
    config_path: str | Path,
    input_directory: str | Path,
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    rows = manifests(load_experiment(config_path))
    discovery = discover_input_files(rows, input_directory)
    by_index = {int(row["run_index"]): row for row in rows}
    final_ready = not discovery.global_issues
    for record in discovery.records:
        index = record.get("run_index")
        path = record.get("path")
        if index is None or not path:
            final_ready = False
            continue
        issues = list(record.get("issues", []))
        if not issues:
            issues = validate_file(Path(path), by_index[int(index)])
        record["issues"] = issues
        record["final_valid"] = not issues
        if issues:
            final_ready = False
    output = Path(output_directory).expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(f"Preflight output directory exists: {output}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(discovery.records)
    frame["issues"] = frame["issues"].map(json.dumps)
    frame.to_csv(output / "preflight_inventory.csv", index=False)
    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_directory": str(Path(input_directory).expanduser().resolve()),
        "expected_models": 36,
        "matched_models": len(discovery.paths_by_index),
        "global_issues": discovery.global_issues,
        "final_ready": bool(final_ready and len(discovery.paths_by_index) == 36),
        "records": discovery.records,
    }
    (output / "preflight_inventory.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def generate_package(
    config_path: str | Path,
    output_directory: str | Path,
    mode: str,
    *,
    input_directory: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    if mode not in {"partial", "final"}:
        raise ValueError("mode must be partial or final")
    config = load_experiment(config_path)
    analysis_config = config.get("analysis", {})
    rows, models, excluded, discovery = load_models(config_path, mode, input_directory)
    output = Path(output_directory).resolve()
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    figures = temporary / "figures"
    tables = temporary / "tables"
    figures.mkdir()
    tables.mkdir()
    index = model_index(models)
    pairs = tint_endpoint_pairs(models)
    count = len(models)
    try:
        for case_id in CASE_ORDER:
            stem = f"pt_{case_id}"
            plot_pt_case(case_id, index, mode, count, figures / figure_relative_stem(stem))
        for observable in OBSERVABLES:
            for case_id in CASE_ORDER:
                stem = f"spectra_{observable}_{case_id}"
                plot_spectra_case(observable, case_id, index, mode, count, figures / figure_relative_stem(stem))
        for case_id in CASE_ORDER:
            for cloud_id, metallicity in PANEL_ORDER:
                stem = f"abundance_{case_id}_{cloud_id}_{int(metallicity):03d}x"
                plot_abundance_combination(case_id, cloud_id, metallicity, index, mode, count,
                                           figures / figure_relative_stem(stem))
        for observable in OBSERVABLES:
            stem = f"residual_{observable}"
            plot_residuals(
                observable,
                pairs,
                mode,
                count,
                figures / figure_relative_stem(stem),
                precision_guide=analysis_config.get("precision_guide"),
            )
            stem = f"case_metric_{observable}"
            plot_case_metric(observable, pairs, mode, count, figures / figure_relative_stem(stem))
            headline = analysis_config.get("headline_combination", {})
            stem = f"headline_case_metric_{observable}"
            plot_headline_case_metric(
                observable,
                pairs,
                mode,
                count,
                figures / figure_relative_stem(stem),
                cloud_id=str(headline.get("cloud_id", "fully_cloudy_virga")),
                metallicity=float(headline.get("metallicity_xsolar", 100.0)),
            )
        stem = "case_metric_co_co2"
        plot_chemistry_metric(pairs, mode, count, figures / figure_relative_stem(stem))

        abundance_pressure_bar = float(analysis_config.get("abundance_pressure_bar", 1.0e-3))
        summary = build_summary_table(rows, models, abundance_pressure_bar)
        summary.to_csv(tables / "photospheric_abundances_1mbar.csv", index=False)
        (tables / "photospheric_abundances_1mbar.tex").write_text(
            summary.to_latex(index=False, float_format=lambda value: f"{value:.6e}"), encoding="utf-8"
        )
        h2o, wogan = build_sanity_tables(models)
        h2o.to_csv(tables / "h2o_sanity_check.csv", index=False)
        wogan.to_csv(tables / "k2_18b_wogan_direction_check.csv", index=False)
        metrics = build_sensitivity_metrics(pairs)
        ranking = build_case_ranking(metrics)
        metrics.to_csv(tables / "sensitivity_metrics.csv", index=False)
        ranking.to_csv(tables / "expected_case_ranking.csv", index=False)

        inventory_frame = pd.DataFrame(discovery.records)
        inventory_frame["issues"] = inventory_frame["issues"].map(json.dumps)
        inventory_frame.to_csv(temporary / "preflight_inventory.csv", index=False)
        (temporary / "preflight_inventory.json").write_text(
            json.dumps(
                {
                    "input_directory": (
                        str(Path(input_directory).expanduser().resolve())
                        if input_directory is not None else None
                    ),
                    "schema_name": SCHEMA_NAME,
                    "schema_version": SCHEMA_VERSION,
                    "global_issues": discovery.global_issues,
                    "records": discovery.records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        source_rows = []
        included_indices = {model.row["run_index"] for model in models}
        for row in rows:
            path = discovery.paths_by_index.get(int(row["run_index"]))
            source_rows.append({
                "run_index": row["run_index"], "run_id": row["run_id"],
                "included": row["run_index"] in included_indices,
                "path": str(path) if path is not None else None,
                "sha256": _sha256(path) if path is not None and path.exists() else None,
                "exclusion_reasons": excluded.get(row["run_index"], []),
            })
        manifest = {
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": mode, "expected_models": 36, "included_models": count,
            "chemistry_mode": rows[0]["chemistry_mode"],
            "nonconverged_indices": [model.row["run_index"] for model in models if not model.climate_converged],
            "corrected_thermal_indices": [model.row["run_index"] for model in models if model.thermal_corrected],
            "input_directory": (
                str(Path(input_directory).expanduser().resolve())
                if input_directory is not None else None
            ),
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "sources": source_rows,
            "figure_stems": [str(figure_relative_stem(stem)) for stem in expected_figure_stems()],
        }
        (temporary / "frozen_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (temporary / "chart_map.csv").write_text(
            "family,question,variant,palette,output\n"
            "P-T,How does Tint change atmospheric structure?,faceted multi-series line,Tint categorical,figures/01_pt_profiles/pt_*.{png,pdf}\n"
            "Spectra,How does Tint change each observable?,faceted multi-series line,Tint categorical,figures/02_spectra/spectra_*.{png,pdf}\n"
            "Abundance,How does Tint change each species profile?,faceted log-profile line,Tint categorical,figures/03_abundances/abundance_*.{png,pdf}\n"
            "Residual,Where is Tint detectable?,multi-series line with benchmark,case categorical,figures/04_residuals/residual_*.{png,pdf}\n"
            "Case comparison,Does insolation or gravity control sensitivity?,faceted bar,case categorical,figures/05_comparisons/*metric*.{png,pdf}\n",
            encoding="utf-8",
        )
        qc_summary = {
            "mode": mode,
            "expected_models": 36,
            "included_models": count,
            "excluded_models": len(excluded),
            "endpoint_pairs": len(pairs),
            "all_climates_converged": bool(
                models and all(model.climate_converged for model in models)
            ),
            "h2o_advisories": int(h2o["advisory_over_0p1_dex"].sum()) if not h2o.empty else 0,
            "wogan_direction_checks": json.loads(wogan.to_json(orient="records")),
            "expected_case_ranking": json.loads(ranking.to_json(orient="records")),
            "discovery_global_issues": discovery.global_issues,
        }
        (temporary / "qc_summary.json").write_text(
            json.dumps(qc_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        figure_lines = [
            "# Tint-sensitivity figure index", "",
            f"Status: **{mode.upper()}** — {count}/36 included models.", "",
            "Partial outputs are diagnostic only. Dashed curves are not climate-converged; blank panels are intentional.", "",
            "Each folder keeps the publication PDF beside its matching PNG preview.", "",
        ]
        all_stems = expected_figure_stems()
        for folder, title, description in FIGURE_GROUPS:
            figure_lines += [f"## {title}", "", f"Folder: `figures/{folder}/`", "", description, ""]
            for stem in all_stems:
                if figure_group(stem) != folder:
                    continue
                relative = figure_relative_stem(stem)
                figure_lines.append(
                    f"- `{stem}`: [PNG](figures/{relative}.png) · [PDF](figures/{relative}.pdf)"
                )
            figure_lines.append("")
        figure_lines += ["", "## Excluded models", ""]
        figure_lines += [f"- {index}: {'; '.join(reasons)}" for index, reasons in sorted(excluded.items())] or ["- None"]
        figure_lines += ["", "## Tables", "", "- `photospheric_abundances_1mbar.csv` / `.tex`: 36-row 1 mbar and pressure-weighted column-mean abundance table.", "- `sensitivity_metrics.csv`: endpoint RMS and maximum spectral residual metrics.", "- `expected_case_ranking.csv`: low-Teq versus observed GJ 1214 b sensitivity check.", "- `h2o_sanity_check.csv`: endpoint H2O change and >0.1 dex advisory.", "- `k2_18b_wogan_direction_check.csv`: K2-18 b 100× CO/CO2 direction check."]
        (temporary / "FIGURE_INDEX.md").write_text("\n".join(figure_lines) + "\n", encoding="utf-8")
        (figures / "README.md").write_text(
            "# Figure folders\n\n"
            "See [`../FIGURE_INDEX.md`](../FIGURE_INDEX.md) for descriptions and links to every PNG and PDF.\n\n"
            + "\n".join(f"- `{folder}/`: {title}. {description}" for folder, title, description in FIGURE_GROUPS)
            + "\n",
            encoding="utf-8",
        )

        missing_exports = [
            f"{stem}.{suffix}" for stem in expected_figure_stems() for suffix in ("png", "pdf")
            if not (figures / figure_relative_stem(stem)).with_suffix(f".{suffix}").is_file()
        ]
        if missing_exports:
            raise RuntimeError(f"Figure export validation failed: {missing_exports}")
        if len(summary) != 36 or tuple(REQUIRED_SPECIES) != ("CH4", "CO2", "CO", "NH3", "HCN", "H2O"):
            raise RuntimeError("Summary-table validation failed")
        if output.exists():
            if not overwrite:
                raise FileExistsError(f"Output directory exists: {output}")
            shutil.rmtree(output)
        os.replace(temporary, output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the Tint-sensitivity figure package")
    parser.add_argument("--config", default="params/tint_sensitivity_36.yaml")
    parser.add_argument("--mode", choices=("partial", "final"), required=True)
    parser.add_argument("--input-dir")
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = generate_package(
        args.config,
        args.output,
        args.mode,
        input_directory=args.input_dir,
        overwrite=args.overwrite,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
