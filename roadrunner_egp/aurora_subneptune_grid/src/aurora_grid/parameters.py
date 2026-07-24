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
G_SI = 6.67430e-11
M_EARTH_KG = 5.9722e24
R_EARTH_M = 6.371e6
NOTEBOOK_REFERENCE = "roadrunner_egp/notebooks/path_a_full_picaso_first_order_simulation.ipynb"
DEFAULT_WAVELENGTH_GRID_MODE = "constant_resolution"
DEFAULT_WAVELENGTH_MIN_UM = 0.3
DEFAULT_WAVELENGTH_MAX_UM = 2.5
DEFAULT_WAVELENGTH_RESOLUTION = 15000.0
DEFAULT_WAVELENGTH_POINTS = 2201

GRID_ROOT = Path(__file__).resolve().parents[2]
ROADRUNNER_ROOT = GRID_ROOT.parent
REPO_ROOT = ROADRUNNER_ROOT.parent

BASE_PARAMETER_KEYS = [
    "stars",
    "planet_radius_rearth",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "phase_deg",
]
GRAVITY_AXIS_KEY = "gravity_ms2"
MASS_AXIS_KEY = "planet_mass_mearth"
DEFAULT_CLIMATE_SPECTRUM_AXES = ("phase_deg",)
SUPPORTED_CLIMATE_SPECTRUM_AXES = frozenset({"planet_radius_rearth", "phase_deg"})

MANIFEST_COLUMNS = [
    "run_index",
    "model_name",
    "run_id",
    "climate_group_index",
    "climate_group_key",
    "star_teff_k",
    "star_radius_rsun",
    "stellar_luminosity_lsun",
    "planet_radius_rearth",
    "climate_reference_radius_rearth",
    "planet_mass_mearth",
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
    "cahoy_reference_name",
    "virga_condensates",
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
    "wavelength_grid_mode",
    "wavelength_min_um",
    "wavelength_max_um",
    "wavelength_resolution",
    "wavelength_points",
    "source_notebook_reference",
]

FLOAT_COLUMNS = {
    "star_teff_k",
    "star_radius_rsun",
    "stellar_luminosity_lsun",
    "planet_radius_rearth",
    "climate_reference_radius_rearth",
    "planet_mass_mearth",
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
    "wavelength_min_um",
    "wavelength_max_um",
    "wavelength_resolution",
}

INT_COLUMNS = {"run_index", "climate_group_index", "wavelength_points"}
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
    missing = [key for key in BASE_PARAMETER_KEYS + ["model_name", "output_root"] if key not in config]
    if missing:
        raise ValueError(f"Config {path} is missing required keys: {missing}")
    has_gravity_axis = GRAVITY_AXIS_KEY in config
    has_mass_axis = MASS_AXIS_KEY in config
    if has_gravity_axis and has_mass_axis:
        raise ValueError(
            f"Config {path} provides both {GRAVITY_AXIS_KEY!r} and {MASS_AXIS_KEY!r}; "
            "choose exactly one primary planet axis."
        )
    if not has_gravity_axis and not has_mass_axis:
        raise ValueError(
            f"Config {path} must provide one of {GRAVITY_AXIS_KEY!r} or {MASS_AXIS_KEY!r}."
        )
    axes = climate_spectrum_axes(config)
    if "planet_radius_rearth" in axes:
        if not has_gravity_axis:
            raise ValueError(
                "planet_radius_rearth can be spectrum-only only when gravity_ms2 "
                "is the primary planet axis."
            )
        reference_radius = float(config.get("climate_reference_radius_rearth", 0.0))
        if reference_radius <= 0.0:
            raise ValueError(
                "A positive climate_reference_radius_rearth is required when "
                "planet_radius_rearth is spectrum-only."
            )
    unsupported_chemistry_pairs(config)
    return config


def climate_spectrum_axes(config: dict[str, Any]) -> tuple[str, ...]:
    raw_axes = config.get("climate_spectrum_axes", DEFAULT_CLIMATE_SPECTRUM_AXES)
    if not isinstance(raw_axes, (list, tuple)) or not raw_axes:
        raise ValueError("climate_spectrum_axes must be a non-empty list when provided.")
    axes = tuple(str(value) for value in raw_axes)
    unknown = sorted(set(axes) - SUPPORTED_CLIMATE_SPECTRUM_AXES)
    if unknown:
        raise ValueError(f"Unsupported climate_spectrum_axes values: {unknown}")
    if "phase_deg" not in axes:
        raise ValueError("climate_spectrum_axes must include 'phase_deg'.")
    if len(set(axes)) != len(axes):
        raise ValueError("climate_spectrum_axes cannot contain duplicates.")
    return axes


