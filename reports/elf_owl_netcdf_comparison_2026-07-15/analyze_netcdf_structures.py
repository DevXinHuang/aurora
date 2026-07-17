from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import xarray as xr


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(__file__).resolve().parent
ELF_DIR = ROOT / "science_inputs/sonora_elf_owl_v2/teff_1300_1500"
AURORA_DIR = ROOT / "outputs/weekend_nc"
PATCHY_FILE = (
    ROOT
    / "roadrunner_egp/aurora_subneptune_grid/outputs/patchy_cloud/"
    "PICASO_T1000_g100_m+000_CO100_fsed3_frac50.patchy_picaso.nc"
)
ELF_PATTERN = re.compile(
    r"spectra_logzz_([^_]+)_teff_([^_]+)_grav_([^_]+)_mh_([^_]+)_co_([^_]+)\.nc$"
)


def file_set(path: Path) -> list[Path]:
    return sorted(path.glob("*.nc"))


def evenly_spaced(paths: list[Path], count: int = 60) -> list[Path]:
    if len(paths) <= count:
        return paths
    return [paths[i] for i in np.linspace(0, len(paths) - 1, count, dtype=int)]


def schema_signature(ds: xr.Dataset) -> tuple:
    return (
        tuple(sorted(ds.sizes)),
        tuple(sorted(ds.variables)),
        tuple(sorted(ds.attrs)),
        tuple(sorted((name, tuple(var.dims), str(var.dtype)) for name, var in ds.variables.items())),
    )


def sampled_schema_consistency(paths: list[Path]) -> dict:
    sampled = evenly_spaced(paths)
    signatures = Counter()
    failures = []
    files_with_index_species = 0
    for path in sampled:
        try:
            with xr.open_dataset(path) as ds:
                signatures[str(schema_signature(ds))] += 1
                if "species" in ds and "index" in [str(value) for value in ds["species"].values.tolist()]:
                    files_with_index_species += 1
        except Exception as exc:  # pragma: no cover - evidence capture
            failures.append({"file": path.name, "error": str(exc)})
    return {
        "sample_size": len(sampled),
        "distinct_schema_signatures": len(signatures),
        "largest_signature_count": max(signatures.values(), default=0),
        "failures": failures,
        "files_with_index_species": files_with_index_species,
    }


def spectral_stats(wavelength: np.ndarray) -> dict:
    wavelength = np.asarray(wavelength, dtype=float)
    delta = np.diff(wavelength)
    resolving_power = np.abs(wavelength[:-1] / delta)
    return {
        "points": int(wavelength.size),
        "min_um": float(np.nanmin(wavelength)),
        "max_um": float(np.nanmax(wavelength)),
        "ascending": bool(np.all(delta > 0)),
        "descending": bool(np.all(delta < 0)),
        "r_min": float(np.nanmin(resolving_power)),
        "r_median": float(np.nanmedian(resolving_power)),
        "r_max": float(np.nanmax(resolving_power)),
        "r_outlier_count_below_59999": int(np.count_nonzero(resolving_power < 59999)),
    }


