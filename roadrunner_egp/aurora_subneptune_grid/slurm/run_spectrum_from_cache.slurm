#!/bin/bash
#SBATCH --job-name=aurora_spec
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-0%12
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.err

# Stage 2 — reflected spectrum from cached climate (one array task per manifest row).
# Submit via scripts/submit_two_stage_grid.sh after stage 1 completes.

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"

MODEL="${MODEL:?set MODEL}"
MANIFEST="${MANIFEST:?set MANIFEST}"
GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"

export AURORA_FORCE_CONDA=1
module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_aurora_picaso4_job.sh

python "$GRID_ROOT/scripts/run_spectrum_from_cache_chunk.py" \
  --manifest "$MANIFEST" \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name "$MODEL" \
  --ck-root "$PICASO_CK_ROOT" \
  --overwrite
