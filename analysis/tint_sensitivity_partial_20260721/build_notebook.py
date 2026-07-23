from __future__ import annotations

from pathlib import Path

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
NOTEBOOK = OUT / "tint_sensitivity_partial_analysis.ipynb"

SNAPSHOT_FILES = [
    "00_k2_18b_observed_tint025_cloud_free_mh001x.nc",
    "01_k2_18b_observed_tint025_cloud_free_mh100x.nc",
    "02_k2_18b_observed_tint025_fully_cloudy_virga_mh001x.nc",
    "03_k2_18b_observed_tint025_fully_cloudy_virga_mh100x.nc",
    "04_k2_18b_observed_tint050_cloud_free_mh001x.nc",
    "05_k2_18b_observed_tint050_cloud_free_mh100x.nc",
    "06_k2_18b_observed_tint050_fully_cloudy_virga_mh001x.nc",
    "07_k2_18b_observed_tint050_fully_cloudy_virga_mh100x.nc",
    "08_k2_18b_observed_tint100_cloud_free_mh001x.nc",
    "09_k2_18b_observed_tint100_cloud_free_mh100x.nc",
    "10_k2_18b_observed_tint100_fully_cloudy_virga_mh001x.nc",
    "11_k2_18b_observed_tint100_fully_cloudy_virga_mh100x.nc",
    "12_gj_1214b_low_tint025_cloud_free_mh001x.nc",
    "13_gj_1214b_low_tint025_cloud_free_mh100x.nc",
    "14_gj_1214b_low_tint025_fully_cloudy_virga_mh001x.nc",
    "15_gj_1214b_low_tint025_fully_cloudy_virga_mh100x.nc",
    "16_gj_1214b_low_tint050_cloud_free_mh001x.nc",
    "17_gj_1214b_low_tint050_cloud_free_mh100x.nc",
    "18_gj_1214b_low_tint050_fully_cloudy_virga_mh001x.nc",
    "19_gj_1214b_low_tint050_fully_cloudy_virga_mh100x.nc",
    "20_gj_1214b_low_tint100_cloud_free_mh001x.nc",
    "21_gj_1214b_low_tint100_cloud_free_mh100x.nc",
    "22_gj_1214b_low_tint100_fully_cloudy_virga_mh001x.nc",
    "23_gj_1214b_low_tint100_fully_cloudy_virga_mh100x.nc",
    "24_gj_1214b_observed_tint025_cloud_free_mh001x.nc",
    "25_gj_1214b_observed_tint025_cloud_free_mh100x.nc",
]


def code(source: str):
    return nbf.v4.new_code_cell(source.strip())


def markdown(source: str):
    return nbf.v4.new_markdown_cell(source.strip())


nb = nbf.v4.new_notebook()
nb["metadata"]["kernelspec"] = {
    "display_name": "Python 3 (PICASO 4)",
    "language": "python",
    "name": "picaso4",
}
nb["metadata"]["language_info"] = {"name": "python", "version": "3.12"}

