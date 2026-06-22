#!/bin/bash
#SBATCH --job-name=aurora_patchy_T1000
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/patchy_T1000_%j.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/patchy_T1000_%j.err

set -euo pipefail

REPO_ROOT="${SLURM_SUBMIT_DIR}"
cd "${REPO_ROOT}"

BASE="roadrunner_egp/aurora_subneptune_grid"
mkdir -p "$BASE/logs" "$BASE/outputs/patchy_cloud" "$BASE/manifests" "$BASE/params/patchy_cloud"

# Activate the same Python env you use for Aurora NetCDF/xarray work.
if command -v micromamba >/dev/null 2>&1; then
  eval "$(micromamba shell hook --shell=bash)"
  micromamba activate picaso-env || micromamba activate picaso4 || true
elif command -v conda >/dev/null 2>&1; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate picaso-env || conda activate picaso4 || true
fi

INPUT_DECK="$BASE/params/patchy_cloud/run_SLGRID_T1000_g100_m+000_CO100_fsed3_frac50.scr"
CASE_ID="SLGRID_T1000_g100_m+000_CO100_fsed3_frac50"
RUN_DIR="$BASE/outputs/patchy_cloud/${CASE_ID}_work"
OUT_NC="$BASE/outputs/patchy_cloud/${CASE_ID}.nc"
mkdir -p "$RUN_DIR"

: "${SLGRID_EXE:?Set SLGRID_EXE to the mentor SLGRID/climate executable path, e.g. sbatch --export=ALL,SLGRID_EXE=/path/to/exe ...}"

cp "$INPUT_DECK" "$RUN_DIR/"
cd "$RUN_DIR"

echo "Running $CASE_ID with $SLGRID_EXE"
"$SLGRID_EXE" < "$(basename "$INPUT_DECK")" | tee "${CASE_ID}.stdout.log"

cd "$REPO_ROOT"
python "$BASE/scripts/slgrid_patchy_to_netcdf.py" \
  --case-id "$CASE_ID" \
  --input-deck "$INPUT_DECK" \
  --work-dir "$RUN_DIR" \
  --output-nc "$OUT_NC"

python - <<PY
import xarray as xr
from pathlib import Path
p = Path("$OUT_NC")
if not p.exists() or p.stat().st_size == 0:
    raise SystemExit(f"NetCDF output missing or empty: {p}")
ds = xr.open_dataset(p)
print("HPC PATCHY CASE OK")
print(ds)
print("Output:", p)
PY
