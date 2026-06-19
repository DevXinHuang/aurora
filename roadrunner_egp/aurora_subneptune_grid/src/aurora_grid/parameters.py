from __future__ import annotations

import itertools
import json
import math
import csv
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .naming import cto_to_picaso_tag, make_output_path, make_run_id


T_SUN_K = 5772.0
R_SUN_AU = 0.004650467260962157
NOTEBOOK_REFERENCE = "roadrunner_egp/notebooks/path_a_full_picaso_first_order_simulation.ipynb"

GRID_ROOT = Path(__file__).resolve().parents[2]
ROADRUNNER_ROOT = GRID_ROOT.parent
REPO_ROOT = ROADRUNNER_ROOT.parent

PARAMETER_KEYS = [
    "stars",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "phase_deg",
]

MANIFEST_COLUMNS = [
    "run_index",
    "model_name",
    "run_id",
    "star_teff_k",
    "star_radius_rsun",
    "stellar_luminosity_lsun",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "c_to_o_picaso_tag",
    "kzz_cm2_s",
    "logkzz",
    "cloud_fraction",
    "cloud_model",
    "fsed",
    "insolation_searth",
    "phase_deg",
    "semi_major_au",
    "equilibrium_temperature_k",
    "picaso_tint_k",
    "output_nc",
    "status",
    "author",
    "contact",
    "project",
    "notes",
    "code",
    "picaso_tint_mode",
    "picaso_tint_fixed_k",
    "picaso_tint_floor_k",
    "netcdf_optional_variables",
    "netcdf_strict_optional",
    "source_notebook_reference",
]

FLOAT_COLUMNS = {
    "star_teff_k",
    "star_radius_rsun",
    "stellar_luminosity_lsun",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "logkzz",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "phase_deg",
    "semi_major_au",
    "equilibrium_temperature_k",
    "picaso_tint_k",
    "picaso_tint_fixed_k",
    "picaso_tint_floor_k",
}

INT_COLUMNS = {"run_index"}
BOOL_COLUMNS = {"netcdf_strict_optional"}


