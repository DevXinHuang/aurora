from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from .config import (
    LEGACY_OPTIONAL_MANIFEST_KEYS,
    QUENCH_FAMILIES,
    REQUIRED_SPECIES,
    manifest_json,
    wavelength_grid,
)


SCHEMA_NAME = "aurora_picaso_tint_sensitivity"
SCHEMA_VERSION = "1.3"

PORTABLE_MANIFEST_KEYS = (
    "run_index",
    "run_id",
    "experiment_name",
    "case_id",
    "planet_mass_mearth",
    "planet_radius_rearth",
    "gravity_ms2",
    "equilibrium_temperature_k",
    "tint_k",
    "metallicity_xsolar",
    "cloud_id",
    "cloud_model",
    "cloud_fraction",
    "fsed",
    "star_teff_k",
    "star_radius_rsun",
    "c_to_o_xsolar",
    "c_to_o_absolute",
    "kzz_cm2_s",
    "phase_angle_deg",
    "chemistry_initialization",
    "chemistry_mode",
    "diseq_chem",
    "self_consistent_kzz",
    "quench",
    "wavelength_minimum_um",
    "wavelength_maximum_um",
    "wavelength_resolving_power",
)


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "unknown"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def build_dataset(result: dict[str, Any], row: dict[str, Any]) -> xr.Dataset:
    wave = np.asarray(result["wavelength_um"], dtype=float)
    pressure = np.asarray(result["pressure_bar"], dtype=float)
    temperature = np.asarray(result["temperature_k"], dtype=float)
    abundances = np.asarray(result["mole_fraction"], dtype=float)
    equilibrium_abundances = np.asarray(result["equilibrium_mole_fraction"], dtype=float)
    kz = np.asarray(result["kzz_cm2_s_profile"], dtype=float)
    if abundances.shape != (pressure.size, len(REQUIRED_SPECIES)):
        raise ValueError(f"Unexpected abundance shape {abundances.shape}")
    if equilibrium_abundances.shape != abundances.shape:
        raise ValueError(f"Unexpected equilibrium abundance shape {equilibrium_abundances.shape}")
    chemistry_mode = str(row.get("chemistry_mode", "disequilibrium_quench"))
    quench_pressures = result.get("quench_pressures_bar", {})
    missing_quench = [name for name in QUENCH_FAMILIES if name not in quench_pressures]
    if missing_quench and bool(result["quench_enabled"]):
        raise ValueError(f"Missing PICASO quench pressures for {missing_quench}")
    quench_pressure_values = np.asarray(
        [quench_pressures.get(name, np.nan) for name in QUENCH_FAMILIES], dtype=float
    )
    abundance_description = (
        "Final PICASO quenched abundance profiles."
        if chemistry_mode == "disequilibrium_quench"
        else "Final PICASO Visscher 2121 equilibrium abundance profiles; no quench adjustment."
    )
    ds = xr.Dataset(
        data_vars={
            "pressure_bar": (("level",), pressure, {"units": "bar"}),
            "temperature_k": (("level",), temperature, {"units": "K"}),
            "kzz_cm2_s_profile": (("level",), kz, {"units": "cm2 s-1"}),
            "mole_fraction": (
                ("level", "species"), abundances,
                {"units": "v/v", "description": abundance_description},
            ),
            "equilibrium_mole_fraction": (
                ("level", "species"), equilibrium_abundances,
                {
                    "units": "v/v",
                    "description": "Visscher 2121 equilibrium abundances evaluated on the final P-T profile.",
                },
            ),
            "quench_pressure_bar": (
                ("quench_family",),
                quench_pressure_values,
                {
                    "units": "bar",
                    "description": (
                        "PICASO timescale-crossing pressure; NaN when chemistry_mode is equilibrium_only."
                    ),
                },
            ),
            "transmission_depth": (
                ("wavelength",), np.asarray(result["transmission_depth"], dtype=float),
                {"units": "dimensionless", "description": "Transit depth (Rp/Rstar)^2."},
            ),
            "thermal_planet_star_flux_ratio": (
                ("wavelength",), np.asarray(result["thermal_planet_star_flux_ratio"], dtype=float),
                {"units": "dimensionless"},
            ),
            "reflected_planet_star_flux_ratio": (
                ("wavelength",), np.asarray(result["reflected_planet_star_flux_ratio"], dtype=float),
                {"units": "dimensionless", "description": "Phase-0 reflected planet/star flux ratio."},
            ),
            "geometric_albedo": (
                ("wavelength",), np.asarray(result["geometric_albedo"], dtype=float),
                {"units": "dimensionless"},
            ),
            "climate_converged": ((), np.int8(bool(result["climate_converged"]))),
            "climate_retry_count": ((), np.int32(result.get("climate_retry_count", 0))),
            "quench_enabled": ((), np.int8(bool(result["quench_enabled"]))),
            "quench_applied": ((), np.int8(bool(result["quench_applied"]))),
            "quench_profile_differs_from_equilibrium": (
                (), np.int8(bool(result["quench_profile_differs_from_equilibrium"]))
            ),
            "quench_pressure_extension_applied": (
                (), np.int8(bool(result.get("quench_pressure_extension_applied", False)))
            ),
            "quench_pressure_extension_retry_count": (
                (), np.int32(result.get("quench_pressure_extension_retry_count", 0))
            ),
            "virga_minimum_particle_clamp_count": (
                (), np.int32(result.get("virga_minimum_particle_clamp_count", 0))
            ),
            "zero_cloud_convergence_guard_count": (
                (), np.int32(result.get("zero_cloud_convergence_guard_count", 0))
            ),
            "diseq_chem": ((), np.int8(bool(result["diseq_chem"]))),
            "self_consistent_kzz": ((), np.int8(bool(result["self_consistent_kzz"]))),
            "thermal_flux_ratio_corrected": ((), np.int8(1)),
            "max_quench_log10_difference": ((), float(result["max_quench_log10_difference"])),
            "max_equilibrium_consistency_log10_difference": (
                (), float(result.get("max_equilibrium_consistency_log10_difference", 0.0))
            ),
            "runtime_seconds": ((), float(result["runtime_seconds"]), {"units": "s"}),
        },
        coords={
            "level": np.arange(pressure.size, dtype=np.int32),
            "species": np.asarray(REQUIRED_SPECIES, dtype=str),
            "quench_family": np.asarray(QUENCH_FAMILIES, dtype=str),
            "wavelength_um": (("wavelength",), wave, {"units": "um"}),
        },
        attrs={
            "title": "Aurora 36-model PICASO Tint-sensitivity experiment",
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "run_id": row["run_id"],
            "experiment_name": row["experiment_name"],
            "manifest_json": manifest_json(row),
            "chemistry_initialization": row["chemistry_initialization"],
            "chemistry_mode": chemistry_mode,
            "chemistry_provenance": (
                "Visscher 2121 equilibrium initialization followed by PICASO quench approximation"
                if chemistry_mode == "disequilibrium_quench"
                else "PICASO Visscher 2121 equilibrium chemistry only; no quench adjustment"
            ),
            "climate_call_diseq_chem": str(bool(result["diseq_chem"])).lower(),
            "climate_call_self_consistent_kzz": str(
                bool(result["self_consistent_kzz"])
            ).lower(),
            "atmosphere_quench_flag": str(bool(result["quench_enabled"])).lower(),
            "kzz_role": (
                "chemistry_and_virga"
                if chemistry_mode == "disequilibrium_quench"
                else "virga_only_not_chemistry"
            ),
            "phase_angle_deg": float(row["phase_angle_deg"]),
            "virga_condensates": ",".join(row["virga_condensates"]),
            "picaso_version": _version("picaso"),
            "virga_version": _version("virga-exo"),
            "xarray_version": xr.__version__,
            "python_version": platform.python_version(),
            "git_commit": _git_commit(),
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "selected_opacity_file": str(result["selected_opacity_file"]),
            "interpolation_diagnostics": json.dumps(
                result.get("interpolation_diagnostics", {}), sort_keys=True
            ),
            "thermal_flux_ratio_method": (
                "planet flux density divided by stellar mean flux density after converting "
                "PICASO climate stellar bin integrals with native wavelength-bin widths"
            ),
            "thermal_flux_ratio_correction_diagnostics": json.dumps(
                result.get("thermal_flux_ratio_correction", {}), sort_keys=True
            ),
            "quench_pressure_extension_maximum_bar": (
                "none"
                if result.get("quench_pressure_extension_maximum_bar") is None
                else str(float(result["quench_pressure_extension_maximum_bar"]))
            ),
            "virga_minimum_particle_radius_cm": str(
                float(result.get("virga_minimum_particle_radius_cm", 1.0e-8))
            ),
            "equilibrium_consistency_tolerance_dex": str(
                float(result.get("equilibrium_consistency_tolerance_dex", 1.0e-2))
            ),
        },
    )
    for name in (
        "run_index", "planet_mass_mearth", "planet_radius_rearth", "gravity_ms2",
        "equilibrium_temperature_k", "tint_k", "metallicity_xsolar", "cloud_fraction",
        "fsed", "star_teff_k", "star_radius_rsun", "c_to_o_xsolar", "c_to_o_absolute",
        "kzz_cm2_s", "phase_angle_deg", "semi_major_axis_au", "wavelength_minimum_um",
        "wavelength_maximum_um", "wavelength_resolving_power",
        "pressure_top_bar", "pressure_bottom_bar", "pressure_log10_spacing",
        "climate_retry_attempts",
        "equilibrium_consistency_tolerance_dex",
    ):
        ds[name] = np.asarray(row[name])
    issues = validate_dataset(ds, row)
    if issues:
        raise ValueError("; ".join(issues))
    return ds


