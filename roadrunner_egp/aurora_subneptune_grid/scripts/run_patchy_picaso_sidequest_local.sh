#!/usr/bin/env bash
set -euo pipefail

# Run from the aurora repo root with your .venv-picaso4 active.
BASE="roadrunner_egp/aurora_subneptune_grid"
MODEL="patchy_picaso_sidequest_components"
CONFIG="$BASE/params/patchy_picaso_sidequest.yaml"
MANIFEST="$BASE/manifests/patchy_picaso_sidequest_manifest.csv"
PATCHY_OUT="$BASE/outputs/patchy_cloud/PICASO_T1000_g100_m+000_CO100_fsed3_frac50.patchy_picaso.nc"

export PYTHONPATH="$BASE/src:roadrunner_egp:${PYTHONPATH:-}"

python "$BASE/scripts/make_manifest.py" \
  --config "$CONFIG" \
  --out "$MANIFEST"

# Actually run PICASO via the existing Roadrunner/Aurora framework. No --dry-run here.
python "$BASE/scripts/run_grid_chunk.py" \
  --manifest "$MANIFEST" \
  --array-index 0 \
  --model-name "$MODEL" \
  --overwrite

python "$BASE/scripts/run_grid_chunk.py" \
  --manifest "$MANIFEST" \
  --array-index 1 \
  --model-name "$MODEL" \
  --overwrite

python "$BASE/scripts/combine_patchy_picaso_components.py" \
  --manifest "$MANIFEST" \
  --hole-fraction 0.5 \
  --output-nc "$PATCHY_OUT" \
  --overwrite

python - <<PY
import xarray as xr
from pathlib import Path
p = Path("$PATCHY_OUT")
assert p.exists() and p.stat().st_size > 0, p
with xr.open_dataset(p) as ds:
    print("PATCHY PICASO LOCAL RUN OK")
    print("file:", p)
    print("schema:", ds.attrs.get("schema_name"))
    print("model:", ds.attrs.get("model_name"))
    print("run_type:", ds.attrs.get("run_type"))
    print("hole_fraction:", ds.attrs.get("cloud_hole_fraction"))
    print("cloud_fraction_var:", float(ds["cloud_fraction"].values) if "cloud_fraction" in ds else "missing")
    print("wavelength points:", ds.sizes.get("wavelength"))
    print("has fpfs:", "reflected_planet_star_flux_ratio" in ds)
PY
