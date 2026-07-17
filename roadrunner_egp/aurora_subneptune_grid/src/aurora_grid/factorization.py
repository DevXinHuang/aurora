from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coupled_grid import COUPLED_EXTRA_COLUMNS, expand_grid_manifest
from .naming import make_run_id, safe_label
from .parameters import (
    BOOL_COLUMNS,
    FLOAT_COLUMNS,
    INT_COLUMNS,
    MANIFEST_COLUMNS,
    ManifestTable,
    REPO_ROOT,
)

DEFAULT_CLIMATE_AXES = (
    "planet_class_id",
    "separation_id",
    "star_teff_k",
    "star_radius_rsun",
    "stellar_spectrum_filename",
    "stellar_spectrum_w_unit",
    "stellar_spectrum_f_unit",
    "semi_major_au",
    "insolation_searth",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "kzz_cm2_s",
    "cloud_fraction",
    "cloud_model",
    "virga_condensates",
    "fsed",
    "picaso_tint_k",
    "picaso_tint_mode",
    "atmosphere_source",
)

DEFAULT_OBSERVATION_AXES = (
    "phase_deg",
    "wavelength_grid_mode",
    "wavelength_min_um",
    "wavelength_max_um",
    "wavelength_resolution",
    "wavelength_points",
    "resolving_power",
    "instrument_bandpass",
)

FACTORIZATION_ANNOTATION_COLUMNS = (
    "climate_key",
    "climate_index",
    "climate_cache_nc",
    "spectrum_index",
    "spectrum_run_id",
)

FULL_FACTORIZED_COLUMNS = tuple(
    dict.fromkeys(
        list(MANIFEST_COLUMNS)
        + list(COUPLED_EXTRA_COLUMNS)
        + list(FACTORIZATION_ANNOTATION_COLUMNS)
        + [
            "stellar_spectrum_filename",
            "stellar_spectrum_w_unit",
            "stellar_spectrum_f_unit",
            "separation_notes",
        ]
    )
)

CLIMATE_MANIFEST_COLUMNS = tuple(
    dict.fromkeys(
        list(MANIFEST_COLUMNS)
        + list(COUPLED_EXTRA_COLUMNS)
        + [
            "climate_key",
            "climate_index",
            "climate_cache_nc",
            "climate_run_id",
            "stellar_spectrum_filename",
            "stellar_spectrum_w_unit",
            "stellar_spectrum_f_unit",
            "separation_notes",
        ]
    )
)

SPECTRUM_MANIFEST_COLUMNS = (
    "spectrum_index",
    "spectrum_run_id",
    "model_name",
    "climate_key",
    "climate_index",
    "climate_cache_nc",
    "phase_deg",
    "output_nc",
    "status",
    "planet_class_id",
    "separation_id",
    "star_teff_k",
    "star_radius_rsun",
    "stellar_spectrum_filename",
    "stellar_spectrum_w_unit",
    "stellar_spectrum_f_unit",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "cloud_fraction",
    "cloud_model",
    "virga_condensates",
    "fsed",
    "insolation_searth",
    "semi_major_au",
    "picaso_tint_k",
    "wavelength_grid_mode",
    "wavelength_min_um",
    "wavelength_max_um",
    "wavelength_resolution",
    "wavelength_points",
)

CLIMATE_SPECTRUM_MAP_COLUMNS = (
    "climate_index",
    "climate_key",
    "climate_cache_nc",
    "planet_class_id",
    "separation_id",
    "n_spectra",
    "spectrum_indices",
    "phase_deg_values",
)

CLIMATE_KEY_EXCLUDE_KEYS = {
    "run_index",
    "run_id",
    "output_nc",
    "status",
    "phase_deg",
    "spectrum_index",
    "spectrum_run_id",
    "climate_key",
    "climate_index",
    "climate_cache_nc",
    "author",
    "contact",
    "project",
    "notes",
    "code",
    "netcdf_optional_variables",
    "netcdf_strict_optional",
    "source_notebook_reference",
    "wavelength_grid_mode",
    "wavelength_min_um",
    "wavelength_max_um",
    "wavelength_resolution",
    "wavelength_points",
    "resolving_power",
    "instrument_bandpass",
}


