from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from aurora_grid.io.netcdf_schema import validate_aurora_netcdf_schema


OUTPUT_DIR = Path("roadrunner_egp/aurora_subneptune_grid/outputs/smoke_test_aurora_subneptune")
NC_DIR = OUTPUT_DIR / "nc"
QC_DIR = OUTPUT_DIR / "qc"
QC_DIR.mkdir(parents=True, exist_ok=True)


def _safe_attr_json(ds, name):
    value = ds.attrs.get(name)
    if value is None:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _get_scalar(ds, name):
    if name in ds:
        try:
            return float(ds[name].values)
        except Exception:
            return np.nan
    return np.nan


def summarize_file(path: Path) -> dict:
    with xr.open_dataset(path) as ds:
        issues = validate_aurora_netcdf_schema(ds)
        errors = [x for x in issues if x.startswith("ERROR:")]
        warnings = [x for x in issues if x.startswith("WARNING:")]

        return {
            "file": str(path),
            "run_index": int(_get_scalar(ds, "run_index")),
            "schema_name": ds.attrs.get("schema_name", ""),
            "schema_version": ds.attrs.get("schema_version", ""),
            "n_errors": len(errors),
            "n_warnings": len(warnings),
            "errors": " | ".join(errors),
            "warnings": " | ".join(warnings),
            "cloud_fraction": _get_scalar(ds, "cloud_fraction"),
            "phase_angle_deg": _get_scalar(ds, "phase_angle_deg"),
            "metallicity_xsolar": _get_scalar(ds, "metallicity_xsolar"),
            "n_wavelength": ds.sizes.get("wavelength", np.nan),
            "n_level": ds.sizes.get("level", np.nan),
            "n_layer": ds.sizes.get("layer", np.nan),
            "n_species": ds.sizes.get("species", np.nan),
            "max_reflected_ratio": float(np.nanmax(ds["reflected_planet_star_flux_ratio"].values)),
            "min_geometric_albedo": float(np.nanmin(ds["geometric_albedo"].values)),
            "max_geometric_albedo": float(np.nanmax(ds["geometric_albedo"].values)),
            "max_cloud_optical_depth": float(np.nanmax(ds["cloud_optical_depth"].values)),
            "min_ssa": float(np.nanmin(ds["single_scattering_albedo"].values)),
            "max_ssa": float(np.nanmax(ds["single_scattering_albedo"].values)),
            "min_asymmetry": float(np.nanmin(ds["asymmetry_factor"].values)),
            "max_asymmetry": float(np.nanmax(ds["asymmetry_factor"].values)),
        }


def plot_spectra(paths):
    plt.figure(figsize=(8, 5))
    for path in paths:
        with xr.open_dataset(path) as ds:
            wl = ds["wavelength_um"].values
            y = ds["reflected_planet_star_flux_ratio"].values
            label = f"run {int(ds['run_index'].values)} cf={float(ds['cloud_fraction'].values):.0f} phase={float(ds['phase_angle_deg'].values):.0f}"
            plt.plot(wl, y, label=label)

    plt.yscale("log")
    plt.xlabel("Wavelength (um)")
    plt.ylabel("Reflected planet/star flux ratio")
    plt.title("QC: reflected-light spectra")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(QC_DIR / "qc_reflected_spectra.png", dpi=180)
    plt.close()


def plot_albedo(paths):
    plt.figure(figsize=(8, 5))
    for path in paths:
        with xr.open_dataset(path) as ds:
            wl = ds["wavelength_um"].values
            y = ds["geometric_albedo"].values
            label = f"run {int(ds['run_index'].values)} cf={float(ds['cloud_fraction'].values):.0f} phase={float(ds['phase_angle_deg'].values):.0f}"
            plt.plot(wl, y, label=label)

    plt.xlabel("Wavelength (um)")
    plt.ylabel("Geometric albedo")
    plt.title("QC: geometric albedo spectra")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(QC_DIR / "qc_geometric_albedo.png", dpi=180)
    plt.close()


def plot_pt_profiles(paths):
    plt.figure(figsize=(6, 7))
    for path in paths:
        with xr.open_dataset(path) as ds:
            t = ds["temperature_k"].values
            p = ds["pressure_bar"].values
            label = f"run {int(ds['run_index'].values)} cf={float(ds['cloud_fraction'].values):.0f}"
            plt.semilogy(t, p, label=label)

    plt.gca().invert_yaxis()
    plt.xlabel("Temperature (K)")
    plt.ylabel("Pressure (bar)")
    plt.title("QC: pressure-temperature profiles")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(QC_DIR / "qc_pt_profiles.png", dpi=180)
    plt.close()


def plot_cloud_heatmap(paths):
    cloudy_path = None
    for path in paths:
        with xr.open_dataset(path) as ds:
            if float(ds["cloud_fraction"].values) > 0:
                cloudy_path = path
                break

    if cloudy_path is None:
        return

    with xr.open_dataset(cloudy_path) as ds:
        wl = ds["wavelength_um"].values
        layer = ds["layer"].values
        tau = ds["cloud_optical_depth"].values
        log_tau = np.log10(np.maximum(tau, 1e-30))

        plt.figure(figsize=(8, 5))
        plt.pcolormesh(wl, layer, log_tau, shading="auto")
        plt.xlabel("Wavelength (um)")
        plt.ylabel("Layer index")
        plt.title(f"QC: log10 cloud optical depth, run {int(ds['run_index'].values)}")
        plt.colorbar(label="log10(cloud optical depth)")
        plt.tight_layout()
        plt.savefig(QC_DIR / "qc_cloud_optical_depth_heatmap.png", dpi=180)
        plt.close()


def plot_qc_summary(summary):
    plt.figure(figsize=(7, 4))
    x = np.arange(len(summary))
    plt.bar(x, summary["n_errors"].values)
    plt.xticks(x, summary["run_index"].astype(str).values)
    plt.xlabel("Run index")
    plt.ylabel("Number of schema errors")
    plt.title("QC: schema error count per run")
    plt.tight_layout()
    plt.savefig(QC_DIR / "qc_schema_errors.png", dpi=180)
    plt.close()


def main():
    paths = sorted(NC_DIR.glob("run_*.nc"))
    if not paths:
        raise SystemExit(f"No NetCDF files found in {NC_DIR}")

    rows = [summarize_file(path) for path in paths]
    summary = pd.DataFrame(rows).sort_values("run_index")
    summary_path = QC_DIR / "qc_summary.csv"
    summary.to_csv(summary_path, index=False)

    plot_spectra(paths)
    plot_albedo(paths)
    plot_pt_profiles(paths)
    plot_cloud_heatmap(paths)
    plot_qc_summary(summary)

    print(f"Read {len(paths)} NetCDF files")
    print(f"Wrote {summary_path}")
    print("Wrote plots:")
    for path in sorted(QC_DIR.glob("*.png")):
        print(" ", path)


if __name__ == "__main__":
    main()
