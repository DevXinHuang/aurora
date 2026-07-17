#!/usr/bin/env python3
"""Build three representative reflected-light NetCDF spectra from climate caches."""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GRID_ROOT = ROOT / "roadrunner_egp" / "aurora_subneptune_grid"
SRC_ROOT = GRID_ROOT / "src"
ROADRUNNER_ROOT = ROOT / "roadrunner_egp"
OUT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = GRID_ROOT / "params" / "aurora_subneptune_v1_dhuang.yaml"
CACHE_DIR = GRID_ROOT / "outputs" / "aurora_subneptune_v1_dhuang" / "climate_cache"
OPACITY_DIR = ROOT / "picaso4_reference" / "opacities"

for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("picaso_refdata", str(ROOT / "picaso4_reference"))
os.environ.setdefault("PYSYN_CDBS", str(ROOT / "picaso4_reference" / "stellar_grids"))
os.environ.setdefault("ROADRUNNER_SCIENCE_INPUTS", str(ROOT / "science_inputs"))
os.environ.setdefault("ROADRUNNER_PICASO_VIRGA_DIR", str(ROOT / "picaso4_reference" / "virga" / "virga"))
os.environ.setdefault("MPLCONFIGDIR", str(OUT_DIR / ".matplotlib"))

import matplotlib
import numpy as np
import xarray as xr
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from astropy import units as u
from astropy.constants import R_earth, R_sun
from picaso import justdoit as jdi

from aurora_grid.cahoy_climate_cache import load_climate_cache
from aurora_grid.io.netcdf_schema import (
    build_aurora_run_dataset,
    validate_aurora_netcdf_schema,
    write_aurora_run_netcdf,
)
from aurora_grid.parameters import create_manifest_dataframe
from aurora_grid.picaso_runner import (
    _system_from_row,
    run_picaso_model_from_climate_cache,
)
from aurora_grid.qc.science_checks import validate_science
from roadrunner.config import THERMAL_NUM_GANGLE, THERMAL_NUM_TANGLE, blackbody
from roadrunner.runner import extract_planet_fluxes


COMMON = {
    "star_index": 0,
    "planet_radius_rearth": 2.5,
    "planet_mass_mearth": 10.183,
    "c_to_o_xsolar": 1.0,
    "kzz_cm2_s": 1.0e9,
    "fsed": 3.0,
    "insolation_searth": 1.5,
    "phase_deg": 0.0,
}

CASES = [
    {
        "case_id": "case01_clear_solar",
        "label": "Clear, 1× solar metallicity",
        "short_label": "Clear · 1× solar",
        "climate_group_index": 23611,
        "metallicity_xsolar": 1.0,
        "cloud_fraction": 0.0,
        "rationale": "Reference atmosphere; isolates the baseline molecular spectrum without clouds.",
        "color": "#3166D5",
        "linestyle": "-",
    },
    {
        "case_id": "case02_cloudy_solar",
        "label": "Fully cloudy, 1× solar metallicity",
        "short_label": "Cloudy · 1× solar",
        "climate_group_index": 23691,
        "metallicity_xsolar": 1.0,
        "cloud_fraction": 1.0,
        "rationale": "Cloud comparison at fixed composition; shows continuum brightening and muted gas bands.",
        "color": "#C68120",
        "linestyle": "--",
    },
    {
        "case_id": "case03_clear_100x_solar",
        "label": "Clear, 100× solar metallicity",
        "short_label": "Clear · 100× solar",
        "climate_group_index": 24811,
        "metallicity_xsolar": 100.0,
        "cloud_fraction": 0.0,
        "rationale": "Composition comparison without clouds; shows the effect of enhanced heavy elements.",
        "color": "#D35D32",
        "linestyle": "-.",
    },
]


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid config: {CONFIG_PATH}")
    return config


def local_opacity_path(selected_ck_file: str) -> Path:
    path = OPACITY_DIR / Path(selected_ck_file).name
    if not path.is_file():
        raise FileNotFoundError(f"Required local preweighted opacity file is missing: {path}")
    return path