def unsupported_chemistry_pairs(config: dict[str, Any]) -> frozenset[tuple[float, float]]:
    raw_pairs = config.get("unsupported_chemistry_pairs", [])
    if raw_pairs in (None, []):
        return frozenset()
    if not isinstance(raw_pairs, list):
        raise ValueError("unsupported_chemistry_pairs must be a list.")
    metallicities = {float(value) for value in config.get("metallicity_xsolar", [])}
    c_to_o_values = {float(value) for value in config.get("c_to_o_xsolar", [])}
    pairs: set[tuple[float, float]] = set()
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, dict):
            raise ValueError("Each unsupported chemistry pair must be a mapping.")
        pair = (
            float(raw_pair["metallicity_xsolar"]),
            float(raw_pair["c_to_o_xsolar"]),
        )
        if pair[0] not in metallicities or pair[1] not in c_to_o_values:
            raise ValueError(
                "Unsupported chemistry pair is outside the configured axes: "
                f"metallicity_xsolar={pair[0]}, c_to_o_xsolar={pair[1]}"
            )
        pairs.add(pair)
    if len(pairs) >= len(metallicities) * len(c_to_o_values):
        raise ValueError("unsupported_chemistry_pairs excludes the entire chemistry grid.")
    return frozenset(pairs)


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


def _planet_axis_key(config: dict[str, Any]) -> str:
    return MASS_AXIS_KEY if MASS_AXIS_KEY in config else GRAVITY_AXIS_KEY


def gravity_from_mass_radius_ms2(planet_mass_mearth: float, planet_radius_rearth: float) -> float:
    mass_kg = float(planet_mass_mearth) * M_EARTH_KG
    radius_m = float(planet_radius_rearth) * R_EARTH_M
    if radius_m <= 0.0:
        raise ValueError("Planet radius must be positive.")
    return (G_SI * mass_kg) / (radius_m**2)


def mass_from_gravity_radius_mearth(gravity_ms2: float, planet_radius_rearth: float) -> float:
    gravity_si = float(gravity_ms2)
    radius_m = float(planet_radius_rearth) * R_EARTH_M
    if gravity_si <= 0.0:
        raise ValueError("Gravity must be positive.")
    if radius_m <= 0.0:
        raise ValueError("Planet radius must be positive.")
    mass_kg = gravity_si * (radius_m**2) / G_SI
    return mass_kg / M_EARTH_KG


def unfiltered_grid_size(config: dict[str, Any]) -> int:
    total = 1
    for key in BASE_PARAMETER_KEYS:
        total *= len(config[key])
    total *= len(config[_planet_axis_key(config)])
    return int(total)


