from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .naming import cto_to_picaso_tag, make_output_path, make_run_id
from .parameters import (
    MANIFEST_COLUMNS,
    ManifestTable,
    _metadata_columns,
    cloud_model_for_fraction,
    equilibrium_temperature_k,
    insolation_to_semi_major_au,
    picaso_tint_k,
    stellar_luminosity_lsun,
    validate_manifest,
)

COUPLED_EXTRA_COLUMNS = ("planet_class_id", "separation_id")

PLANET_CLASS_SCALAR_KEYS = (
    "planet_radius_rearth",
    "gravity_ms2",
    "kzz_cm2_s",
    "picaso_tint_mode",
    "picaso_tint_k",
    "picaso_tint_fixed_k",
    "picaso_tint_floor_k",
)

PLANET_CLASS_LIST_KEYS = ("metallicity_xsolar", "c_to_o_xsolar")

SEPARATION_SCALAR_KEYS = (
    "semi_major_au",
    "insolation_searth",
    "cloud_fraction",
    "cloud_model",
    "fsed",
)


def load_coupled_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Config {path} did not parse to a mapping.")
    validate_coupled_config(config)
    return config


def load_grid_config(path: str | Path) -> dict[str, Any]:
    """Load YAML for either cartesian or coupled factorized grids."""
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Config {path} did not parse to a mapping.")
    factorization = config.get("factorization") or {}
    if isinstance(factorization, dict) and str(factorization.get("grid_expansion", "")).strip().lower() == "coupled_cases":
        validate_coupled_config(config)
    return config


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _resolve_star(config: dict[str, Any]) -> dict[str, float]:
    if "star" in config and isinstance(config["star"], dict):
        star = config["star"]
        return {
            "teff_k": float(star["teff_k"]),
            "radius_rsun": float(star["radius_rsun"]),
        }
    stars = config.get("stars")
    if isinstance(stars, list) and stars:
        star = stars[0]
        if isinstance(star, dict):
            return {
                "teff_k": float(star["teff_k"]),
                "radius_rsun": float(star["radius_rsun"]),
            }
    raise ValueError("Coupled config requires 'star' mapping or non-empty 'stars' list.")


def validate_coupled_config(config: dict[str, Any]) -> None:
    missing = [key for key in ("model_name", "output_root", "planet_classes", "separations", "phase_deg") if key not in config]
    if missing:
        raise ValueError(f"Coupled config missing required keys: {missing}")
    if not isinstance(config["planet_classes"], list) or not config["planet_classes"]:
        raise ValueError("Coupled config requires non-empty 'planet_classes' list.")
    if not isinstance(config["separations"], list) or not config["separations"]:
        raise ValueError("Coupled config requires non-empty 'separations' list.")
    if not isinstance(config["phase_deg"], list) or not config["phase_deg"]:
        raise ValueError("Coupled config requires non-empty 'phase_deg' list.")
    _resolve_star(config)
    for planet_class in config["planet_classes"]:
        if not isinstance(planet_class, dict):
            raise ValueError("Each planet_class entry must be a mapping.")
        if "id" not in planet_class:
            raise ValueError("Each planet_class requires an 'id'.")
        for key in ("planet_radius_rearth", "gravity_ms2", "metallicity_xsolar"):
            if key not in planet_class:
                raise ValueError(f"planet_class {planet_class.get('id')!r} missing {key!r}.")
    for separation in config["separations"]:
        if not isinstance(separation, dict):
            raise ValueError("Each separation entry must be a mapping.")
        if "id" not in separation:
            raise ValueError("Each separation requires an 'id'.")
        if "semi_major_au" not in separation and "insolation_searth" not in separation:
            raise ValueError(f"separation {separation.get('id')!r} requires semi_major_au or insolation_searth.")


def _planet_class_products(planet_class: dict[str, Any]) -> list[dict[str, Any]]:
    combos: list[dict[str, Any]] = [{}]
    for key in PLANET_CLASS_LIST_KEYS:
        if key not in planet_class:
            if key == "metallicity_xsolar":
                raise ValueError(f"planet_class {planet_class.get('id')!r} missing metallicity_xsolar.")
            continue
        values = _as_list(planet_class[key])
        combos = [
            {**combo, key: value}
            for combo in combos
            for value in values
        ]
    return combos


def _separation_products(separation: dict[str, Any]) -> list[dict[str, Any]]:
    return [separation]


def _tint_k_for_row(config: dict[str, Any], planet_class: dict[str, Any], teq_k: float) -> float:
    row_config = {
        "picaso_tint_mode": planet_class.get("picaso_tint_mode", config.get("picaso_tint_mode", "equilibrium")),
        "picaso_tint_fixed_k": planet_class.get(
            "picaso_tint_fixed_k",
            planet_class.get("picaso_tint_k", config.get("picaso_tint_fixed_k", 1000.0)),
        ),
        "picaso_tint_floor_k": planet_class.get("picaso_tint_floor_k", config.get("picaso_tint_floor_k", 100.0)),
    }
    mode = str(row_config["picaso_tint_mode"]).strip().lower()
    if mode == "fixed":
        if "picaso_tint_k" in planet_class:
            return float(planet_class["picaso_tint_k"])
        return float(row_config["picaso_tint_fixed_k"])
    return picaso_tint_k(row_config, teq_k)