class ManifestTable:
    """Small manifest table wrapper that avoids runtime dependence on pandas."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def column_values(self, column: str) -> list[Any]:
        return [row.get(column) for row in self.rows]

    def has_duplicate(self, column: str) -> bool:
        seen = set()
        for value in self.column_values(column):
            if value in seen:
                return True
            seen.add(value)
        return False

    def duplicate_values(self, column: str, limit: int = 5) -> list[Any]:
        seen = set()
        duplicates = []
        for value in self.column_values(column):
            if value in seen and value not in duplicates:
                duplicates.append(value)
                if len(duplicates) >= limit:
                    break
            seen.add(value)
        return duplicates

    def head(self, n: int = 5) -> "ManifestTable":
        return ManifestTable(self.rows[:n])

    def to_csv(self, path: str | Path, index: bool = False) -> None:
        del index
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows)

    def to_string(self, index: bool = False) -> str:
        del index
        if not self.rows:
            return "<empty manifest>"
        columns = [column for column in MANIFEST_COLUMNS if column in self.rows[0]]
        preview_rows = self.rows
        widths = {
            column: max(
                len(column),
                *(len(_display_value(row.get(column))) for row in preview_rows),
            )
            for column in columns
        }
        header = " ".join(column.ljust(widths[column]) for column in columns)
        lines = [header]
        for row in preview_rows:
            lines.append(" ".join(_display_value(row.get(column)).ljust(widths[column]) for column in columns))
        return "\n".join(lines)


def _display_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.12g}"
    return "" if value is None else str(value)


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Config {path} did not parse to a mapping.")
    missing = [key for key in PARAMETER_KEYS + ["model_name", "output_root"] if key not in config]
    if missing:
        raise ValueError(f"Config {path} is missing required keys: {missing}")
    return config


def stellar_luminosity_lsun(teff_k: float, radius_rsun: float) -> float:
    return float(radius_rsun) ** 2 * (float(teff_k) / T_SUN_K) ** 4


def insolation_to_semi_major_au(luminosity_lsun: float, insolation_searth: float) -> float:
    if float(insolation_searth) <= 0:
        raise ValueError("Insolation must be positive.")
    return math.sqrt(float(luminosity_lsun) / float(insolation_searth))


def equilibrium_temperature_k(
    star_teff_k: float,
    star_radius_rsun: float,
    semi_major_au: float,
    bond_albedo: float = 0.0,
) -> float:
    if semi_major_au <= 0:
        raise ValueError("Semi-major axis must be positive.")
    albedo_factor = max(0.0, 1.0 - float(bond_albedo)) ** 0.25
    return (
        float(star_teff_k)
        * math.sqrt((float(star_radius_rsun) * R_SUN_AU) / (2.0 * float(semi_major_au)))
        * albedo_factor
    )


def picaso_tint_k(config: dict[str, Any], equilibrium_k: float) -> float:
    mode = str(config.get("picaso_tint_mode", "equilibrium")).strip().lower()
    fixed_k = float(config.get("picaso_tint_fixed_k", 1000.0))
    floor_k = float(config.get("picaso_tint_floor_k", 100.0))
    if mode == "fixed":
        return fixed_k
    if mode == "equilibrium":
        return float(equilibrium_k)
    if mode == "equilibrium_floor":
        return max(floor_k, float(equilibrium_k))
    raise ValueError(
        f"Unsupported picaso_tint_mode {mode!r}; "
        "choose 'fixed', 'equilibrium', or 'equilibrium_floor'."
    )


def cloud_model_for_fraction(cloud_fraction: float) -> str:
    value = float(cloud_fraction)
    if value < 0.0 or value > 1.0:
        raise ValueError(f"cloud_fraction must be between 0 and 1; got {cloud_fraction!r}.")
    if math.isclose(value, 0.0, abs_tol=1e-12):
        return "none"
    # Any nonzero value is a cloudy PICASO/Virga column.
    # Values between 0 and 1 are handled natively by PICASO patchy-cloud holes:
    # fhole = 1 - cloud_fraction.
    return "virga"


def expected_grid_size(config: dict[str, Any]) -> int:
    total = len(config["stars"])
    for key in PARAMETER_KEYS:
        if key == "stars":
            continue
        total *= len(config[key])
    return int(total)


def _metadata_columns(config: dict[str, Any]) -> dict[str, Any]:
    netcdf_config = config.get("netcdf", {})
    if netcdf_config is None:
        netcdf_config = {}
    if not isinstance(netcdf_config, dict):
        raise ValueError("Config key 'netcdf' must be a mapping when provided.")
    return {
        "author": config.get("author", ""),
        "contact": config.get("contact", ""),
        "project": config.get("project", ""),
        "notes": config.get("notes", ""),
        "code": json.dumps(config.get("code", {}), sort_keys=True),
        "picaso_tint_mode": config.get("picaso_tint_mode", "equilibrium"),
        "picaso_tint_fixed_k": float(config.get("picaso_tint_fixed_k", 1000.0)),
        "picaso_tint_floor_k": float(config.get("picaso_tint_floor_k", 100.0)),
        "netcdf_optional_variables": json.dumps(netcdf_config.get("optional_variables", []), sort_keys=True),
        "netcdf_strict_optional": bool(netcdf_config.get("strict_optional", False)),
        "source_notebook_reference": NOTEBOOK_REFERENCE,
    }


def create_manifest_dataframe(config: dict[str, Any]) -> ManifestTable:
    rows: list[dict[str, Any]] = []
    metadata = _metadata_columns(config)
    output_root = config["output_root"]
    run_index = 0

    products = itertools.product(
        config["stars"],
        config["planet_radius_rearth"],
        config["gravity_ms2"],
        config["metallicity_xsolar"],
        config["c_to_o_xsolar"],
        config["kzz_cm2_s"],
        config["cloud_fraction"],
        config["fsed"],
        config["insolation_searth"],
        config["phase_deg"],
    )
    for (
        star,
        planet_radius_rearth,
        gravity_ms2,
        metallicity_xsolar,
        c_to_o_xsolar,
        kzz_cm2_s,
        cloud_fraction,
        fsed,
        insolation_searth,
        phase_deg,
    ) in products:
        star_teff_k = float(star["teff_k"])
        star_radius_rsun = float(star["radius_rsun"])
        luminosity_lsun = stellar_luminosity_lsun(star_teff_k, star_radius_rsun)
        semi_major_au = insolation_to_semi_major_au(luminosity_lsun, insolation_searth)
        teq_k = equilibrium_temperature_k(star_teff_k, star_radius_rsun, semi_major_au)
        row: dict[str, Any] = {
            "run_index": run_index,
            "model_name": config["model_name"],
            "star_teff_k": star_teff_k,
            "star_radius_rsun": star_radius_rsun,
            "stellar_luminosity_lsun": luminosity_lsun,
            "planet_radius_rearth": float(planet_radius_rearth),
            "gravity_ms2": float(gravity_ms2),
            "metallicity_xsolar": float(metallicity_xsolar),
            "c_to_o_xsolar": float(c_to_o_xsolar),
            "c_to_o_picaso_tag": cto_to_picaso_tag(float(c_to_o_xsolar)),
            "kzz_cm2_s": float(kzz_cm2_s),
            "logkzz": float(np.log10(float(kzz_cm2_s))),
            "cloud_fraction": float(cloud_fraction),
            "cloud_model": cloud_model_for_fraction(float(cloud_fraction)),
            "fsed": float(fsed),
            "insolation_searth": float(insolation_searth),
            "phase_deg": float(phase_deg),
            "semi_major_au": semi_major_au,
            "equilibrium_temperature_k": teq_k,
            "picaso_tint_k": picaso_tint_k(config, teq_k),
            **metadata,
            "status": "pending",
        }
        row["run_id"] = make_run_id(row)
        row["output_nc"] = make_output_path(row, output_root)
        rows.append(row)
        run_index += 1

    table = ManifestTable(rows)
    validate_manifest(table, expected_rows=expected_grid_size(config))
    return table


def validate_manifest(dataframe: ManifestTable, expected_rows: int | None = None) -> None:
    if expected_rows is not None and len(dataframe) != int(expected_rows):
        raise ValueError(f"Manifest has {len(dataframe)} rows; expected {expected_rows}.")
    if dataframe.has_duplicate("run_id"):
        raise ValueError(f"Duplicate run_id values found: {dataframe.duplicate_values('run_id')}")
    if dataframe.has_duplicate("output_nc"):
        raise ValueError(f"Duplicate output paths found: {dataframe.duplicate_values('output_nc')}")


def _coerce_manifest_row(row: dict[str, str]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key, value in row.items():
        if key in INT_COLUMNS:
            coerced[key] = int(value)
        elif key in BOOL_COLUMNS:
            coerced[key] = str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}
        elif key in FLOAT_COLUMNS:
            coerced[key] = float(value)
        else:
            coerced[key] = value
    return coerced


def read_manifest_csv(path: str | Path) -> ManifestTable:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [_coerce_manifest_row(row) for row in reader]
    table = ManifestTable(rows)
    validate_manifest(table)
    return table


def resolve_repo_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return REPO_ROOT / path
