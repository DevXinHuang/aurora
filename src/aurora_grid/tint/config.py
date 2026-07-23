from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import yaml


EXPECTED_MODEL_COUNT = 36
REQUIRED_SPECIES = ("CH4", "CO2", "CO", "NH3", "HCN", "H2O")
QUENCH_FAMILIES = ("CO-CH4-H2O", "CO2", "NH3-N2", "HCN")
LEGACY_OPTIONAL_MANIFEST_KEYS = {
    "chemistry_mode",
    "equilibrium_consistency_tolerance_dex",
    "pressure_top_bar",
    "pressure_bottom_bar",
    "pressure_log10_spacing",
    "pressure_grid_strategy",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_experiment(path: str | Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Experiment configuration must be a mapping: {path}")
    config["_config_path"] = str(path)
    config["_config_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    validate_config(config)
    return config


def _semi_major_axis_au(star_teff_k: float, star_radius_rsun: float, teq_k: float) -> float:
    # Teq = Tstar sqrt(Rstar / 2a), with zero Bond albedo and full redistribution.
    r_sun_au = 0.004650467260962157
    return 0.5 * star_radius_rsun * r_sun_au * (star_teff_k / teq_k) ** 2


def _run_id(index: int, case: dict[str, Any], tint: float, cloud: dict[str, Any], metallicity: float) -> str:
    return (
        f"{index:02d}_{case['id']}_tint{int(tint):03d}_"
        f"{cloud['id']}_mh{int(metallicity):03d}x"
    )


def manifests(config: dict[str, Any]) -> list[dict[str, Any]]:
    fixed = config["fixed"]
    wavelength = config["wavelength"]
    paths = config["paths"]
    repo_root = _repo_root()
    rows: list[dict[str, Any]] = []
    combinations = itertools.product(
        config["cases"],
        config["axes"]["tint_k"],
        config["axes"]["cloud"],
        config["axes"]["metallicity_xsolar"],
    )
    for index, (case, tint, cloud, metallicity) in enumerate(combinations):
        row: dict[str, Any] = {
            "run_index": index,
            "run_id": _run_id(index, case, float(tint), cloud, float(metallicity)),
            "experiment_name": config["experiment"]["name"],
            "case_id": case["id"],
            "case_label": case["label"],
            "planet_mass_mearth": float(case["planet_mass_mearth"]),
            "planet_radius_rearth": float(case["planet_radius_rearth"]),
            "gravity_ms2": float(case["gravity_ms2"]),
            "equilibrium_temperature_k": float(case["equilibrium_temperature_k"]),
            "tint_k": float(tint),
            "metallicity_xsolar": float(metallicity),
            "cloud_id": cloud["id"],
            "cloud_model": cloud["cloud_model"],
            "cloud_fraction": float(cloud["cloud_fraction"]),
            "fsed": float(cloud["fsed"]),
            "star_teff_k": float(fixed["star_teff_k"]),
            "star_radius_rsun": float(fixed["star_radius_rsun"]),
            "c_to_o_xsolar": float(fixed["c_to_o_xsolar"]),
            "c_to_o_absolute": float(fixed["c_to_o_absolute"]),
            "kzz_cm2_s": float(fixed["kzz_cm2_s"]),
            "phase_angle_deg": float(fixed["phase_angle_deg"]),
            "virga_condensates": list(fixed["virga_condensates"]),
            "chemistry_initialization": str(fixed["chemistry_initialization"]),
            "chemistry_mode": str(fixed.get("chemistry_mode", "disequilibrium_quench")),
            "equilibrium_consistency_tolerance_dex": float(
                fixed.get("equilibrium_consistency_tolerance_dex", 1.0e-2)
            ),
            "diseq_chem": bool(fixed["diseq_chem"]),
            "self_consistent_kzz": bool(fixed["self_consistent_kzz"]),
            "quench": bool(fixed["quench"]),
            "redistribution_factor": float(fixed["redistribution_factor"]),
            "bond_albedo_for_orbit": float(fixed["bond_albedo_for_orbit"]),
            "pressure_levels": int(fixed["pressure_levels"]),
            "climate_retry_attempts": int(fixed["climate_retry_attempts"]),
            "wavelength_minimum_um": float(wavelength["minimum_um"]),
            "wavelength_maximum_um": float(wavelength["maximum_um"]),
            "wavelength_resolving_power": float(wavelength["resolving_power"]),
            "config_path": config["_config_path"],
            "config_sha256": config["_config_sha256"],
        }
        row["semi_major_axis_au"] = _semi_major_axis_au(
            row["star_teff_k"], row["star_radius_rsun"], row["equilibrium_temperature_k"]
        )
        row["pressure_top_bar"] = 1.0e-6
        row["pressure_log10_spacing"] = 0.125
        if row["chemistry_mode"] == "disequilibrium_quench" and row["equilibrium_temperature_k"] >= 500.0:
            # The PICASO quench timescale crossings move deeper for lower Tint.
            # These bounds retain the default 0.125-dex sampling while enclosing
            # all four PICASO quench families on the initial hot-case profiles.
            bottom_log10 = {25.0: 6.0, 50.0: 5.0, 100.0: 4.0}[row["tint_k"]]
            row["pressure_grid_strategy"] = "quench_complete_adaptive_deep"
        else:
            bottom_log10 = 1.5
            row["pressure_grid_strategy"] = "picaso_guillot_default"
        row["pressure_bottom_bar"] = 10.0 ** bottom_log10
        row["pressure_levels"] = int(
            round((bottom_log10 - math.log10(row["pressure_top_bar"])) / row["pressure_log10_spacing"])
        ) + 1
        for key in ("reference_data", "opacity_directory", "virga_directory", "output_directory"):
            candidate = Path(paths[key]).expanduser()
            row[key] = str(candidate if candidate.is_absolute() else (repo_root / candidate).resolve())
        row["output_path"] = str(Path(row["output_directory"]) / f"{row['run_id']}.nc")
        rows.append(row)
    return rows


def validate_config(config: dict[str, Any]) -> None:
    rows = manifests(config)
    if len(rows) != EXPECTED_MODEL_COUNT:
        raise ValueError(f"Expected exactly {EXPECTED_MODEL_COUNT} models, got {len(rows)}")
    ids = [row["run_id"] for row in rows]
    if len(set(ids)) != EXPECTED_MODEL_COUNT:
        raise ValueError("Experiment contains duplicate run_id values")
    signatures = {
        (
            row["case_id"], row["tint_k"], row["cloud_id"], row["metallicity_xsolar"]
        )
        for row in rows
    }
    if len(signatures) != EXPECTED_MODEL_COUNT:
        raise ValueError("Experiment does not contain 36 unique coupled case/Tint/cloud/metallicity models")
    fixed = config["fixed"]
    chemistry_mode = str(fixed.get("chemistry_mode", "disequilibrium_quench"))
    if chemistry_mode not in {"disequilibrium_quench", "equilibrium_only"}:
        raise ValueError(
            "fixed.chemistry_mode must be 'disequilibrium_quench' or 'equilibrium_only'"
        )
    required_fixed = {
        "star_teff_k": 3500.0,
        "star_radius_rsun": 0.45,
        "c_to_o_xsolar": 1.0,
        "kzz_cm2_s": 1.0e10,
        "phase_angle_deg": 0.0,
        "climate_retry_attempts": 2,
    }
    for key, expected in required_fixed.items():
        if fixed.get(key) != expected:
            raise ValueError(f"fixed.{key} must be {expected!r}, got {fixed.get(key)!r}")
    expected_chemistry_controls = {
        "disequilibrium_quench": {
            "diseq_chem": True,
            "self_consistent_kzz": False,
            "quench": True,
        },
        "equilibrium_only": {
            "diseq_chem": False,
            "self_consistent_kzz": False,
            "quench": False,
        },
    }[chemistry_mode]
    for key, expected in expected_chemistry_controls.items():
        if fixed.get(key) is not expected:
            raise ValueError(
                f"fixed.{key} must be {expected!r} for chemistry_mode={chemistry_mode!r}, "
                f"got {fixed.get(key)!r}"
            )
    if chemistry_mode == "equilibrium_only" and float(
        fixed.get("equilibrium_consistency_tolerance_dex", -1.0)
    ) != 1.0e-2:
        raise ValueError("fixed.equilibrium_consistency_tolerance_dex must be 1e-2")
    if tuple(fixed.get("virga_condensates", ())) != ("H2O", "CH4", "NH3"):
        raise ValueError("Virga condensates must be exactly H2O, CH4, NH3")
    wave = config["wavelength"]
    if (float(wave["minimum_um"]), float(wave["maximum_um"]), float(wave["resolving_power"])) != (0.6, 15.0, 1000.0):
        raise ValueError("Wavelength grid must be 0.6-15 um at constant R=1000")
    analysis = config.get("analysis", {})
    abundance_pressure = float(analysis.get("abundance_pressure_bar", 1.0e-3))
    if abundance_pressure <= 0:
        raise ValueError("analysis.abundance_pressure_bar must be positive")
    headline = analysis.get("headline_combination", {})
    cloud_ids = {str(item["id"]) for item in config["axes"]["cloud"]}
    if str(headline.get("cloud_id", "fully_cloudy_virga")) not in cloud_ids:
        raise ValueError("analysis.headline_combination.cloud_id is not in the cloud axis")
    metallicities = {float(value) for value in config["axes"]["metallicity_xsolar"]}
    if float(headline.get("metallicity_xsolar", 100.0)) not in metallicities:
        raise ValueError(
            "analysis.headline_combination.metallicity_xsolar is not in the metallicity axis"
        )
    guide = analysis.get("precision_guide", {})
    band = tuple(float(value) for value in guide.get("band_ppm", (20.0, 50.0)))
    if len(band) != 2 or band[0] < 0 or band[1] <= band[0]:
        raise ValueError("analysis.precision_guide.band_ppm must be [low, high] with 0 <= low < high")
    if float(guide.get("reference_ppm", 30.0)) < 0:
        raise ValueError("analysis.precision_guide.reference_ppm must be nonnegative")


def model_manifest(config: dict[str, Any], index: int) -> dict[str, Any]:
    rows = manifests(config)
    if index < 0 or index >= len(rows):
        raise IndexError(f"Model index {index} is outside 0..{len(rows) - 1}")
    return rows[index]


def manifest_json(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)


def wavelength_grid(row: dict[str, Any]):
    import numpy as np

    minimum = float(row["wavelength_minimum_um"])
    maximum = float(row["wavelength_maximum_um"])
    resolving_power = float(row["wavelength_resolving_power"])
    count = int(math.ceil(math.log(maximum / minimum) * resolving_power)) + 1
    return np.geomspace(minimum, maximum, count)
