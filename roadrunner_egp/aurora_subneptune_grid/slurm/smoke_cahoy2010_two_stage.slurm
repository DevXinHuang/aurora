#!/bin/bash
#SBATCH --job-name=cahoy_smoke
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/cahoy_smoke_%j.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/cahoy_smoke_%j.err

# One Cahoy climate group (Jupiter 1x @ 0.8 AU) — run before the full 16+304 grid.

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"

MODEL="aurora_cahoy2010_replication_v0"
GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"
MANIFEST="$GRID_ROOT/manifests/${MODEL}_manifest.csv"

export AURORA_FORCE_CONDA=1
module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_aurora_picaso4_job.sh

if [ ! -f "$MANIFEST" ] || ! head -1 "$MANIFEST" | tr ',' '\n' | grep -qx climate_group_index; then
  python "$GRID_ROOT/scripts/make_cahoy2010_manifest.py" --out "$MANIFEST"
fi

python "$GRID_ROOT/scripts/run_climate_cache_chunk.py" \
  --manifest "$MANIFEST" \
  --climate-group-index 0 \
  --ck-root "$PICASO_CK_ROOT" \
  --overwrite

CACHE="$GRID_ROOT/outputs/$MODEL/climate_cache/climate_00.npz"
CASE="$GRID_ROOT/outputs/$MODEL/climate_cache/climate_00_case.pkl"
if [ ! -f "$CACHE" ] || [ ! -f "$CASE" ]; then
  echo "ERROR: smoke failed — cache not written: $CACHE / $CASE" >&2
  exit 1
fi

python "$GRID_ROOT/scripts/run_spectrum_from_cache_chunk.py" \
  --manifest "$MANIFEST" \
  --array-index 0 \
  --model-name "$MODEL" \
  --ck-root "$PICASO_CK_ROOT" \
  --overwrite

NC="$GRID_ROOT/outputs/$MODEL/nc/run_000000.nc"
if [ ! -f "$NC" ]; then
  echo "ERROR: smoke failed — spectrum NC not written: $NC" >&2
  exit 1
fi

echo "SMOKE OK: $CACHE and $NC"
