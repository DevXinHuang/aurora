#!/usr/bin/env bash
set -euo pipefail

CONFIG="roadrunner_egp/aurora_subneptune_grid/params/patchy_picaso_climate_native.yaml"
MANIFEST="roadrunner_egp/aurora_subneptune_grid/manifests/patchy_picaso_climate_native_manifest.csv"
OUT="roadrunner_egp/aurora_subneptune_grid/outputs/patchy_picaso_climate_native/nc/run_000000.nc"

python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config "$CONFIG" \
  --out "$MANIFEST"

python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest "$MANIFEST" \
  --array-index 0 \
  --model-name patchy_picaso_climate_native \
  --use-picaso-climate \
  --overwrite

python - <<'PY'
import xarray as xr
p = "roadrunner_egp/aurora_subneptune_grid/outputs/patchy_picaso_climate_native/nc/run_000000.nc"
ds = xr.open_dataset(p)
print(ds)
print("PATCHY PICASO CLIMATE NATIVE LOCAL RUN OK")
print("file:", p)
print("schema:", ds.attrs.get("schema_name"))
print("model:", ds.attrs.get("model_name"))
print("cloud attrs:", ds.attrs.get("cld_params"))
print("cloud_fraction var:", float(ds.cloud_fraction.values))
print("max fpfs:", float(ds.reflected_planet_star_flux_ratio.max()))
print("max cloud opd:", float(ds.cloud_optical_depth.max()))
print("picaso metadata:", ds.attrs.get("grid_params"))
PY
