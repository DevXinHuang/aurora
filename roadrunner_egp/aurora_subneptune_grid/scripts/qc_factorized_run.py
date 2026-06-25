#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
SRC_ROOT = GRID_ROOT / "src"
for path in (SRC_ROOT, ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aurora_grid.coupled_grid import load_grid_config
from aurora_grid.factorization import create_factorized_manifests, load_factorization_config, read_factorized_manifest_csv, resolve_repo_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QC a factorized Aurora climate/spectrum run.")
    parser.add_argument("--config", help="Factorized YAML config (for expected counts).")
    parser.add_argument("--climate-manifest", help="Climate manifest CSV path.")
    parser.add_argument("--spectrum-manifest", help="Spectrum manifest CSV path.")
    parser.add_argument("--map-manifest", help="Climate-spectrum map CSV path.")
    parser.add_argument("--require-outputs", action="store_true", help="Fail if spectrum output_nc files are missing.")
    parser.add_argument("--require-caches", action="store_true", help="Fail if climate_cache_nc files are missing.")
    return parser.parse_args()


def _check(name: str, passed: bool, detail: str = "") -> tuple[bool, str]:
    status = "PASS" if passed else "FAIL"
    line = f"{status:4s}  {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed, line


def main() -> int:
    args = parse_args()
    config = load_grid_config(args.config) if args.config else None
    factorization = load_factorization_config(config) if config else None

    if args.climate_manifest and args.spectrum_manifest:
        climate = read_factorized_manifest_csv(args.climate_manifest, kind="climate")
        spectrum = read_factorized_manifest_csv(args.spectrum_manifest, kind="spectrum")
        climate_map = (
            read_factorized_manifest_csv(args.map_manifest, kind="map")
            if args.map_manifest
            else None
        )
    elif config is not None:
        manifests = create_factorized_manifests(config)
        climate = manifests.climate
        spectrum = manifests.spectrum
        climate_map = manifests.climate_spectrum_map
    else:
        raise ValueError("Provide --config or both --climate-manifest and --spectrum-manifest.")

    all_pass = True

    if factorization and factorization.expected_climates is not None:
        ok, _ = _check(
            "expected_climate_count",
            len(climate) == factorization.expected_climates,
            f"got {len(climate)}, expected {factorization.expected_climates}",
        )
        all_pass = all_pass and ok

    if factorization and factorization.expected_spectra is not None:
        ok, _ = _check(
            "expected_spectrum_count",
            len(spectrum) == factorization.expected_spectra,
            f"got {len(spectrum)}, expected {factorization.expected_spectra}",
        )
        all_pass = all_pass and ok

    ok, _ = _check("unique_climate_cache_nc", not climate.has_duplicate("climate_cache_nc"))
    all_pass = all_pass and ok
    ok, _ = _check("unique_output_nc", not spectrum.has_duplicate("output_nc"))
    all_pass = all_pass and ok
    ok, _ = _check("unique_spectrum_run_id", not spectrum.has_duplicate("spectrum_run_id"))
    all_pass = all_pass and ok

    cache_paths = {str(row["climate_cache_nc"]) for row in climate.rows}
    spectrum_cache_refs = {str(row["climate_cache_nc"]) for row in spectrum.rows}
    ok, _ = _check(
        "spectrum_rows_reference_known_climate_caches",
        spectrum_cache_refs.issubset(cache_paths),
        f"missing {len(spectrum_cache_refs - cache_paths)} cache refs",
    )
    all_pass = all_pass and ok

    if args.require_caches:
        missing_caches = [path for path in cache_paths if not resolve_repo_path(path).exists()]
        ok, _ = _check(
            "climate_cache_files_exist",
            not missing_caches,
            f"missing {len(missing_caches)}",
        )
        all_pass = all_pass and ok

    if args.require_outputs:
        missing_outputs = [str(row["output_nc"]) for row in spectrum.rows if not resolve_repo_path(row["output_nc"]).exists()]
        ok, _ = _check(
            "spectrum_output_files_exist",
            not missing_outputs,
            f"missing {len(missing_outputs)}",
        )
        all_pass = all_pass and ok

    phases_by_climate: dict[str, list[float]] = {}
    for row in spectrum.rows:
        phases_by_climate.setdefault(str(row["climate_key"]), []).append(float(row["phase_deg"]))

    phase_counts = {key: len(values) for key, values in phases_by_climate.items()}
    uniform_phases = len(set(phase_counts.values())) == 1 if phase_counts else False
    ok, _ = _check(
        "uniform_phase_coverage_per_climate",
        uniform_phases,
        f"counts={sorted(set(phase_counts.values()))}",
    )
    all_pass = all_pass and ok

    if climate_map is not None:
        for row in climate_map.rows:
            indices = json.loads(row["spectrum_indices"])
            phases = json.loads(row["phase_deg_values"])
            ok, _ = _check(
                f"map_climate_{row['climate_index']}_phase_count",
                len(phases) == int(row["n_spectra"]) == len(indices),
                f"n_spectra={row['n_spectra']}, phases={len(phases)}",
            )
            all_pass = all_pass and ok

    if config and str(config.get("factorization", {}).get("grid_expansion", "")).lower() == "coupled_cases":
        by_class: dict[str, int] = {}
        for row in climate.rows:
            class_id = str(row.get("planet_class_id", ""))
            by_class[class_id] = by_class.get(class_id, 0) + 1
        expected_per_class = len(climate) // max(len(by_class), 1)
        for class_id, count in sorted(by_class.items()):
            ok, _ = _check(
                f"climate_count_{class_id}",
                count == expected_per_class,
                f"got {count}, expected {expected_per_class}",
            )
            all_pass = all_pass and ok

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