def validate_dataset(ds: xr.Dataset, expected_row: dict[str, Any] | None = None) -> list[str]:
    issues: list[str] = []
    if ds.attrs.get("schema_name") != SCHEMA_NAME:
        issues.append(
            f"schema_name is {ds.attrs.get('schema_name')!r}; expected {SCHEMA_NAME!r}"
        )
    if ds.attrs.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            f"schema_version is {ds.attrs.get('schema_version')!r}; expected {SCHEMA_VERSION!r}"
        )
    required = {
        "pressure_bar", "temperature_k", "kzz_cm2_s_profile", "mole_fraction",
        "equilibrium_mole_fraction", "quench_pressure_bar",
        "transmission_depth", "thermal_planet_star_flux_ratio",
        "reflected_planet_star_flux_ratio", "geometric_albedo", "climate_converged",
        "climate_retry_count",
        "quench_enabled", "quench_applied", "diseq_chem", "self_consistent_kzz",
        "thermal_flux_ratio_corrected",
        "zero_cloud_convergence_guard_count",
    }
    missing = sorted(required.difference(ds.variables))
    if missing:
        issues.append(f"missing variables: {missing}")
        return issues
    if tuple(str(x) for x in ds["species"].values.tolist()) != REQUIRED_SPECIES:
        issues.append("species coordinate is not the required six-species ordering")
    if tuple(str(x) for x in ds["quench_family"].values.tolist()) != QUENCH_FAMILIES:
        issues.append("quench_family coordinate is not the required PICASO ordering")
    pressure = np.asarray(ds["pressure_bar"].values, dtype=float)
    if pressure.size < 2 or np.any(~np.isfinite(pressure)) or np.any(pressure <= 0):
        issues.append("pressure grid must contain at least two finite positive levels")
    elif not (np.all(np.diff(pressure) > 0) or np.all(np.diff(pressure) < 0)):
        issues.append("pressure grid is not strictly monotonic")
    wave = np.asarray(ds["wavelength_um"].values, dtype=float)
    if wave.size < 2 or not np.all(np.diff(wave) > 0):
        issues.append("wavelength grid is not strictly increasing")
    else:
        resolution = 1.0 / np.diff(np.log(wave))
        if not np.allclose(resolution, 1000.0, rtol=5e-4, atol=0.0):
            issues.append("wavelength grid is not constant R=1000")
        if not np.isclose(wave[0], 0.6) or not np.isclose(wave[-1], 15.0):
            issues.append("wavelength endpoints are not 0.6 and 15 um")
    chemistry_mode = str(
        ds.attrs.get(
            "chemistry_mode",
            "disequilibrium_quench" if int(ds["diseq_chem"].item()) == 1 else "equilibrium_only",
        )
    )
    finite_exempt = {"climate_converged"}
    if chemistry_mode == "equilibrium_only":
        finite_exempt.add("quench_pressure_bar")
    for name in required.difference(finite_exempt):
        if name in ds and np.issubdtype(ds[name].dtype, np.number):
            values = np.asarray(ds[name].values)
            if not np.all(np.isfinite(values)):
                issues.append(f"{name} contains non-finite values")
    kz = np.asarray(ds["kzz_cm2_s_profile"].values, dtype=float)
    if not np.all(kz == 1.0e10):
        issues.append("kzz profile is not fixed at 1e10 cm2/s")
    expected_controls = {
        "disequilibrium_quench": (1, 1, 1, 0),
        "equilibrium_only": (0, 0, 0, 0),
    }.get(chemistry_mode)
    actual_controls = (
        int(ds["quench_enabled"].item()),
        int(ds["quench_applied"].item()),
        int(ds["diseq_chem"].item()),
        int(ds["self_consistent_kzz"].item()),
    )
    if expected_controls is None:
        issues.append(f"unsupported chemistry_mode {chemistry_mode!r}")
    elif actual_controls != expected_controls:
        issues.append(
            f"chemistry controls {actual_controls!r} do not match {chemistry_mode!r} "
            f"expected {expected_controls!r}"
        )
    if int(ds["climate_converged"].item()) != 1:
        issues.append("climate solution is not converged")
    if int(ds["thermal_flux_ratio_corrected"].item()) != 1:
        issues.append("thermal planet/star flux ratio is not marked as unit-corrected")
    thermal = np.asarray(ds["thermal_planet_star_flux_ratio"].values, dtype=float)
    if np.any(thermal < 0.0) or float(np.max(thermal)) >= 0.05:
        issues.append("thermal planet/star flux ratio is outside the physical validation bound [0, 0.05)")
    quench_pressure = np.asarray(ds["quench_pressure_bar"].values, dtype=float)
    if chemistry_mode == "disequilibrium_quench":
        if np.any(~np.isfinite(quench_pressure)) or np.any(quench_pressure <= 0.0):
            issues.append("quench pressures must be finite and positive")
    elif not np.all(np.isnan(quench_pressure)):
        issues.append("equilibrium-only products must store NaN quench pressures as not applicable")
    if chemistry_mode == "equilibrium_only":
        if "quench_profile_differs_from_equilibrium" not in ds:
            issues.append("equilibrium-only product is missing its quench-difference flag")
        elif int(ds["quench_profile_differs_from_equilibrium"].item()) != 0:
            issues.append("equilibrium-only product is incorrectly marked as changed by quenching")
        if "max_quench_log10_difference" not in ds:
            issues.append("equilibrium-only product is missing its quench-difference diagnostic")
        elif float(ds["max_quench_log10_difference"].item()) != 0.0:
            issues.append("equilibrium-only product must have zero quench difference")
        if "max_equilibrium_consistency_log10_difference" not in ds:
            issues.append("equilibrium-only product is missing its equilibrium consistency diagnostic")
        else:
            tolerance = float(ds.attrs.get("equilibrium_consistency_tolerance_dex", 1.0e-2))
            consistency = float(ds["max_equilibrium_consistency_log10_difference"].item())
            if not np.isfinite(consistency) or consistency > tolerance:
                issues.append(
                    f"equilibrium consistency difference {consistency:g} dex exceeds {tolerance:g} dex"
                )
    if expected_row is not None:
        if chemistry_mode != expected_row.get("chemistry_mode", "disequilibrium_quench"):
            issues.append("chemistry_mode does not match manifest")
        if ds.attrs.get("run_id") != expected_row["run_id"]:
            issues.append("run_id does not match manifest")
        try:
            stored = json.loads(ds.attrs["manifest_json"])
        except Exception:
            issues.append("manifest_json is not valid JSON")
        else:
            mismatches = [
                key
                for key in PORTABLE_MANIFEST_KEYS
                if key not in LEGACY_OPTIONAL_MANIFEST_KEYS
                and stored.get(key) != expected_row.get(key)
            ]
            if mismatches:
                issues.append(
                    "stored manifest scientific fields do not match expected manifest: "
                    f"{mismatches}"
                )
        expected_wave = wavelength_grid(expected_row)
        if wave.shape != expected_wave.shape or not np.allclose(
            wave, expected_wave, rtol=1.0e-12, atol=1.0e-14
        ):
            issues.append("wavelength coordinate does not exactly match manifest grid")
    return issues


def validate_file(path: str | Path, expected_row: dict[str, Any] | None = None) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"missing file: {path}"]
    try:
        with xr.open_dataset(path) as ds:
            ds.load()
            return validate_dataset(ds, expected_row)
    except Exception as exc:
        return [f"cannot open/validate {path}: {exc}"]


def write_atomic(ds: xr.Dataset, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        temporary.unlink()
    encoding = {
        name: {"zlib": True, "complevel": 4, "shuffle": True}
        for name, variable in ds.data_vars.items()
        if variable.ndim > 0 and np.issubdtype(variable.dtype, np.number)
    }
    try:
        ds.to_netcdf(temporary, engine="netcdf4", encoding=encoding)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