def make_row(config: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    selected = deepcopy(config)
    selected.update(
        {
            "stars": [config["stars"][COMMON["star_index"]]],
            "planet_radius_rearth": [COMMON["planet_radius_rearth"]],
            "planet_mass_mearth": [COMMON["planet_mass_mearth"]],
            "metallicity_xsolar": [case["metallicity_xsolar"]],
            "c_to_o_xsolar": [COMMON["c_to_o_xsolar"]],
            "kzz_cm2_s": [COMMON["kzz_cm2_s"]],
            "cloud_fraction": [case["cloud_fraction"]],
            "fsed": [COMMON["fsed"]],
            "insolation_searth": [COMMON["insolation_searth"]],
            "phase_deg": [COMMON["phase_deg"]],
            "output_root": str(OUT_DIR / "netcdf"),
        }
    )
    row = dict(create_manifest_dataframe(selected).rows[0])
    row.update(
        {
            "climate_group_index": int(case["climate_group_index"]),
            "output_nc": str(OUT_DIR / "netcdf" / f"{case['case_id']}.nc"),
            "wavelength_grid_mode": "constant_resolution",
            "wavelength_min_um": 0.30,
            "wavelength_max_um": 15.0,
            "wavelength_resolution": 1500.0,
            "wavelength_points": int(math.ceil(math.log(15.0 / 0.30) * 1500.0)) + 1,
            "netcdf_optional_variables": [
                "thermal_planet_star_flux_ratio",
                "total_planet_star_flux_ratio",
            ],
            "notes": (
                "Full-range reflected plus thermal spectrum (0.30-15 microns) at R=1500 from an existing converged Aurora climate cache. "
                "One of three controlled comparison cases with fixed bulk and orbital parameters."
            ),
        }
    )
    return row


def cache_path(index: int) -> Path:
    return CACHE_DIR / f"climate_{index:02d}.npz"


def build_case(config: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    row = make_row(config, case)
    source_cache = cache_path(case["climate_group_index"])
    source_pickle = source_cache.with_name(f"{source_cache.stem}_case.pkl")
    if not source_cache.is_file() or not source_pickle.is_file():
        raise FileNotFoundError(f"Missing cache pair for climate group {case['climate_group_index']}")

    climate_cache = load_climate_cache(source_cache)
    diagnostics = climate_cache.get("metadata", {}).get("diagnostics", {})
    if not bool(int(diagnostics.get("climate_converged", 0))):
        raise RuntimeError(f"Climate group {case['climate_group_index']} is not converged")
    climate_cache["selected_ck_file"] = str(local_opacity_path(climate_cache["selected_ck_file"]))

    started = perf_counter()
    model_output = run_picaso_model_from_climate_cache(row, climate_cache)
    output_grid = np.asarray(model_output["wavelength_um"], dtype=float)
    opacity = jdi.opannection(
        ck_db=climate_cache["selected_ck_file"],
        wave_range=[float(np.nanmin(output_grid)), float(np.nanmax(output_grid))],
        method="preweighted",
    )
    picaso_case = model_output["picaso_case"]
    system = _system_from_row(row)
    picaso_case.gravity(
        mass=float(row["planet_mass_mearth"]),
        mass_unit=u.M_earth,
        radius=float(row["planet_radius_rearth"]),
        radius_unit=u.R_earth,
    )
    picaso_case.star(
        opacity,
        temp=system.tstar_k,
        metal=0,
        logg=4.44,
        radius=system.rstar_rsun,
        radius_unit=u.R_sun,
        semi_major=system.a_au,
        semi_major_unit=u.AU,
    )
    picaso_case.phase_angle(
        0.0,
        num_gangle=THERMAL_NUM_GANGLE,
        num_tangle=THERMAL_NUM_TANGLE,
    )
    thermal_output = picaso_case.spectrum(
        opacity,
        calculation="thermal",
        as_dict=True,
        full_output=True,
    )
    _, reflected_flux, thermal_flux = extract_planet_fluxes(
        model_output["picaso_out_reflected"],
        thermal_output,
        output_grid,
        system,
    )
    wavelength_cm = output_grid * 1.0e-4
    stellar_surface_flux_per_um = np.pi * np.squeeze(blackbody(system.tstar_k, wavelength_cm)) * 1.0e-4
    projected_area_ratio = (
        float(row["planet_radius_rearth"]) * R_earth.value
        / (float(row["star_radius_rsun"]) * R_sun.value)
    ) ** 2
    thermal_ratio = np.nan_to_num(
        np.divide(
            thermal_flux,
            stellar_surface_flux_per_um,
            out=np.zeros_like(thermal_flux),
            where=stellar_surface_flux_per_um > 0,
        )
        * projected_area_ratio
    )
    model_output.update(
        {
            "picaso_out_emission": thermal_output,
            "fpfs_emission": thermal_ratio,
            "thermal_planet_star_flux_ratio": thermal_ratio,
            "total_planet_star_flux_ratio": np.asarray(model_output["fpfs_reflection"], dtype=float) + thermal_ratio,
            "absolute_flux_reflected": reflected_flux,
            "absolute_flux_thermal": thermal_flux,
        }
    )
    model_output["picaso_metadata"]["thermal_source"] = "picaso_cached_case_spectrum"
    runtime_seconds = perf_counter() - started
    dataset = build_aurora_run_dataset(
        model_output,
        row,
        runtime_seconds=runtime_seconds,
        run_success=True,
    )
    dataset.attrs.update(
        {
            "comparison_case_id": case["case_id"],
            "comparison_case_label": case["label"],
            "source_climate_npz": str(source_cache.resolve()),
            "source_climate_pkl": str(source_pickle.resolve()),
            "display_spectrum_resolution": 1500.0,
        }
    )

    schema_issues = validate_aurora_netcdf_schema(dataset)
    science_flags = validate_science(dataset, row=row)
    errors = [issue for issue in schema_issues if issue.startswith("ERROR:")]
    errors.extend(flag.message for flag in science_flags if flag.severity == "fail")
    if errors:
        raise RuntimeError(f"QC failed for {case['case_id']}: {'; '.join(errors)}")

    output_path = Path(row["output_nc"])
    status = write_aurora_run_netcdf(dataset, output_path, overwrite=True)
    return {
        **{key: value for key, value in case.items() if key not in {"color", "linestyle"}},
        "output_nc": str(output_path.resolve()),
        "source_npz": str(source_cache.resolve()),
        "source_pkl": str(source_pickle.resolve()),
        "runtime_seconds": round(runtime_seconds, 3),
        "wavelength_points": int(row["wavelength_points"]),
        "schema_warnings": " | ".join(issue for issue in schema_issues if not issue.startswith("ERROR:")),
        "science_flags": " | ".join(f"{flag.severity}: {flag.message}" for flag in science_flags),
        "write_status": status["status"],
        "star_teff_k": row["star_teff_k"],
        "star_radius_rsun": row["star_radius_rsun"],
        "planet_radius_rearth": row["planet_radius_rearth"],
        "planet_mass_mearth": row["planet_mass_mearth"],
        "gravity_ms2": row["gravity_ms2"],
        "c_to_o_xsolar": row["c_to_o_xsolar"],
        "kzz_cm2_s": row["kzz_cm2_s"],
        "fsed": row["fsed"],
        "insolation_searth": row["insolation_searth"],
        "phase_deg": row["phase_deg"],
    }


def render_plot(results: list[dict[str, Any]]) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "text.color": "#172033",
            "axes.labelcolor": "#344054",
            "xtick.color": "#667085",
            "ytick.color": "#667085",
        }
    )
    fig, (ax_albedo, ax_contrast) = plt.subplots(
        2,
        1,
        figsize=(13.333, 7.5),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 0.82], "hspace": 0.17},
        facecolor="white",
    )
    fig.subplots_adjust(left=0.085, right=0.965, top=0.79, bottom=0.13)

    for case, result in zip(CASES, results):
        with xr.open_dataset(result["output_nc"]) as dataset:
            wavelength = np.asarray(dataset["wavelength_um"].values, dtype=float)
            albedo = np.asarray(dataset["geometric_albedo"].values, dtype=float)
            contrast_ppm = 1.0e6 * np.asarray(dataset["reflected_planet_star_flux_ratio"].values, dtype=float)
            total_contrast_ppm = 1.0e6 * np.asarray(dataset["total_planet_star_flux_ratio"].values, dtype=float)
        style = {
            "color": case["color"],
            "linestyle": case["linestyle"],
            "linewidth": 1.8,
            "label": case["short_label"],
        }
        ax_albedo.plot(wavelength, albedo, **style)
        ax_contrast.plot(wavelength, np.clip(total_contrast_ppm, 1.0e-12, None), **style)

    for axis in (ax_albedo, ax_contrast):
        axis.set_xlim(0.30, 15.0)
        axis.set_xscale("log")
        axis.grid(True, color="#D7DDE8", linewidth=0.7, alpha=0.75)
        axis.set_axisbelow(True)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#98A2B3")
        axis.spines["bottom"].set_color("#98A2B3")

    ax_albedo.set_ylim(bottom=0)
    ax_contrast.set_yscale("log")
    ax_albedo.set_ylabel("Geometric albedo")
    ax_contrast.set_ylabel("Total contrast (ppm)\nreflected + thermal")
    ax_contrast.set_xlabel("Wavelength (µm)")
    ax_contrast.set_xticks([0.3, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0])
    ax_contrast.set_xticklabels(["0.3", "0.5", "1", "2", "3", "5", "10", "15"])
    ax_albedo.legend(loc="upper right", frameon=False, ncol=3, fontsize=9.5, handlelength=3.2)

    fig.text(0.085, 0.94, "Full-range spectra", fontsize=19, fontweight="bold", color="#172033")
    fig.text(
        0.085,
        0.895,
        "Fixed parameters: 3500 K host · 2.5 R⊕ · 10.183 M⊕ · 1.5 S⊕ · C/O = 1× solar · Kzz = 10⁹ cm² s⁻¹ · phase = 0° · R = 1500",
        fontsize=10,
        color="#667085",
    )
    fig.text(
        0.085,
        0.855,
        "Geometric albedo (top) and total planet/star contrast, reflected + thermal (bottom); clouds and metallicity vary.",
        fontsize=10,
        color="#667085",
    )
    fig.text(
        0.085,
        0.055,
        "Each NetCDF contains geometric albedo, reflected contrast, thermal contrast, and total planet/star contrast.",
        fontsize=8.8,
        color="#667085",
    )
    fig.text(0.085, 0.025, "Sources: Aurora climate cache groups 23611, 23691, and 24811.", fontsize=8.2, color="#667085")

    fig.savefig(OUT_DIR / "representative_spectra.png", dpi=180, facecolor="white")
    fig.savefig(OUT_DIR / "representative_spectra.svg", facecolor="white")
    plt.close(fig)


