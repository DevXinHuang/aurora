#!/usr/bin/env python3
"""Convert one mentor SLGRID patchy-cloud case into an Aurora-style NetCDF file.

Local smoke-test mode works even before the mentor executable is available: it parses
and preserves the case metadata in a valid NetCDF. After SLGRID runs, it also tries to
attach the first numeric spectrum-like table it finds in the work directory.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


def _clean_value(line: str) -> str:
    s = line.strip()
    if not s:
        return ""
    if s.startswith("'"):
        m = re.match(r"'([^']*)'", s)
        return m.group(1) if m else s.strip("'")
    return s.split()[0]


def _as_bool(v: str) -> bool:
    return v.strip().upper().startswith("T")


def _as_float(v: str) -> float:
    return float(v.replace("D", "E").replace("d", "e"))


def parse_slgrid_deck(path: Path) -> dict[str, Any]:
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    v = [_clean_value(ln) for ln in lines]
    if len(v) < 44:
        raise ValueError(f"Input deck too short: found {len(v)} nonblank values in {path}")

    n_species = int(float(v[39]))
    species = v[44 : 44 + n_species]
    g_ms2 = _as_float(v[1])
    fhole = _as_float(v[36])
    fsed = _as_float(v[37])
    metal_dex = _as_float(v[4])

    meta = {
        "internal_temperature_k": _as_float(v[0]),
        "gravity_ms2": g_ms2,
        "gravity_cgs": g_ms2 * 100.0,
        "logg_cgs": math.log10(g_ms2 * 100.0),
        "rc_boundary_level": int(float(v[2])),
        "surface_albedo": _as_float(v[3]),
        "metallicity_dex": metal_dex,
        "metallicity_xsolar": 10.0 ** metal_dex,
        "lower_boundary_condition": int(float(v[5])),
        "abundance_path": v[6],
        "opacity_path": v[7],
        "generate_pressure_grid": _as_bool(v[8]),
        "pressure_min_bar": _as_float(v[9]),
        "pressure_max_bar": _as_float(v[10]),
        "pressure_grid_temperature_k": _as_float(v[11]),
        "tstart_file": v[12],
        "adiabat_option": {"1": "saumon", "2": "dry", "3": "moist"}.get(v[13], v[13]),
        "use_mmw_gradient": _as_bool(v[14]),
        "convergence_tolerance": _as_float(v[15]),
        "cfl_multiplier": _as_float(v[16]),
        "adjust_superadiabatic_gradients": _as_bool(v[17]),
        "superadiabatic_threshold": _as_float(v[18]),
        "convergence_option": int(float(v[19])),
        "initial_timestep_s": _as_float(v[20]),
        "n_timesteps": int(float(v[21])),
        "output_interval_timesteps": int(float(v[22])),
        "include_solar_fluxes": _as_bool(v[23]),
        "stellar_spectrum_file": v[24],
        "solar_file_lines": int(float(v[25])),
        "stellar_distance_au": _as_float(v[26]),
        "use_stellar_blackbody": _as_bool(v[27]),
        "stellar_teff_k": _as_float(v[28]),
        "stellar_radius_rsun": _as_float(v[29]),
        "case_id": v[30],
        "do_clouds": _as_bool(v[31]),
        "do_holes": _as_bool(v[32]),
        "do_saumon": _as_bool(v[33]),
        "use_disort": _as_bool(v[34]),
        "generate_smart_outputs": _as_bool(v[35]),
        "hole_fraction": fhole,
        "cloud_fraction": 1.0 - fhole,
        "fsed": fsed,
        "kzz_min_cm2_s": _as_float(v[38]),
        "n_condensible_species": n_species,
        "do_optics": _as_bool(v[40]),
        "read_mie_data": _as_bool(v[41]),
        "read_initial_cloud_profiles": _as_bool(v[42]),
        "cloud_start_file": v[43],
        "condensible_species": species,
    }
    return meta


def find_numeric_tables(work_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    if not work_dir.exists():
        return candidates
    allowed = {".txt", ".dat", ".out", ".flx", ".trn", ".rad", ".spc", ".spec", ".pt", ".csv"}
    for p in work_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in allowed:
            continue
        try:
            text = p.read_text(errors="ignore")[:8192]
        except Exception:
            continue
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[EeDd][-+]?\d+)?", text)
        if len(nums) > 20:
            candidates.append(p)
    return sorted(candidates)


def load_first_two_column_spectrum(work_dir: Path) -> tuple[Path, np.ndarray, np.ndarray] | None:
    for p in find_numeric_tables(work_dir):
        try:
            arr = np.genfromtxt(p, comments="#", delimiter=None)
        except Exception:
            continue
        if arr.ndim == 2 and arr.shape[1] >= 2 and arr.shape[0] >= 10:
            x = np.asarray(arr[:, 0], dtype=float)
            y = np.asarray(arr[:, 1], dtype=float)
            finite = np.isfinite(x) & np.isfinite(y)
            if finite.sum() >= 10:
                x = x[finite]
                y = y[finite]
                order = np.argsort(x)
                return p, x[order], y[order]
    return None


def build_dataset(meta: dict[str, Any], work_dir: Path) -> xr.Dataset:
    species_string = ";".join(meta["condensible_species"])
    now = datetime.now(timezone.utc).isoformat()

    # Always non-empty: one case dimension with the key scalar parameters as data variables.
    ds = xr.Dataset(
        data_vars={
            "internal_temperature_k": (("case",), [meta["internal_temperature_k"]]),
            "gravity_ms2": (("case",), [meta["gravity_ms2"]]),
            "logg_cgs": (("case",), [meta["logg_cgs"]]),
            "metallicity_xsolar": (("case",), [meta["metallicity_xsolar"]]),
            "metallicity_dex": (("case",), [meta["metallicity_dex"]]),
            "cloud_fraction": (("case",), [meta["cloud_fraction"]]),
            "cloud_hole_fraction": (("case",), [meta["hole_fraction"]]),
            "fsed": (("case",), [meta["fsed"]]),
            "kzz_min_cm2_s": (("case",), [meta["kzz_min_cm2_s"]]),
            "pressure_min_bar": (("case",), [meta["pressure_min_bar"]]),
            "pressure_max_bar": (("case",), [meta["pressure_max_bar"]]),
        },
        coords={"case": [meta["case_id"]]},
        attrs={
            "schema_name": "aurora_subneptune_netcdf",
            "schema_version": "1.0-patchy-slgrid-sidequest",
            "model_name": meta["case_id"],
            "run_type": "patchy_cloud_single_case",
            "source_model": "mentor_SLGRID_input_deck",
            "cloud_model": "patchy_cloud_with_clear_holes",
            "patchy_weighting_formula": "patchy_weighted = fhole * clear_column + (1 - fhole) * cloudy_column",
            "condensible_species": species_string,
            "created_utc": now,
            "raw_case_metadata_json": json.dumps(meta, sort_keys=True),
        },
    )

    units = {
        "internal_temperature_k": "K",
        "gravity_ms2": "m s-2",
        "logg_cgs": "log10(cm s-2)",
        "metallicity_xsolar": "solar",
        "metallicity_dex": "dex",
        "cloud_fraction": "1",
        "cloud_hole_fraction": "1",
        "fsed": "1",
        "kzz_min_cm2_s": "cm2 s-1",
        "pressure_min_bar": "bar",
        "pressure_max_bar": "bar",
    }
    for name, unit in units.items():
        ds[name].attrs["units"] = unit

    spec = load_first_two_column_spectrum(work_dir)
    if spec is not None:
        source_path, x, y = spec
        ds = ds.assign_coords(wavelength=("wavelength", x))
        ds["slgrid_primary_spectrum_column1"] = (("wavelength",), y)
        ds["wavelength"].attrs.update({"long_name": "first column from detected SLGRID/SMART numeric output", "units": "unknown"})
        ds["slgrid_primary_spectrum_column1"].attrs.update({"long_name": "second column from detected SLGRID/SMART numeric output", "units": "unknown"})
        ds.attrs["detected_numeric_output"] = str(source_path)
    else:
        ds.attrs["detected_numeric_output"] = "none; metadata-only local smoke test or no spectrum-like output found"

    return ds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", required=True)
    ap.add_argument("--input-deck", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--output-nc", required=True, type=Path)
    args = ap.parse_args()

    meta = parse_slgrid_deck(args.input_deck)
    if args.case_id:
        meta["case_id"] = args.case_id
    ds = build_dataset(meta, args.work_dir)
    args.output_nc.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(args.output_nc)
    print(f"Wrote {args.output_nc}")
    print(ds)


if __name__ == "__main__":
    main()
