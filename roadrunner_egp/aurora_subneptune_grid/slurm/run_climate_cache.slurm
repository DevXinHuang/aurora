#!/bin/bash
#SBATCH --job-name=aurora_clim
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-0%6
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=5G
#SBATCH --time=03:00:00
#SBATCH --output=/groups/tdrobin/dhuang/aurora_subneptune_v1_dhuang/logs/%x_%A_%a.out
#SBATCH --error=/groups/tdrobin/dhuang/aurora_subneptune_v1_dhuang/logs/%x_%A_%a.err

# Stage 1 — climate convergence (one array task per climate_group_index).
# Submit via scripts/submit_two_stage_grid.sh (sets MODEL, MANIFEST, array range).

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"

MODEL="${MODEL:?set MODEL}"
MANIFEST="${MANIFEST:?set MANIFEST}"
GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"

export NUMBA_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/aurora_numba_cache_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$NUMBA_CACHE_DIR"

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMBA_NUM_THREADS=1

export AURORA_FORCE_CONDA=1
module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_aurora_picaso4_job.sh

CLIMATE_ARGS=(--manifest "$MANIFEST")
if [[ -n "${CLIMATE_INDEX_MAP:-}" ]]; then
  CLIMATE_ARGS+=(--climate-index-map "$CLIMATE_INDEX_MAP" --array-task-id "${SLURM_ARRAY_TASK_ID}")
else
  CLIMATE_ARGS+=(--climate-group-index "${SLURM_ARRAY_TASK_ID}")
fi

python "$GRID_ROOT/scripts/run_climate_cache_chunk.py" \
  "${CLIMATE_ARGS[@]}" \
  --ck-root "$PICASO_CK_ROOT" \
  --overwrite
