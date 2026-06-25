#!/bin/bash
#SBATCH --job-name=aurora_fact_clim
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --array=0-15
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.err

# Factorized climate stage — 16 Cahoy validation climates
#
# Generate manifests before submitting:
#
#   python roadrunner_egp/aurora_subneptune_grid/scripts/make_factorized_manifests.py \
#     --config roadrunner_egp/aurora_subneptune_grid/params/aurora_cahoy_exact_304_factorized.yaml \
#     --out-dir roadrunner_egp/aurora_subneptune_grid/manifests
#
# Submit climate array, then spectrum array with dependency:
#
#   CLIMATE_JOB=$(sbatch --parsable slurm/run_aurora_factorized_climate.slurm)
#   sbatch --dependency=afterok:${CLIMATE_JOB} slurm/run_aurora_factorized_spectrum.slurm

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"

if ! command -v module >/dev/null 2>&1; then
  if [ -f /etc/profile.d/modules.sh ]; then
    source /etc/profile.d/modules.sh
  fi
fi

module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_roadrunner_picaso4.sh

export PYTHONPATH="roadrunner_egp/aurora_subneptune_grid/src:roadrunner_egp"
export PICASO_CK_ROOT="/home/u11/danielxinhuang/Documents/aurora/picaso4_reference/opacities"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

MANIFEST="roadrunner_egp/aurora_subneptune_grid/manifests/aurora_cahoy_exact_304_climate_manifest.csv"

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: Climate manifest not found at $MANIFEST" >&2
  echo "Generate manifests first with make_factorized_manifests.py" >&2
  exit 1
fi

python roadrunner_egp/aurora_subneptune_grid/scripts/run_climate_chunk.py \
  --manifest "$MANIFEST" \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name aurora_cahoy_exact_304