@dataclass(frozen=True)
class FactorizationConfig:
    enabled: bool
    grid_expansion: str
    climate_axes: tuple[str, ...]
    observation_axes: tuple[str, ...]
    expected_climates: int | None
    expected_spectra: int | None
    cache_root: str | None


@dataclass(frozen=True)
class FactorizedManifests:
    full: ManifestTable
    climate: ManifestTable
    spectrum: ManifestTable
    climate_spectrum_map: ManifestTable


def load_factorization_config(config: dict[str, Any]) -> FactorizationConfig | None:
    block = config.get("factorization")
    if not isinstance(block, dict):
        return None
    enabled = bool(block.get("enabled", False))
    if not enabled:
        return None
    climate_axes = tuple(block.get("climate_axes", DEFAULT_CLIMATE_AXES))
    observation_axes = tuple(block.get("observation_axes", DEFAULT_OBSERVATION_AXES))
    expected_climates = block.get("expected_climates")
    expected_spectra = block.get("expected_spectra")
    cache_root = block.get("cache_root", config.get("cache_root"))
    grid_expansion = str(block.get("grid_expansion", "cartesian")).strip().lower()
    return FactorizationConfig(
        enabled=enabled,
        grid_expansion=grid_expansion,
        climate_axes=climate_axes,
        observation_axes=observation_axes,
        expected_climates=int(expected_climates) if expected_climates is not None else None,
        expected_spectra=int(expected_spectra) if expected_spectra is not None else None,
        cache_root=str(cache_root) if cache_root else None,
    )


def make_climate_key(row: dict[str, Any], climate_axes: tuple[str, ...] | None = None) -> str:
    from .naming import _json_safe
    import hashlib

    axes = climate_axes or DEFAULT_CLIMATE_AXES
    payload: dict[str, Any] = {}
    for axis in axes:
        if axis in row and row[axis] is not None and row[axis] != "":
            payload[axis] = _json_safe(row[axis])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:12]


def default_cache_root(model_name: str) -> str:
    return f"roadrunner_egp/aurora_subneptune_grid/cache/climates/{safe_label(model_name)}"


def make_climate_cache_path(
    model_name: str,
    climate_key: str,
    cache_root: str | None = None,
) -> str:
    root = Path(cache_root) if cache_root else Path(default_cache_root(model_name))
    filename = f"{safe_label(climate_key)}.nc"
    return str(root / filename)


