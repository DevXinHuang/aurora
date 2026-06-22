#!/usr/bin/env python3
"""Combine Aurora/Roadrunner clear + cloudy PICASO components into one patchy-cloud NetCDF.

This is intentionally separate from the normal runner because the current Aurora manifest
only supports cloud_fraction = 0.0 or 1.0 for real PICASO runs. Patchiness is a linear
area-weighted disk average of the two component spectra.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


def _as_float(value: Any) -> float:
    return float(str(value).strip())


def _resolve(path: str | Path, repo_root: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else repo_root / p


def _load_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _find_component(rows: list[dict[str, str]], cloud_fraction: float) -> dict[str, str]:
    matches = [r for r in rows if np.isclose(_as_float(r["cloud_fraction"]), cloud_fraction)]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one row with cloud_fraction={cloud_fraction}; found {len(matches)}")
    return matches[0]


def _weighted_dataarray(clear_da: xr.DataArray, cloudy_da: xr.DataArray, fhole: float) -> xr.DataArray:
    clear_aligned, cloudy_aligned = xr.align(clear_da, cloudy_da, join="exact")
    out = fhole * clear_aligned + (1.0 - fhole) * cloudy_aligned
    out.attrs.update(clear_da.attrs)
    out.attrs["patchy_combination"] = "area_weighted_clear_cloudy"
    out.attrs["patchy_weighting_formula"] = "fhole * clear + (1 - fhole) * cloudy"
    return out


def combine(clear: xr.Dataset, cloudy: xr.Dataset, fhole: float) -> xr.Dataset:
    if not (0.0 <= fhole <= 1.0):
        raise ValueError("fhole must be between 0 and 1")
    cloud_fraction = 1.0 - fhole

    # Start from cloudy so required cloud variables and coordinates remain present.
    ds = cloudy.copy(deep=True)

    linear_vars = [
        "reflected_planet_star_flux_ratio",
        "geometric_albedo",
        "reflected_flux",
        "thermal_flux",
        "thermal_planet_star_flux_ratio",
        "total_planet_star_flux_ratio",
        "bond_albedo",
        "mean_molecular_weight_amu",
    ]
    for name in linear_vars:
        if name in clear and name in cloudy:
            ds[name] = _weighted_dataarray(clear[name], cloudy[name], fhole)

    # Cloud optical depth can be stored as an area-mean column diagnostic.
    # Single-scattering albedo and asymmetry are properties of cloudy particles, not
    # a true linear mixture, so leave them as the cloudy-column particle values.
    if "cloud_optical_depth" in clear and "cloud_optical_depth" in cloudy:
        ds["cloud_optical_depth"] = _weighted_dataarray(clear["cloud_optical_depth"], cloudy["cloud_optical_depth"], fhole)
        ds["cloud_optical_depth"].attrs["comment"] = "Area-mean optical depth for patchy mixture; clear holes contribute zero opacity."
    for name in ["single_scattering_albedo", "asymmetry_factor"]:
        if name in ds:
            ds[name].attrs["comment"] = "Cloudy-column particle property retained for the cloudy part of the patchy mixture; not area-linearly mixed."

    # Recompute reflected fraction when possible.
    if "reflected_planet_star_flux_ratio" in ds and "thermal_planet_star_flux_ratio" in ds:
        denom = ds["reflected_planet_star_flux_ratio"] + ds["thermal_planet_star_flux_ratio"]
        ds["reflected_fraction"] = xr.where(denom > 0, ds["reflected_planet_star_flux_ratio"] / denom, 0.0)
        ds["reflected_fraction"].attrs.update({"long_name": "reflected fraction of total planet-star flux ratio", "units": "1"})

    # Scalar metadata variables.
    for scalar_name in ["cloud_fraction"]:
        if scalar_name in ds:
            ds[scalar_name] = xr.DataArray(float(cloud_fraction), attrs=ds[scalar_name].attrs)
            ds[scalar_name].attrs["comment"] = "Area fraction covered by cloudy column in patchy-cloud mixture."
    ds["cloud_hole_fraction"] = xr.DataArray(float(fhole), attrs={"units": "1", "long_name": "clear-hole area fraction"})

    if "runtime_seconds" in clear and "runtime_seconds" in cloudy and "runtime_seconds" in ds:
        try:
            ds["runtime_seconds"] = clear["runtime_seconds"] + cloudy["runtime_seconds"]
        except Exception:
            pass

    ds.attrs.update(
        {
            "title": "Aurora/Roadrunner PICASO patchy-cloud sidequest case",
            "model_name": "PICASO_T1000_g100_m+000_CO100_fsed3_frac50_patchy",
            "run_type": "patchy_cloud_linear_combo_from_two_picaso_component_runs",
            "cloud_model": "patchy_none_plus_virga",
            "patchy_weighting_formula": "patchy = fhole * clear_column + (1 - fhole) * cloudy_column",
            "cloud_hole_fraction": str(float(fhole)),
            "cloud_fraction": str(float(cloud_fraction)),
            "component_clear_source": clear.attrs.get("run_id", "unknown"),
            "component_cloudy_source": cloudy.attrs.get("run_id", "unknown"),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    return ds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-nc", required=True, type=Path)
    parser.add_argument("--hole-fraction", type=float, default=0.5)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    manifest_path = _resolve(args.manifest, repo_root)
    rows = _load_manifest_rows(manifest_path)
    clear_row = _find_component(rows, 0.0)
    cloudy_row = _find_component(rows, 1.0)
    clear_nc = _resolve(clear_row["output_nc"], repo_root)
    cloudy_nc = _resolve(cloudy_row["output_nc"], repo_root)
    out_nc = _resolve(args.output_nc, repo_root)

    if not clear_nc.exists():
        raise FileNotFoundError(f"Missing clear component NetCDF: {clear_nc}")
    if not cloudy_nc.exists():
        raise FileNotFoundError(f"Missing cloudy component NetCDF: {cloudy_nc}")
    if out_nc.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists; pass --overwrite to replace: {out_nc}")

    with xr.open_dataset(clear_nc) as clear_open, xr.open_dataset(cloudy_nc) as cloudy_open:
        clear = clear_open.load()
        cloudy = cloudy_open.load()

    ds = combine(clear, cloudy, args.hole_fraction)
    ds.attrs["source_manifest_row"] = json.dumps(
        {"clear_component": clear_row, "cloudy_component": cloudy_row},
        sort_keys=True,
    )
    out_nc.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_nc.with_suffix(out_nc.suffix + ".tmp")
    ds.to_netcdf(tmp)
    tmp.replace(out_nc)

    print(f"WROTE PATCHY PICASO NC: {out_nc}")
    print(ds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
