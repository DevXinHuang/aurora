#!/bin/bash
#SBATCH --job-name=cahoy_sp304
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-303%12
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/aurora_cahoy2010_replication_v0/spectrum_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/aurora_cahoy2010_replication_v0/spectrum_%A_%a.err

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"

MODEL="aurora_cahoy2010_replication_v0"
GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"
MANIFEST="$GRID_ROOT/manifests/${MODEL}_manifest.csv"

mkdir -p "$GRID_ROOT/logs/$MODEL"
mkdir -p "$GRID_ROOT/outputs/$MODEL/nc"

export AURORA_FORCE_CONDA=1
module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_aurora_picaso4_job.sh

if [ ! -f "$MANIFEST" ] || ! head -1 "$MANIFEST" | tr ',' '\n' | grep -qx climate_group_index; then
  python "$GRID_ROOT/scripts/make_cahoy2010_manifest.py" --config "$GRID_ROOT/params/${MODEL}.yaml" --out "$MANIFEST"
fi

python "$GRID_ROOT/scripts/run_spectrum_from_cache_chunk.py" \
  --manifest "$MANIFEST" \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name "$MODEL" \
  --ck-root "$PICASO_CK_ROOT" \
  --overwrite
