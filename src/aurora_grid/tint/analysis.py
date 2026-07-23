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
from .netcdf import validate_file


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _basic_legacy_issues(ds: xr.Dataset, row: dict[str, Any]) -> list[str]:
    required = {
        "pressure_bar", "temperature_k", "mole_fraction", "wavelength_um",
        "transmission_depth", "reflected_planet_star_flux_ratio", "climate_converged",
        "kzz_cm2_s_profile", "quench_enabled", "quench_applied", "diseq_chem",
        "self_consistent_kzz",
    }
    issues = [f"missing {name}" for name in sorted(required.difference(ds.variables))]
    if issues:
        return issues
    if ds.attrs.get("run_id") != row["run_id"]:
        issues.append("run_id mismatch")
    if tuple(str(value) for value in ds["species"].values.tolist()) != REQUIRED_SPECIES:
        issues.append("species ordering mismatch")
    numeric = [name for name in required if name in ds and np.issubdtype(ds[name].dtype, np.number)]
    if any(not np.all(np.isfinite(np.asarray(ds[name].values))) for name in numeric):
        issues.append("non-finite required values")
    if not np.all(np.asarray(ds["kzz_cm2_s_profile"].values) == 1.0e10):
        issues.append("Kzz is not fixed at 1e10")
    expected = (
        (1, 1, 1, 0)
        if row.get("chemistry_mode", "disequilibrium_quench") == "disequilibrium_quench"
        else (0, 0, 0, 0)
    )
    actual = (
        int(ds["quench_enabled"].item()), int(ds["quench_applied"].item()),
        int(ds["diseq_chem"].item()), int(ds["self_consistent_kzz"].item()),
    )
    if actual != expected:
        issues.append(f"chemistry controls mismatch: got {actual}, expected {expected}")
    return issues


def load_models(config_path: str | Path, mode: str) -> tuple[list[dict[str, Any]], list[ModelData], dict[int, list[str]]]:
    rows = manifests(load_experiment(config_path))
    loaded: list[ModelData] = []
    excluded: dict[int, list[str]] = {}
    for row in rows:
        path = Path(row["output_path"])
        if not path.exists():
            excluded[row["run_index"]] = ["missing NetCDF"]
            continue
        if mode == "final":
            issues = validate_file(path, row)
            if issues:
                excluded[row["run_index"]] = issues
                continue
        with xr.open_dataset(path) as source:
            ds = source.load()
        if mode == "partial":
            issues = _basic_legacy_issues(ds, row)
            if issues:
                excluded[row["run_index"]] = issues
                continue
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
    if not loaded:
        raise RuntimeError("No valid model outputs are available for plotting")
    if mode == "final":
        if excluded or len(loaded) != 36:
            raise RuntimeError(f"Final package requires 36 valid models; loaded={len(loaded)}, excluded={excluded}")
        nonconverged = [model.row["run_index"] for model in loaded if not model.climate_converged]
        if nonconverged:
            raise RuntimeError(f"Final package requires climate convergence; nonconverged={nonconverged}")
    return rows, loaded, excluded


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
    ax.invert_yaxis()


def _watermark(fig: plt.Figure, mode: str, loaded_count: int) -> None:
    if mode == "partial":
        fig.text(
            0.5, 0.5, f"PARTIAL — {loaded_count}/36 — NOT FOR SCIENTIFIC CITATION",
            ha="center", va="center", rotation=25, fontsize=22, color="#B42318",
            alpha=0.12, weight="bold", zorder=1000,
        )


def _save_figure(fig: plt.Figure, stem: Path, mode: str, loaded_count: int) -> None:
    _watermark(fig, mode, loaded_count)
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


def plot_residuals(observable: str, pairs: dict[tuple[str, str, float], tuple[ModelData, ModelData]], mode: str, count: int, stem: Path) -> None:
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
            residual = np.abs(np.asarray(high.spectra[observable]) - np.asarray(low.spectra[observable])) * 1e6
            label = f"{CASE_SHORT[case_id]} · {'clear' if cloud_id == 'cloud_free' else 'cloudy'} · {metallicity:g}×"
            ax.plot(low.wavelength_um, residual, color=colors[case_id], linestyle=line_styles[(cloud_id, metallicity)], linewidth=1.4, alpha=1.0 if low.climate_converged and high.climate_converged else 0.55, label=label)
            plotted += 1
    ax.axhspan(20, 50, color="#697386", alpha=0.10, label="Illustrative JWST 20–50 ppm band")
    ax.axhline(30, color="#323A46", linewidth=1.0, linestyle="--", label="30 ppm reference")
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
            delta_ppm = (np.asarray(high.spectra[observable]) - np.asarray(low.spectra[observable])) * 1e6
            values.append(float(np.sqrt(np.mean(delta_ppm ** 2))))
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


