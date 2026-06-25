#!/usr/bin/env python
"""Build the 304-row Cahoy et al. 2010 replication manifest."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import yaml


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.naming import cto_to_picaso_tag, make_output_path, make_run_id
from aurora_grid.parameters import (
    NOTEBOOK_REFERENCE,
    ManifestTable,
    cloud_model_for_fraction,
    validate_manifest,
)
from aurora_grid.climate_groups import assign_climate_group_indices, count_climate_groups

# Cahoy Table 1: Jupiter g=25 m/s² Tint=100 K; Neptune g=10 m/s² Tint=50 K.
# Radii: ~1 R_Jup and Neptune analog (~3.865 R_earth) per Cahoy gas/ice giants.
JUPITER_RADIUS_REARTH = 11.209
NEPTUNE_RADIUS_REARTH = 3.865

CAHOY_PLANETS = (
    {
        "cahoy_type": "Jupiter",
        "cahoy_met_label": "1x",
        "gravity_ms2": 25.0,
        "metallicity_xsolar": 1.0,
        "planet_radius_rearth": JUPITER_RADIUS_REARTH,
        "picaso_tint_k": 100.0,
    },
    {
        "cahoy_type": "Jupiter",
        "cahoy_met_label": "3x",
        "gravity_ms2": 25.0,
        "metallicity_xsolar": 3.0,
        "planet_radius_rearth": JUPITER_RADIUS_REARTH,
        "picaso_tint_k": 100.0,
    },
    {
        "cahoy_type": "Neptune",
        "cahoy_met_label": "10x",
        "gravity_ms2": 10.0,
        "metallicity_xsolar": 10.0,
        "planet_radius_rearth": NEPTUNE_RADIUS_REARTH,
        "picaso_tint_k": 50.0,
    },
    {
        "cahoy_type": "Neptune",
        "cahoy_met_label": "30x",
        "gravity_ms2": 10.0,
        "metallicity_xsolar": 30.0,
        "planet_radius_rearth": NEPTUNE_RADIUS_REARTH,
        "picaso_tint_k": 50.0,
    },
)

# Cloud prescription from Cahoy Table 1 (separation-dependent, not a clear/cloudy sweep).
CAHOY_SEPARATIONS = (
    {
        "semi_major_au": 0.8,
        "insolation_searth": 1.5625,
        "cloud_fraction": 0.0,
        "fsed": 6.0,
        "virga_condensates": "",
        "cahoy_cloud_note": "cloud-free",
    },
    {
        "semi_major_au": 2.0,
        "insolation_searth": 0.25,
        "cloud_fraction": 1.0,
        "fsed": 6.0,
        "virga_condensates": "H2O",
        "cahoy_cloud_note": "H2O clouds",
    },
    {
        "semi_major_au": 5.0,
        "insolation_searth": 0.04,
        "cloud_fraction": 1.0,
        "fsed": 10.0,
        "virga_condensates": "H2O,NH3",
        "cahoy_cloud_note": "H2O+NH3 clouds",
    },
    {
        "semi_major_au": 10.0,
        "insolation_searth": 0.01,
        "cloud_fraction": 1.0,
        "fsed": 10.0,
        "virga_condensates": "H2O,NH3",
        "cahoy_cloud_note": "H2O+NH3 clouds",
    },
)

PHASES_DEG = tuple(range(0, 181, 10))
STAR_TEFF_K = 5772.0
STAR_RADIUS_RSUN = 1.0
STELLAR_LUMINOSITY_LSUN = 1.0
C_TO_O_XSOLAR = 1.0
KZZ_CM2_S = 1.0e9


def _cahoy_reference_name(planet: dict, separation_au: float, phase_deg: float) -> str:
    au_label = f"{separation_au:g}AU"
    return f"{planet['cahoy_type']}_{planet['cahoy_met_label']}_{au_label}_{int(phase_deg)}deg.dat"


def _equilibrium_temperature_k(semi_major_au: float) -> float:
    albedo_factor = 1.0
    return STAR_TEFF_K * math.sqrt(STAR_RADIUS_RSUN * 0.004650467260962157 / (2.0 * semi_major_au)) * albedo_factor


def build_cahoy2010_manifest(config: dict) -> ManifestTable:
    netcdf_config = config.get("netcdf") or {}
    metadata = {
        "author": config.get("author", ""),
        "contact": config.get("contact", ""),
        "project": config.get("project", ""),
        "notes": config.get("notes", ""),
        "code": json.dumps(config.get("code", {}), sort_keys=True),
        "picaso_tint_mode": str(config.get("picaso_tint_mode", "fixed")),
        "picaso_tint_fixed_k": float(config.get("picaso_tint_fixed_k", 100.0)),
        "picaso_tint_floor_k": float(config.get("picaso_tint_floor_k", 50.0)),
        "netcdf_optional_variables": json.dumps(netcdf_config.get("optional_variables", []), sort_keys=True),
        "netcdf_strict_optional": bool(netcdf_config.get("strict_optional", False)),
        "source_notebook_reference": NOTEBOOK_REFERENCE,
    }
    output_root = config["output_root"]
    rows: list[dict] = []
    run_index = 0

    for planet in CAHOY_PLANETS:
        for sep in CAHOY_SEPARATIONS:
            teq_k = _equilibrium_temperature_k(sep["semi_major_au"])
            for phase_deg in PHASES_DEG:
                cloud_fraction = float(sep["cloud_fraction"])
                row = {
                    "run_index": run_index,
                    "model_name": config["model_name"],
                    "star_teff_k": STAR_TEFF_K,
                    "star_radius_rsun": STAR_RADIUS_RSUN,
                    "stellar_luminosity_lsun": STELLAR_LUMINOSITY_LSUN,
                    "planet_radius_rearth": float(planet["planet_radius_rearth"]),
                    "gravity_ms2": float(planet["gravity_ms2"]),
                    "metallicity_xsolar": float(planet["metallicity_xsolar"]),
                    "c_to_o_xsolar": C_TO_O_XSOLAR,
                    "c_to_o_picaso_tag": cto_to_picaso_tag(C_TO_O_XSOLAR),
                    "kzz_cm2_s": KZZ_CM2_S,
                    "logkzz": 9.0,
                    "cloud_fraction": cloud_fraction,
                    "cloud_model": cloud_model_for_fraction(cloud_fraction),
                    "fsed": float(sep["fsed"]),
                    "insolation_searth": float(sep["insolation_searth"]),
                    "phase_deg": float(phase_deg),
                    "semi_major_au": float(sep["semi_major_au"]),
                    "equilibrium_temperature_k": teq_k,
                    "picaso_tint_k": float(planet["picaso_tint_k"]),
                    "cahoy_reference_name": _cahoy_reference_name(planet, sep["semi_major_au"], phase_deg),
                    "cahoy_planet_type": planet["cahoy_type"],
                    "cahoy_metallicity_label": planet["cahoy_met_label"],
                    "cahoy_cloud_note": sep["cahoy_cloud_note"],
                    "virga_condensates": sep["virga_condensates"],
                    **metadata,
                    "status": "pending",
                }
                row["run_id"] = make_run_id(row)
                row["output_nc"] = make_output_path(row, output_root)
                rows.append(row)
                run_index += 1

    assign_climate_group_indices(rows)
    table = ManifestTable(rows)
    validate_manifest(table, expected_rows=304)
    return table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Cahoy et al. 2010 replication manifest (304 rows).")
    parser.add_argument(
        "--config",
        default=str(GRID_ROOT / "params" / "aurora_cahoy2010_replication_v0.yaml"),
        help="YAML config with model_name and output_root.",
    )
    parser.add_argument(
        "--out",
        default=str(GRID_ROOT / "manifests" / "aurora_cahoy2010_replication_v0_manifest.csv"),
        help="Output manifest CSV path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with Path(args.config).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    manifest = build_cahoy2010_manifest(config)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(output_path, index=False)

    print(f"model_name: {config['model_name']}")
    print(f"total_rows: {len(manifest)}")
    print(f"climate_groups: {count_climate_groups(manifest.rows)}")
    print(f"output_root: {config['output_root']}")
    print(f"manifest: {output_path}")
    print(f"example_cahoy_reference: {manifest.rows[0]['cahoy_reference_name']}")
    print(f"example_output_nc: {manifest.rows[0]['output_nc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
