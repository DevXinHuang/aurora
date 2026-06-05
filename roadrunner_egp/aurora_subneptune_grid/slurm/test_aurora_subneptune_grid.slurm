#!/bin/bash
#SBATCH --job-name=aurora_test
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --array=0-5
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.err

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"

source ~/miniconda3/etc/profile.d/conda.sh
conda activate picaso4
source env/activate_roadrunner_picaso4.sh

python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config roadrunner_egp/aurora_subneptune_grid/params/smoke_test.yaml \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_manifest.csv

python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_manifest.csv \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name smoke_test_aurora_subneptune
