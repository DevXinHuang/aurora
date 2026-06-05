#!/bin/bash
#SBATCH --job-name=aurora_subnep
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --array=0-99
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/%x_%A_%a.err

# Full grid: submit in batches to stay within Slurm MaxArraySize.
# Check your limit:  scontrol show config | grep MaxArraySize
#
# Example batched submission (from repo root):
#   for start in $(seq 0 1000 460799); do
#     end=$((start + 999))
#     [ $end -gt 460799 ] && end=460799
#     sbatch --array=${start}-${end}%100 \
#       roadrunner_egp/aurora_subneptune_grid/slurm/run_aurora_subneptune_grid.slurm
#   done

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"

source ~/miniconda3/etc/profile.d/conda.sh
conda activate picaso4
source env/activate_roadrunner_picaso4.sh

MANIFEST="roadrunner_egp/aurora_subneptune_grid/manifests/aurora_subneptune_v0_manifest.csv"

if [ ! -f "$MANIFEST" ]; then
  python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
    --config roadrunner_egp/aurora_subneptune_grid/params/aurora_subneptune_v0.yaml \
    --out "$MANIFEST"
fi

python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest "$MANIFEST" \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name aurora_subneptune_v0