def write_manifest(results: list[dict[str, Any]]) -> None:
    fieldnames = list(results[0])
    with (OUT_DIR / "selected_cases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    (OUT_DIR / "selected_cases.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def write_summary(results: list[dict[str, Any]]) -> None:
    lines = [
        "# Representative reflected-light spectra",
        "",
        "Three reflected-plus-thermal spectra were constructed from existing converged NPZ/PKL climate-cache pairs for a controlled comparison at fixed bulk and orbital parameters.",
        "",
        "Fixed parameters:",
        "",
        "- Host: 3500 K, 0.45 R_sun",
        "- Planet: 2.5 R_earth, 10.183 M_earth",
        "- Insolation: 1.5 S_earth",
        "- C/O: 1x solar",
        "- Kzz: 1e9 cm2/s",
        "- Phase: 0 degrees",
        "- Full configured wavelength grid: 0.30-15 microns at R = 1500",
        "",
        "Selected cases:",
        "",
    ]
    for result in results:
        lines.append(
            f"- **{result['label']}** — climate group {result['climate_group_index']}; {result['rationale']}"
        )
    lines.extend(
        [
            "",
            "All three NetCDF files passed the Aurora schema checks and contained finite, nonzero reflected spectra.",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "netcdf").mkdir(parents=True, exist_ok=True)
    config = load_config()
    results = []
    for case in CASES:
        print(f"building {case['case_id']} from climate group {case['climate_group_index']}", flush=True)
        result = build_case(config, case)
        results.append(result)
        print(f"wrote {result['output_nc']}", flush=True)
    write_manifest(results)
    write_summary(results)
    render_plot(results)
    print(json.dumps(results, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