def build_summary_table(rows: list[dict[str, Any]], models: Iterable[ModelData]) -> pd.DataFrame:
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
            "abundance_pressure_bar": 1.0e-3,
        }
        for species_index, species in enumerate(REQUIRED_SPECIES):
            record[f"{species}_mole_fraction_at_1mbar"] = (
                _interpolate_log_pressure(model, model.mole_fraction[:, species_index], 1.0e-3)
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


def expected_figure_stems() -> list[str]:
    stems = [f"pt_{case}" for case in CASE_ORDER]
    stems += [f"spectra_{observable}_{case}" for observable in OBSERVABLES for case in CASE_ORDER]
    stems += [f"abundance_{case}_{cloud}_{int(metallicity):03d}x" for case in CASE_ORDER for cloud, metallicity in PANEL_ORDER]
    stems += [f"residual_{observable}" for observable in OBSERVABLES]
    stems += [f"case_metric_{observable}" for observable in OBSERVABLES]
    stems += ["case_metric_co_co2"]
    return stems


def generate_package(config_path: str | Path, output_directory: str | Path, mode: str, *, overwrite: bool = False) -> Path:
    if mode not in {"partial", "final"}:
        raise ValueError("mode must be partial or final")
    rows, models, excluded = load_models(config_path, mode)
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
            plot_pt_case(case_id, index, mode, count, figures / f"pt_{case_id}")
        for observable in OBSERVABLES:
            for case_id in CASE_ORDER:
                plot_spectra_case(observable, case_id, index, mode, count, figures / f"spectra_{observable}_{case_id}")
        for case_id in CASE_ORDER:
            for cloud_id, metallicity in PANEL_ORDER:
                plot_abundance_combination(case_id, cloud_id, metallicity, index, mode, count,
                                           figures / f"abundance_{case_id}_{cloud_id}_{int(metallicity):03d}x")
        for observable in OBSERVABLES:
            plot_residuals(observable, pairs, mode, count, figures / f"residual_{observable}")
            plot_case_metric(observable, pairs, mode, count, figures / f"case_metric_{observable}")
        plot_chemistry_metric(pairs, mode, count, figures / "case_metric_co_co2")

        summary = build_summary_table(rows, models)
        summary.to_csv(tables / "photospheric_abundances_1mbar.csv", index=False)
        (tables / "photospheric_abundances_1mbar.tex").write_text(
            summary.to_latex(index=False, float_format=lambda value: f"{value:.6e}"), encoding="utf-8"
        )
        h2o, wogan = build_sanity_tables(models)
        h2o.to_csv(tables / "h2o_sanity_check.csv", index=False)
        wogan.to_csv(tables / "k2_18b_wogan_direction_check.csv", index=False)

        source_rows = []
        included_indices = {model.row["run_index"] for model in models}
        for row in rows:
            path = Path(row["output_path"])
            source_rows.append({
                "run_index": row["run_index"], "run_id": row["run_id"],
                "included": row["run_index"] in included_indices,
                "path": str(path), "sha256": _sha256(path) if path.exists() else None,
                "exclusion_reasons": excluded.get(row["run_index"], []),
            })
        manifest = {
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": mode, "expected_models": 36, "included_models": count,
            "chemistry_mode": rows[0]["chemistry_mode"],
            "nonconverged_indices": [model.row["run_index"] for model in models if not model.climate_converged],
            "corrected_thermal_indices": [model.row["run_index"] for model in models if model.thermal_corrected],
            "sources": source_rows, "figure_stems": expected_figure_stems(),
        }
        (temporary / "frozen_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (temporary / "chart_map.csv").write_text(
            "family,question,variant,palette,output\n"
            "P-T,How does Tint change atmospheric structure?,faceted multi-series line,Tint categorical,figures/pt_*.{png,pdf}\n"
            "Spectra,How does Tint change each observable?,faceted multi-series line,Tint categorical,figures/spectra_*.{png,pdf}\n"
            "Abundance,How does Tint change each species profile?,faceted log-profile line,Tint categorical,figures/abundance_*.{png,pdf}\n"
            "Residual,Where is Tint detectable?,multi-series line with benchmark,case categorical,figures/residual_*.{png,pdf}\n"
            "Case comparison,Does insolation or gravity control sensitivity?,faceted bar,case categorical,figures/case_metric_*.{png,pdf}\n",
            encoding="utf-8",
        )
        figure_lines = [
            "# Tint-sensitivity figure index", "",
            f"Status: **{mode.upper()}** — {count}/36 included models.", "",
            "Partial outputs are diagnostic only. Dashed curves are not climate-converged; blank panels are intentional.", "",
            "## Figures", "",
        ]
        figure_lines += [f"- `{stem}.png` and `{stem}.pdf`" for stem in expected_figure_stems()]
        figure_lines += ["", "## Excluded models", ""]
        figure_lines += [f"- {index}: {'; '.join(reasons)}" for index, reasons in sorted(excluded.items())] or ["- None"]
        figure_lines += ["", "## Tables", "", "- `photospheric_abundances_1mbar.csv` / `.tex`: 36-row standardized 1 mbar abundance table.", "- `h2o_sanity_check.csv`: endpoint H2O change and >0.1 dex advisory.", "- `k2_18b_wogan_direction_check.csv`: K2-18 b 100× CO/CO2 direction check."]
        (temporary / "FIGURE_INDEX.md").write_text("\n".join(figure_lines) + "\n", encoding="utf-8")

        missing_exports = [
            f"{stem}.{suffix}" for stem in expected_figure_stems() for suffix in ("png", "pdf")
            if not (figures / f"{stem}.{suffix}").is_file()
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
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = generate_package(args.config, args.output, args.mode, overwrite=args.overwrite)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
