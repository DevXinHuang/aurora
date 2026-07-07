#!/bin/bash
#SBATCH --job-name=aurora_clim
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-0%6
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.err

# Stage 1 — climate convergence (one array task per climate_group_index).
# Submit via scripts/submit_two_stage_grid.sh (sets MODEL, MANIFEST, array range).

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"

MODEL="${MODEL:?set MODEL}"
MANIFEST="${MANIFEST:?set MANIFEST}"
GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"

mkdir -p "$GRID_ROOT/logs"

export NUMBA_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/aurora_numba_cache_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$NUMBA_CACHE_DIR"

export AURORA_FORCE_CONDA=1
module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_aurora_picaso4_job.sh

python "$GRID_ROOT/scripts/run_climate_cache_chunk.py" \
  --manifest "$MANIFEST" \
  --climate-group-index "${SLURM_ARRAY_TASK_ID}" \
  --ck-root "$PICASO_CK_ROOT" \
  --overwrite
