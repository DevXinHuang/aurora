#!/bin/bash
#SBATCH --job-name=aurora_valid
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --array=0-1151
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.err

# HPC Validation Run — 1,152 representative models
#
# Pre-generate the manifest BEFORE submitting this script:
#
#   python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
#     --config roadrunner_egp/aurora_subneptune_grid/params/hpc_validation.yaml \
#     --out roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv
#
# Then submit:
#   sbatch roadrunner_egp/aurora_subneptune_grid/slurm/validation_aurora_subneptune_grid.slurm

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"

source ~/miniconda3/etc/profile.d/conda.sh
conda activate picaso4
source env/activate_roadrunner_picaso4.sh

MANIFEST="roadrunner_egp/aurora_subneptune_grid/manifests/hpc_validation_manifest.csv"

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: Manifest not found at $MANIFEST" >&2
  echo "Generate it first:" >&2
  echo "  python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \\" >&2
  echo "    --config roadrunner_egp/aurora_subneptune_grid/params/hpc_validation.yaml \\" >&2
  echo "    --out $MANIFEST" >&2
  exit 1
fi

python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest "$MANIFEST" \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name hpc_validation_aurora_subneptune