def expected_grid_size(config: dict[str, Any]) -> int:
    total = unfiltered_grid_size(config)
    excluded_pairs = unsupported_chemistry_pairs(config)
    if not excluded_pairs:
        return total
    chemistry_pair_count = len(config["metallicity_xsolar"]) * len(config["c_to_o_xsolar"])
    return total - len(excluded_pairs) * (total // chemistry_pair_count)


def expected_climate_grid_size(config: dict[str, Any]) -> int:
    spectra_per_climate = 1
    for axis in climate_spectrum_axes(config):
        spectra_per_climate *= len(config[axis])
    total = expected_grid_size(config)
    if total % spectra_per_climate:
        raise ValueError(
            f"Filtered grid size {total} is not divisible by {spectra_per_climate} spectra per climate."
        )
    return total // spectra_per_climate


def _metadata_columns(config: dict[str, Any]) -> dict[str, Any]:
    netcdf_config = config.get("netcdf", {})
    if netcdf_config is None:
        netcdf_config = {}
    if not isinstance(netcdf_config, dict):
        raise ValueError("Config key 'netcdf' must be a mapping when provided.")
    wavelength_grid = netcdf_config.get("wavelength_grid", {})
    if wavelength_grid is None:
        wavelength_grid = {}
    if not isinstance(wavelength_grid, dict):
        raise ValueError("Config key 'netcdf.wavelength_grid' must be a mapping when provided.")
    grid_mode = str(wavelength_grid.get("mode", DEFAULT_WAVELENGTH_GRID_MODE))
    wavelength_min_um = float(wavelength_grid.get("min_um", DEFAULT_WAVELENGTH_MIN_UM))
    wavelength_max_um = float(wavelength_grid.get("max_um", DEFAULT_WAVELENGTH_MAX_UM))
    wavelength_resolution = float(wavelength_grid.get("resolution", DEFAULT_WAVELENGTH_RESOLUTION))
    wavelength_points = int(wavelength_grid.get("points", DEFAULT_WAVELENGTH_POINTS))
    if grid_mode.strip().lower() in {"constant_resolution", "picaso_max", "picaso_resampled_max", "max"}:
        wavelength_points = int(math.ceil(math.log(wavelength_max_um / wavelength_min_um) * wavelength_resolution)) + 1
    metadata = {
        "author": config.get("author", ""),
        "contact": config.get("contact", ""),
        "project": config.get("project", ""),
        "notes": config.get("notes", ""),
        "code": json.dumps(config.get("code", {}), sort_keys=True),
        "picaso_tint_mode": config.get("picaso_tint_mode", "equilibrium"),
        "picaso_tint_fixed_k": float(config.get("picaso_tint_fixed_k", 1000.0)),
        "picaso_tint_floor_k": float(config.get("picaso_tint_floor_k", 100.0)),
        "virga_condensates": str(config.get("virga_condensates", "")),
        "netcdf_optional_variables": json.dumps(netcdf_config.get("optional_variables", []), sort_keys=True),
        "netcdf_strict_optional": bool(netcdf_config.get("strict_optional", False)),
        "wavelength_grid_mode": grid_mode,
        "wavelength_min_um": wavelength_min_um,
        "wavelength_max_um": wavelength_max_um,
        "wavelength_resolution": wavelength_resolution,
        "wavelength_points": wavelength_points,
        "source_notebook_reference": NOTEBOOK_REFERENCE,
    }
    if config.get("climate_reference_radius_rearth") not in (None, ""):
        metadata["climate_reference_radius_rearth"] = float(
            config["climate_reference_radius_rearth"]
        )
    return metadata


def create_manifest_dataframe(config: dict[str, Any]) -> ManifestTable:
    rows: list[dict[str, Any]] = []
    metadata = _metadata_columns(config)
    output_root = config["output_root"]
    run_index = 0
    excluded_pairs = unsupported_chemistry_pairs(config)

    axis_key = _planet_axis_key(config)
    products = itertools.product(
        config["stars"],
        config["planet_radius_rearth"],
        config[axis_key],
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
        primary_planet_axis_value,
        metallicity_xsolar,
        c_to_o_xsolar,
        kzz_cm2_s,
        cloud_fraction,
        fsed,
        insolation_searth,
        phase_deg,
    ) in products:
        chemistry_pair = (float(metallicity_xsolar), float(c_to_o_xsolar))
        if chemistry_pair in excluded_pairs:
            continue
        star_teff_k = float(star["teff_k"])
        star_radius_rsun = float(star["radius_rsun"])
        planet_radius_rearth_value = float(planet_radius_rearth)
        axis_value = float(primary_planet_axis_value)
        if axis_key == MASS_AXIS_KEY:
            planet_mass_mearth = axis_value
            gravity_ms2 = gravity_from_mass_radius_ms2(planet_mass_mearth, planet_radius_rearth_value)
        else:
            gravity_ms2 = axis_value
            planet_mass_mearth = mass_from_gravity_radius_mearth(gravity_ms2, planet_radius_rearth_value)
        luminosity_lsun = stellar_luminosity_lsun(star_teff_k, star_radius_rsun)
        semi_major_au = insolation_to_semi_major_au(luminosity_lsun, insolation_searth)
        teq_k = equilibrium_temperature_k(star_teff_k, star_radius_rsun, semi_major_au)
        row: dict[str, Any] = {
            "run_index": run_index,
            "model_name": config["model_name"],
            "star_teff_k": star_teff_k,
            "star_radius_rsun": star_radius_rsun,
            "stellar_luminosity_lsun": luminosity_lsun,
            "planet_radius_rearth": planet_radius_rearth_value,
            "planet_mass_mearth": float(planet_mass_mearth),
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
        if value in (None, ""):
            coerced[key] = value
            continue
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