nb["cells"] = [
    markdown(
        """
# PICASO Tint-sensitivity partial analysis

## tl;dr

- This frozen snapshot contains **26/36 valid NetCDF models**: both 255 K cases are complete (12 each), while the 500 K case has only two clear, Tint=25 K models.
- Across converged endpoint pairs in the complete 255 K cases, changing Tint from 25 to 100 K changes transmission spectra by only **1.6–9.3 ppm RMS**. Metallicity, clouds, gravity, and Teq have larger effects in the current sample.
- Seven saved models have `climate_converged=false`; they are finite and restartable but remain provisional. Thermal planet/star ratios are excluded because a dimensional inconsistency was found in the installed PICASO climate stellar-flux path.
"""
    ),
    markdown(
        """
## Context & Methods

This is a technical, frozen-snapshot companion to the partial-results report. The unit of analysis is one unique case × Tint × cloud × metallicity model. Transmission modulation is peak-to-trough transit depth over 0.6–15 µm, in ppm. Tint sensitivity is the wavelength-wise RMS difference between Tint=100 K and Tint=25 K spectra for otherwise identical models.

### Key Assumptions

- Only the explicit file list below is analyzed, so ongoing Slurm tasks cannot change denominators.
- `climate_converged=false` is not treated as a file failure, but claims depending on such models are flagged provisional.
- Thermal ratios are retained in the source files but excluded from scientific comparisons pending correction and rerun.
"""
    ),
    code(
        f"""
from pathlib import Path
import json
import re
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path({str(ROOT)!r})
OUT = Path({str(OUT)!r})
OUTPUT_DIR = ROOT / "outputs" / "tint_sensitivity_36"
LOG_DIR = ROOT / "logs" / "tint_sensitivity_36"
SNAPSHOT_UTC = "2026-07-21T17:21:30Z"
SNAPSHOT_FILES = {SNAPSHOT_FILES!r}
paths = [OUTPUT_DIR / name for name in SNAPSHOT_FILES]
assert len(paths) == 26 and all(path.is_file() for path in paths)
"""
    ),
    markdown("## Data\n\n### 1. Load and profile the frozen NetCDF cohort"),
    code(
        """
rows = []
spectra = {}
for path in paths:
    with xr.open_dataset(path) as ds:
        ds.load()
        wave = ds.wavelength_um.values.astype(float)
        transmission = ds.transmission_depth.values.astype(float)
        albedo = ds.geometric_albedo.values.astype(float)
        pressure = ds.pressure_bar.values.astype(float)
        temperature = ds.temperature_k.values.astype(float)
        run_id = ds.attrs["run_id"]
        case_id = run_id.split("_tint")[0].split("_", 1)[1]
        cloud = "cloudy" if float(ds.cloud_fraction.item()) == 1.0 else "clear"

        assert np.all(np.isfinite(transmission))
        assert np.all(np.isfinite(albedo))
        assert np.all(ds.kzz_cm2_s_profile.values == 1e10)
        assert int(ds.quench_enabled.item()) == int(ds.quench_applied.item()) == 1
        assert int(ds.diseq_chem.item()) == 1
        assert int(ds.self_consistent_kzz.item()) == 0

        rows.append({
            "run_index": int(ds.run_index.item()),
            "run_id": run_id,
            "case_id": case_id,
            "tint_k": float(ds.tint_k.item()),
            "metallicity_xsolar": float(ds.metallicity_xsolar.item()),
            "cloud": cloud,
            "climate_converged": bool(ds.climate_converged.item()),
            "transmission_modulation_ppm": float(np.ptp(transmission) * 1e6),
            "visible_albedo_median": float(np.median(albedo[(wave >= 0.6) & (wave <= 1.0)])),
            "temperature_1bar_k": float(np.interp(0.0, np.log10(pressure), temperature)),
            "max_quench_difference_dex": float(ds.max_quench_log10_difference.item()),
            "pressure_levels": int(pressure.size),
            "pressure_max_bar": float(pressure.max()),
            "runtime_seconds": float(ds.runtime_seconds.item()),
        })
        spectra[int(ds.run_index.item())] = transmission

models = pd.DataFrame(rows).sort_values("run_index").reset_index(drop=True)
models.to_csv(OUT / "model_summary.csv", index=False)
models.head(10)
"""
    ),
    markdown("### 2. Confirm coverage, convergence, and uniqueness"),
    code(
        """
expected_by_case = {
    "k2_18b_observed": 12,
    "gj_1214b_low": 12,
    "gj_1214b_observed": 12,
}
coverage = (
    models.groupby("case_id", as_index=False)
    .agg(valid_models=("run_index", "size"), converged_models=("climate_converged", "sum"))
)
coverage["expected_models"] = coverage.case_id.map(expected_by_case)
coverage["coverage_rate"] = coverage.valid_models / coverage.expected_models
coverage["nonconverged_models"] = coverage.valid_models - coverage.converged_models
coverage.to_csv(OUT / "coverage.csv", index=False)

assert models.run_id.nunique() == len(models) == 26
assert models.run_index.nunique() == 26
assert models.run_index.min() == 0 and models.run_index.max() == 25
coverage
"""
    ),
    markdown("## Results\n\n### 3. Quantify Tint sensitivity on complete endpoint pairs"),
    code(
        """
pair_rows = []
for keys, group in models.groupby(["case_id", "cloud", "metallicity_xsolar"]):
    by_tint = group.set_index("tint_k")
    if not {25.0, 100.0}.issubset(by_tint.index):
        continue
    low = by_tint.loc[25.0]
    high = by_tint.loc[100.0]
    delta = spectra[int(high.run_index)] - spectra[int(low.run_index)]
    pair_rows.append({
        "case_id": keys[0],
        "cloud": keys[1],
        "metallicity_xsolar": keys[2],
        "pair_label": f"{keys[0].replace('_', ' ')} | {keys[1]} | {keys[2]:g}x",
        "rms_transmission_change_ppm": float(np.sqrt(np.mean(delta**2)) * 1e6),
        "maximum_transmission_change_ppm": float(np.max(np.abs(delta)) * 1e6),
        "temperature_1bar_change_k": float(high.temperature_1bar_k - low.temperature_1bar_k),
        "both_endpoints_converged": bool(low.climate_converged and high.climate_converged),
    })

tint_pairs = pd.DataFrame(pair_rows).sort_values("rms_transmission_change_ppm", ascending=False)
tint_pairs.to_csv(OUT / "tint_sensitivity.csv", index=False)
tint_pairs
"""
    ),
    code(
        """
plot_rows = tint_pairs[tint_pairs.both_endpoints_converged].sort_values("rms_transmission_change_ppm")
fig, ax = plt.subplots(figsize=(9, 4.8))
ax.barh(plot_rows.pair_label, plot_rows.rms_transmission_change_ppm, color="#2563A6")
ax.set_xlabel("RMS transmission change, Tint 100 K minus 25 K (ppm)")
ax.set_title("Tint sensitivity for converged endpoint pairs")
ax.grid(axis="x", color="#D9DEE5", linewidth=0.7)
ax.set_axisbelow(True)
fig.tight_layout()
plt.show()
"""
    ),
    markdown("### 4. Compare gravity, metallicity, clouds, and the provisional hot case"),
    code(
        """
case_summary = (
    models.groupby("case_id", as_index=False)
    .agg(
        valid_models=("run_index", "size"),
        converged_models=("climate_converged", "sum"),
        median_transmission_modulation_ppm=("transmission_modulation_ppm", "median"),
        minimum_transmission_modulation_ppm=("transmission_modulation_ppm", "min"),
        maximum_transmission_modulation_ppm=("transmission_modulation_ppm", "max"),
        median_temperature_1bar_k=("temperature_1bar_k", "median"),
    )
)
case_summary.to_csv(OUT / "case_summary.csv", index=False)
case_summary
"""
    ),
    code(
        """
cloud_effects = models.pivot_table(
    index=["case_id", "tint_k", "metallicity_xsolar"],
    columns="cloud",
    values=["transmission_modulation_ppm", "visible_albedo_median", "climate_converged"],
    aggfunc="first",
).dropna()
cloud_effects["cloud_change_transmission_ppm"] = (
    cloud_effects[("transmission_modulation_ppm", "cloudy")]
    - cloud_effects[("transmission_modulation_ppm", "clear")]
)
cloud_effects["cloud_to_clear_albedo_ratio"] = (
    cloud_effects[("visible_albedo_median", "cloudy")]
    / cloud_effects[("visible_albedo_median", "clear")]
)
cloud_effects.reset_index().to_csv(OUT / "cloud_effects.csv", index=False)
cloud_effects[["cloud_change_transmission_ppm", "cloud_to_clear_albedo_ratio"]]
"""
    ),
    markdown("### 5. Inventory failed attempts by root cause"),
    code(
        """
failure_rows = []
for path in sorted(LOG_DIR.glob("*.err")):
    text = path.read_text(errors="replace")
    if "Traceback" not in text:
        continue
    if "missing required column 'kz'" in text:
        category = "Returned profile omitted kz"
        stage = "preflight"
    elif "transit_depth" in text and ("non-finite" in text or "finite native samples" in text):
        category = "Planet radius unavailable to transmission"
        stage = "preflight"
    elif "mixing across Pressure Ranges" in text:
        category = "Quench point below pressure grid"
        stage = "production"
    elif "particles would need to be smaller than gas atoms" in text:
        category = "Virga particle root below physical floor"
        stage = "corrected production"
    else:
        category = "Other"
        stage = "unknown"
    job_match = re.match(r"(?P<job>\\d+)_(?P<index>\\d+)\\.err", path.name)
    failure_rows.append({
        "log_file": path.name,
        "job_id": int(job_match.group("job")) if job_match else None,
        "run_index": int(job_match.group("index")) if job_match else None,
        "stage": stage,
        "category": category,
    })

failures = pd.DataFrame(failure_rows)
failures.to_csv(OUT / "failure_inventory.csv", index=False)
failure_summary = (
    failures.groupby(["stage", "category"], as_index=False)
    .agg(failed_attempt_logs=("log_file", "size"), unique_run_indices=("run_index", "nunique"))
    .sort_values("failed_attempt_logs", ascending=False)
)
failure_summary.to_csv(OUT / "failure_summary.csv", index=False)
failure_summary
"""
    ),
    markdown(
        """
## Limitations, uncertainty, and robustness checks

- The 500 K case is incomplete, so its two clear Tint=25 K points cannot establish Tint or cloud sensitivity.
- Seven files are finite and schema-valid but have `climate_converged=false`; they should not be used for final inference until convergence is improved or independently justified.
- Failed-attempt counts refer to traceback log files, not unique scientific models. Several models were retried during implementation diagnostics.
- Thermal planet/star ratios are excluded. The installed climate stellar path integrates stellar flux per native bin before dividing a planet flux density by it, producing a dimensional mismatch and implausibly large ratios.
"""
    ),
    markdown(
        """
## Takeaways

1. Tint is a secondary transmission driver in the two complete 255 K cases: converged 25→100 K endpoint differences span 1.6–9.3 ppm RMS.
2. Lower gravity increases the median transmission modulation: GJ 1214 b low is about 23% larger than K2-18 b across the complete grids.
3. At 100× solar, clouds suppress transmission modulation by roughly 40–62 ppm in the converged comparisons and raise visible geometric albedo by about 34–84×.
4. The current 500 K clear points show much larger modulation (293–496 ppm), but this is provisional until the remaining hot models finish and the thermal-ratio defect is corrected.
"""
    ),
]

nbf.write(nb, NOTEBOOK)
print(NOTEBOOK)