def _write_manifest(table: ManifestTable, path: Path, columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(table.rows)


def _validate_factorized(full: ManifestTable, climate: ManifestTable, spectrum: ManifestTable, factorization: FactorizationConfig) -> None:
    if factorization.expected_climates is not None and len(climate) != factorization.expected_climates:
        raise ValueError(f"Climate manifest has {len(climate)} rows; expected {factorization.expected_climates}.")
    if factorization.expected_spectra is not None and len(spectrum) != factorization.expected_spectra:
        raise ValueError(f"Spectrum manifest has {len(spectrum)} rows; expected {factorization.expected_spectra}.")
    if full.has_duplicate("output_nc"):
        raise ValueError(f"Duplicate output_nc in full manifest: {full.duplicate_values('output_nc')}")
    if spectrum.has_duplicate("output_nc"):
        raise ValueError(f"Duplicate output_nc in spectrum manifest: {spectrum.duplicate_values('output_nc')}")
    if climate.has_duplicate("climate_cache_nc"):
        raise ValueError(f"Duplicate climate_cache_nc: {climate.duplicate_values('climate_cache_nc')}")
    if climate.has_duplicate("climate_key"):
        raise ValueError(f"Duplicate climate_key: {climate.duplicate_values('climate_key')}")

    phases_per_climate = [0] * len(climate)
    climate_key_to_index = {row["climate_key"]: int(row["climate_index"]) for row in climate.rows}
    for row in spectrum.rows:
        key = row["climate_key"]
        if key not in climate_key_to_index:
            raise ValueError(f"Spectrum row references unknown climate_key {key!r}.")
        phases_per_climate[climate_key_to_index[key]] += 1
    if phases_per_climate and len(set(phases_per_climate)) != 1:
        raise ValueError(f"Uneven phase coverage per climate: {phases_per_climate}")


def create_factorized_manifests(config: dict[str, Any]) -> FactorizedManifests:
    factorization = load_factorization_config(config)
    if factorization is None:
        raise ValueError("Config does not have factorization.enabled=true.")

    full_table = expand_grid_manifest(config)
    cache_root = factorization.cache_root or default_cache_root(config["model_name"])
    model_name = str(config["model_name"])

    annotated_full: list[dict[str, Any]] = []
    climate_by_key: dict[str, dict[str, Any]] = {}
    spectrum_rows: list[dict[str, Any]] = []
    map_rows: dict[str, dict[str, Any]] = {}

    for row in full_table.rows:
        annotated = dict(row)
        climate_key = make_climate_key(row, factorization.climate_axes)
        climate_cache_nc = make_climate_cache_path(model_name, climate_key, cache_root)
        annotated["climate_key"] = climate_key
        annotated["climate_cache_nc"] = climate_cache_nc
        annotated["spectrum_index"] = int(row["run_index"])
        annotated["spectrum_run_id"] = str(row["run_id"])

        if climate_key not in climate_by_key:
            climate_row = dict(row)
            climate_row.pop("phase_deg", None)
            climate_row.pop("output_nc", None)
            climate_row.pop("run_index", None)
            climate_row.pop("run_id", None)
            climate_row["climate_key"] = climate_key
            climate_row["climate_cache_nc"] = climate_cache_nc
            climate_row["climate_run_id"] = make_run_id({**climate_row, "phase_deg": 0.0})
            climate_by_key[climate_key] = climate_row
            map_rows[climate_key] = {
                "climate_key": climate_key,
                "climate_cache_nc": climate_cache_nc,
                "planet_class_id": row.get("planet_class_id", ""),
                "separation_id": row.get("separation_id", ""),
                "spectrum_indices": [],
                "phase_deg_values": [],
            }

        annotated_full.append(annotated)

        spectrum_row = {
            "spectrum_index": int(row["run_index"]),
            "spectrum_run_id": str(row["run_id"]),
            "model_name": model_name,
            "climate_key": climate_key,
            "climate_cache_nc": climate_cache_nc,
            "phase_deg": float(row["phase_deg"]),
            "output_nc": str(row["output_nc"]),
            "status": "pending",
            "planet_class_id": row.get("planet_class_id", ""),
            "separation_id": row.get("separation_id", ""),
            "star_teff_k": row["star_teff_k"],
            "star_radius_rsun": row["star_radius_rsun"],
            "stellar_spectrum_filename": row.get("stellar_spectrum_filename", ""),
            "stellar_spectrum_w_unit": row.get("stellar_spectrum_w_unit", ""),
            "stellar_spectrum_f_unit": row.get("stellar_spectrum_f_unit", ""),
            "planet_radius_rearth": row["planet_radius_rearth"],
            "gravity_ms2": row["gravity_ms2"],
            "metallicity_xsolar": row["metallicity_xsolar"],
            "c_to_o_xsolar": row["c_to_o_xsolar"],
            "cloud_fraction": row["cloud_fraction"],
            "cloud_model": row["cloud_model"],
            "virga_condensates": row.get("virga_condensates", ""),
            "fsed": row["fsed"],
            "insolation_searth": row["insolation_searth"],
            "semi_major_au": row["semi_major_au"],
            "picaso_tint_k": row["picaso_tint_k"],
            "wavelength_grid_mode": row.get("wavelength_grid_mode", ""),
            "wavelength_min_um": row.get("wavelength_min_um", ""),
            "wavelength_max_um": row.get("wavelength_max_um", ""),
            "wavelength_resolution": row.get("wavelength_resolution", ""),
            "wavelength_points": row.get("wavelength_points", ""),
        }
        spectrum_rows.append(spectrum_row)
        map_entry = map_rows[climate_key]
        map_entry["spectrum_indices"].append(int(row["run_index"]))
        map_entry["phase_deg_values"].append(float(row["phase_deg"]))

    climate_index_by_key = {
        climate_key: climate_index for climate_index, climate_key in enumerate(sorted(climate_by_key.keys()))
    }
    for annotated in annotated_full:
        annotated["climate_index"] = climate_index_by_key[str(annotated["climate_key"])]
    for spectrum_row in spectrum_rows:
        spectrum_row["climate_index"] = climate_index_by_key[str(spectrum_row["climate_key"])]

    climate_rows: list[dict[str, Any]] = []
    for climate_index, climate_key in enumerate(sorted(climate_by_key.keys())):
        climate_row = dict(climate_by_key[climate_key])
        climate_row["climate_index"] = climate_index
        climate_rows.append(climate_row)
        map_rows[climate_key]["climate_index"] = climate_index

    climate_spectrum_map_rows: list[dict[str, Any]] = []
    for climate_key in sorted(map_rows.keys()):
        entry = map_rows[climate_key]
        phase_values = sorted(set(entry["phase_deg_values"]))
        climate_spectrum_map_rows.append(
            {
                "climate_index": entry["climate_index"],
                "climate_key": entry["climate_key"],
                "climate_cache_nc": entry["climate_cache_nc"],
                "planet_class_id": entry.get("planet_class_id", ""),
                "separation_id": entry.get("separation_id", ""),
                "n_spectra": len(entry["spectrum_indices"]),
                "spectrum_indices": json.dumps(sorted(entry["spectrum_indices"])),
                "phase_deg_values": json.dumps(phase_values),
            }
        )

    full = ManifestTable(annotated_full)
    climate = ManifestTable(climate_rows)
    spectrum = ManifestTable(spectrum_rows)
    climate_spectrum_map = ManifestTable(climate_spectrum_map_rows)
    _validate_factorized(full, climate, spectrum, factorization)
    return FactorizedManifests(full=full, climate=climate, spectrum=spectrum, climate_spectrum_map=climate_spectrum_map)


def write_factorized_manifests(manifests: FactorizedManifests, out_dir: str | Path, prefix: str) -> dict[str, Path]:
    out_dir = Path(out_dir)
    paths = {
        "full": out_dir / f"{prefix}_full_manifest.csv",
        "climate": out_dir / f"{prefix}_climate_manifest.csv",
        "spectrum": out_dir / f"{prefix}_spectrum_manifest.csv",
        "map": out_dir / f"{prefix}_climate_spectrum_map.csv",
    }
    _write_manifest(manifests.full, paths["full"], FULL_FACTORIZED_COLUMNS)
    _write_manifest(manifests.climate, paths["climate"], CLIMATE_MANIFEST_COLUMNS)
    _write_manifest(manifests.spectrum, paths["spectrum"], SPECTRUM_MANIFEST_COLUMNS)
    _write_manifest(manifests.climate_spectrum_map, paths["map"], CLIMATE_SPECTRUM_MAP_COLUMNS)
    return paths


FACTORIZED_FLOAT_COLUMNS = FLOAT_COLUMNS | {
    "phase_deg",
    "climate_index",
    "spectrum_index",
    "star_teff_k",
    "star_radius_rsun",
    "planet_radius_rearth",
    "gravity_ms2",
    "metallicity_xsolar",
    "c_to_o_xsolar",
    "cloud_fraction",
    "fsed",
    "insolation_searth",
    "semi_major_au",
    "picaso_tint_k",
}
FACTORIZED_INT_COLUMNS = INT_COLUMNS | {"climate_index", "spectrum_index"}


def read_factorized_manifest_csv(path: str | Path, *, kind: str = "full") -> ManifestTable:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            coerced: dict[str, Any] = {}
            for key, value in row.items():
                if value == "" or value is None:
                    coerced[key] = value
                elif key in FACTORIZED_INT_COLUMNS:
                    coerced[key] = int(value)
                elif key in BOOL_COLUMNS:
                    coerced[key] = str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}
                elif key in FACTORIZED_FLOAT_COLUMNS:
                    coerced[key] = float(value)
                else:
                    coerced[key] = value
            rows.append(coerced)
    return ManifestTable(rows)


def resolve_repo_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return REPO_ROOT / path