def variable_rows(ds: xr.Dataset, family: str) -> list[dict]:
    rows = []
    for name, var in ds.variables.items():
        encoding = var.encoding
        rows.append(
            {
                "family": family,
                "name": name,
                "role": "coordinate" if name in ds.coords else "data variable",
                "dimensions": ", ".join(var.dims) if var.dims else "scalar",
                "dtype": str(var.dtype),
                "units": str(var.attrs.get("units", "")),
                "description": str(var.attrs.get("description", "")),
                "compressed": bool(encoding.get("zlib", False)),
                "chunks": str(encoding.get("chunksizes")),
            }
        )
    return rows


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    elf_files = file_set(ELF_DIR)
    aurora_files = file_set(AURORA_DIR)

    parsed = []
    unmatched = []
    for path in elf_files:
        match = ELF_PATTERN.match(path.name)
        if match:
            parsed.append(tuple(float(value) for value in match.groups()))
        else:
            unmatched.append(path.name)
    axis_names = ["logkzz", "teff_k", "gravity_ms2", "metallicity_dex", "c_to_o_xsolar"]
    axes = {
        name: sorted({row[index] for row in parsed})
        for index, name in enumerate(axis_names)
    }
    full_product = int(np.prod([len(values) for values in axes.values()]))
    counts_by_teff = Counter(row[1] for row in parsed)
    counts_by_gravity = Counter(row[2] for row in parsed)

    elf_sample = elf_files[0]
    aurora_sample = AURORA_DIR / "run_0000000.nc"
    if not aurora_sample.exists():
        aurora_sample = aurora_files[0]

    with xr.open_dataset(elf_sample) as elf, xr.open_dataset(
        aurora_sample
    ) as aurora:
        elf_species = [name for name in elf.data_vars if name not in {"temperature", "flux"}]
        aurora_species = [str(value) for value in aurora["species"].values.tolist()]
        elf_chemistry_sums = np.sum(
            np.stack([np.asarray(elf[name].values, dtype=float) for name in elf_species]), axis=0
        )
        aurora_mole_fraction = np.asarray(aurora["mole_fraction"].values, dtype=float)
        aurora_chemistry_sums = np.nansum(aurora_mole_fraction, axis=1)
        aurora_index_species = "index" in aurora_species
        if aurora_index_species:
            index_position = aurora_species.index("index")
            aurora_without_index = np.delete(aurora_mole_fraction, index_position, axis=1)
            aurora_sums_without_index = np.nansum(aurora_without_index, axis=1)
            index_values = aurora_mole_fraction[:, index_position]
        else:
            aurora_sums_without_index = aurora_chemistry_sums
            index_values = np.asarray([], dtype=float)
        variable_inventory = variable_rows(elf, "Elf Owl") + variable_rows(aurora, "AURORA")
        summary = {
            "elf": {
                "files": len(elf_files),
                "bytes_uncompressed": sum(path.stat().st_size for path in elf_files),
                "representative_file": elf_sample.name,
                "dimensions": dict(elf.sizes),
                "coordinate_names": list(elf.coords),
                "data_variable_count": len(elf.data_vars),
                "global_attribute_count": len(elf.attrs),
                "global_attributes": list(elf.attrs),
                "spectral": spectral_stats(elf["wavelength"].values),
                "pressure_min_bar": float(elf["pressure"].min()),
                "pressure_max_bar": float(elf["pressure"].max()),
                "pressure_ascending": bool(np.all(np.diff(elf["pressure"].values) > 0)),
                "species_count": len(elf_species),
                "species": elf_species,
                "chemistry_sum_min": float(np.nanmin(elf_chemistry_sums)),
                "chemistry_sum_max": float(np.nanmax(elf_chemistry_sums)),
                "all_float64": all(var.dtype == np.dtype("float64") for var in elf.variables.values()),
                "compressed_variable_count": sum(
                    bool(var.encoding.get("zlib", False)) for var in elf.variables.values()
                ),
            },
            "aurora": {
                "files": len(aurora_files),
                "bytes": sum(path.stat().st_size for path in aurora_files),
                "representative_file": aurora_sample.name,
                "dimensions": dict(aurora.sizes),
                "coordinate_names": list(aurora.coords),
                "data_variable_count": len(aurora.data_vars),
                "global_attribute_count": len(aurora.attrs),
                "schema_name": aurora.attrs.get("schema_name"),
                "schema_version": aurora.attrs.get("schema_version"),
                "spectral": spectral_stats(aurora["wavelength_um"].values),
                "pressure_min_bar": float(aurora["pressure_bar"].min()),
                "pressure_max_bar": float(aurora["pressure_bar"].max()),
                "pressure_ascending": bool(np.all(np.diff(aurora["pressure_bar"].values) > 0)),
                "species_count": len(aurora_species),
                "species": aurora_species,
                "has_spurious_index_species": aurora_index_species,
                "index_species_min": float(np.nanmin(index_values)) if index_values.size else None,
                "index_species_max": float(np.nanmax(index_values)) if index_values.size else None,
                "chemistry_sum_min": float(np.nanmin(aurora_chemistry_sums)),
                "chemistry_sum_max": float(np.nanmax(aurora_chemistry_sums)),
                "chemistry_sum_without_index_min": float(np.nanmin(aurora_sums_without_index)),
                "chemistry_sum_without_index_max": float(np.nanmax(aurora_sums_without_index)),
                "compressed_variable_count": sum(
                    bool(var.encoding.get("zlib", False)) for var in aurora.variables.values()
                ),
                "wavelength_is_xarray_coordinate": "wavelength_um" in aurora.coords,
                "wavenumber_is_xarray_coordinate": "wavenumber_cm1" in aurora.coords,
            },
            "grid": {
                "axes": axes,
                "full_cartesian_product": full_product,
                "actual_files": len(parsed),
                "coverage_fraction": len(parsed) / full_product,
                "counts_by_teff": {str(int(key)): value for key, value in sorted(counts_by_teff.items())},
                "counts_by_gravity": {
                    str(int(key)): value for key, value in sorted(counts_by_gravity.items())
                },
                "unmatched_filenames": unmatched,
            },
            "comparison": {
                "shared_species": sorted(set(elf_species) & set(aurora_species)),
                "elf_only_species": sorted(set(elf_species) - set(aurora_species)),
                "aurora_only_species": sorted(set(aurora_species) - set(elf_species)),
                "spectral_point_ratio_elf_to_aurora": int(elf.sizes["wavelength"])
                / int(aurora.sizes["wavelength"]),
                "vertical_point_ratio_elf_to_aurora_levels": int(elf.sizes["pressure"])
                / int(aurora.sizes["level"]),
            },
            "schema_consistency": {
                "elf": sampled_schema_consistency(elf_files),
                "aurora": sampled_schema_consistency(aurora_files),
            },
            "patchy_file_exists": PATCHY_FILE.exists(),
        }

    (REPORT_DIR / "analysis.json").write_text(json.dumps(summary, indent=2) + "\n")
    (REPORT_DIR / "variable_inventory.json").write_text(
        json.dumps(variable_inventory, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
