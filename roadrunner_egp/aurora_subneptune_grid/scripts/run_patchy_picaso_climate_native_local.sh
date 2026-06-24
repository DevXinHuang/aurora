#!/usr/bin/env bash
set -euo pipefail

# Run from the aurora repo root. Uses .venv-picaso4 on Mac or conda/micromamba on HPC.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=/dev/null
source "${REPO_ROOT}/env/activate_aurora_picaso4_job.sh"

CONFIG="roadrunner_egp/aurora_subneptune_grid/params/patchy_picaso_climate_native.yaml"
MANIFEST="roadrunner_egp/aurora_subneptune_grid/manifests/patchy_picaso_climate_native_manifest.csv"

python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config "$CONFIG" \
  --out "$MANIFEST"

python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest "$MANIFEST" \
  --array-index 0 \
  --model-name patchy_picaso_climate_native \
  --use-picaso-climate \
  --picaso-ck-root "$PICASO_CK_ROOT" \
  --overwrite

python - <<'PY'
import json
import xarray as xr

p = "roadrunner_egp/aurora_subneptune_grid/outputs/patchy_picaso_climate_native/nc/run_000000.nc"
ds = xr.open_dataset(p)
grid_params = ds.attrs.get("grid_params", {})
if isinstance(grid_params, str):
    grid_params = json.loads(grid_params)
meta = grid_params.get("picaso_metadata", {})
if meta.get("dry_run"):
    raise SystemExit("ERROR: output is a dry-run toy spectrum, not a real PICASO climate run.")
print(ds)
print("PATCHY PICASO CLIMATE NATIVE LOCAL RUN OK")
print("file:", p)
print("schema:", ds.attrs.get("schema_name"))
print("model:", ds.attrs.get("model_name"))
print("cloud attrs:", ds.attrs.get("cld_params"))
print("cloud_fraction var:", float(ds.cloud_fraction.values))
print("max fpfs:", float(ds.reflected_planet_star_flux_ratio.max()))
print("max cloud opd:", float(ds.cloud_optical_depth.max()))
print("picaso metadata:", meta)
print("runtime_seconds:", float(ds.runtime_seconds.values))
PY