def _orbit_from_separation(
    separation: dict[str, Any],
    star_teff_k: float,
    star_radius_rsun: float,
    luminosity_lsun: float,
) -> tuple[float, float]:
    if "semi_major_au" in separation:
        semi_major_au = float(separation["semi_major_au"])
        insolation = luminosity_lsun / semi_major_au**2
        return semi_major_au, insolation
    insolation_searth = float(separation["insolation_searth"])
    semi_major_au = insolation_to_semi_major_au(luminosity_lsun, insolation_searth)
    return semi_major_au, insolation_searth


def _cloud_model_for_separation(separation: dict[str, Any]) -> str:
    if "cloud_model" in separation:
        return str(separation["cloud_model"])
    if "cloud_fraction" in separation:
        return cloud_model_for_fraction(float(separation["cloud_fraction"]))
    return "none"


def expand_coupled_climates(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand coupled planet-class × separation combinations (no phase axis)."""
    validate_coupled_config(config)
    star = _resolve_star(config)
    star_teff_k = star["teff_k"]
    star_radius_rsun = star["radius_rsun"]
    luminosity_lsun = stellar_luminosity_lsun(star_teff_k, star_radius_rsun)
    metadata = _metadata_columns(config)
    rows: list[dict[str, Any]] = []

    for planet_class in config["planet_classes"]:
        planet_class_id = str(planet_class["id"])
        class_products = _planet_class_products(planet_class)
        for separation in config["separations"]:
            separation_id = str(separation["id"])
            for class_combo in class_products:
                semi_major_au, insolation_searth = _orbit_from_separation(
                    separation,
                    star_teff_k,
                    star_radius_rsun,
                    luminosity_lsun,
                )
                teq_k = equilibrium_temperature_k(star_teff_k, star_radius_rsun, semi_major_au)
                metallicity_xsolar = float(class_combo.get("metallicity_xsolar", planet_class["metallicity_xsolar"]))
                c_to_o_xsolar = float(
                    class_combo.get(
                        "c_to_o_xsolar",
                        planet_class.get("c_to_o_xsolar", 1.0),
                    )
                )
                kzz_cm2_s = float(planet_class.get("kzz_cm2_s", config.get("kzz_cm2_s", 1.0e9)))
                cloud_fraction = float(separation.get("cloud_fraction", 0.0))
                fsed = float(separation.get("fsed", config.get("fsed", 3.0)))
                cloud_model = _cloud_model_for_separation(separation)
                tint_mode = str(
                    planet_class.get("picaso_tint_mode", config.get("picaso_tint_mode", "equilibrium"))
                )
                row: dict[str, Any] = {
                    "model_name": config["model_name"],
                    **metadata,
                    "planet_class_id": planet_class_id,
                    "separation_id": separation_id,
                    "star_teff_k": star_teff_k,
                    "star_radius_rsun": star_radius_rsun,
                    "stellar_luminosity_lsun": luminosity_lsun,
                    "planet_radius_rearth": float(planet_class["planet_radius_rearth"]),
                    "gravity_ms2": float(planet_class["gravity_ms2"]),
                    "metallicity_xsolar": metallicity_xsolar,
                    "c_to_o_xsolar": c_to_o_xsolar,
                    "c_to_o_picaso_tag": cto_to_picaso_tag(c_to_o_xsolar),
                    "kzz_cm2_s": kzz_cm2_s,
                    "logkzz": float(np.log10(kzz_cm2_s)),
                    "cloud_fraction": cloud_fraction,
                    "cloud_model": cloud_model,
                    "fsed": fsed,
                    "insolation_searth": insolation_searth,
                    "semi_major_au": semi_major_au,
                    "equilibrium_temperature_k": teq_k,
                    "picaso_tint_k": _tint_k_for_row(config, planet_class, teq_k),
                    "picaso_tint_mode": tint_mode,
                    "picaso_tint_fixed_k": float(
                        planet_class.get("picaso_tint_fixed_k", planet_class.get("picaso_tint_k", config.get("picaso_tint_fixed_k", 1000.0)))
                    ),
                    "picaso_tint_floor_k": float(planet_class.get("picaso_tint_floor_k", config.get("picaso_tint_floor_k", 100.0))),
                    "status": "pending",
                }
                rows.append(row)
    return rows


def expand_coupled_full_manifest(config: dict[str, Any]) -> ManifestTable:
    """Expand coupled climates × phase_deg into a full manifest table."""
    climate_rows = expand_coupled_climates(config)
    output_root = config["output_root"]
    full_rows: list[dict[str, Any]] = []
    run_index = 0
    for climate_row in climate_rows:
        for phase_deg in config["phase_deg"]:
            row = dict(climate_row)
            row["phase_deg"] = float(phase_deg)
            row["run_index"] = run_index
            row["run_id"] = make_run_id(row)
            row["output_nc"] = make_output_path(row, output_root)
            full_rows.append(row)
            run_index += 1
    table = ManifestTable(full_rows)
    expected = len(climate_rows) * len(config["phase_deg"])
    validate_manifest(table, expected_rows=expected)
    return table


def expand_grid_manifest(config: dict[str, Any]) -> ManifestTable:
    """Dispatch manifest expansion based on factorization.grid_expansion."""
    factorization = config.get("factorization") or {}
    mode = "cartesian"
    if isinstance(factorization, dict):
        mode = str(factorization.get("grid_expansion", "cartesian")).strip().lower()
    if mode == "coupled_cases":
        return expand_coupled_full_manifest(config)
    from .parameters import create_manifest_dataframe

    return create_manifest_dataframe(config)


def coupled_manifest_columns() -> list[str]:
    columns = list(MANIFEST_COLUMNS)
    for column in COUPLED_EXTRA_COLUMNS:
        if column not in columns:
            insert_at = columns.index("model_name") + 1
            columns.insert(insert_at, column)
    return columns
