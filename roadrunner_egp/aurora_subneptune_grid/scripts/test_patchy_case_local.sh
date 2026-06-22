#!/usr/bin/env bash
set -euo pipefail

# Run this from the aurora repo root after copying the package files into the repo.
CASE_ID="SLGRID_T1000_g100_m+000_CO100_fsed3_frac50"
BASE="roadrunner_egp/aurora_subneptune_grid"
INPUT_DECK="$BASE/params/patchy_cloud/run_SLGRID_T1000_g100_m+000_CO100_fsed3_frac50.scr"
WORK_DIR="$BASE/outputs/patchy_cloud/${CASE_ID}_local_smoke"
OUT_NC="$BASE/outputs/patchy_cloud/${CASE_ID}.local_smoke.nc"

mkdir -p "$WORK_DIR" "$BASE/outputs/patchy_cloud"

python "$BASE/scripts/slgrid_patchy_to_netcdf.py" \
  --case-id "$CASE_ID" \
  --input-deck "$INPUT_DECK" \
  --work-dir "$WORK_DIR" \
  --output-nc "$OUT_NC"

python - <<PY
import xarray as xr
from pathlib import Path
p = Path("$OUT_NC")
assert p.exists() and p.stat().st_size > 0, f"missing or empty: {p}"
ds = xr.open_dataset(p)
print("LOCAL PATCHY SMOKE TEST OK")
print("file:", p)
print("cloud_fraction:", float(ds.cloud_fraction.values[0]))
print("cloud_hole_fraction:", float(ds.cloud_hole_fraction.values[0]))
print("fsed:", float(ds.fsed.values[0]))
print("Tint:", float(ds.internal_temperature_k.values[0]))
print("logg_cgs:", float(ds.logg_cgs.values[0]))
print("species:", ds.attrs.get("condensible_species"))
PY
