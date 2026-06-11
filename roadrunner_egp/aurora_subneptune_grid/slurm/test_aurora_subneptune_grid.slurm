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

module load anaconda
conda activate picaso4
source env/activate_roadrunner_picaso4.sh

# Only task 0 generates the manifest; others wait for it
MANIFEST="roadrunner_egp/aurora_subneptune_grid/manifests/smoke_test_manifest.csv"
if [ "${SLURM_ARRAY_TASK_ID}" -eq 0 ]; then
  python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
    --config roadrunner_egp/aurora_subneptune_grid/params/smoke_test.yaml \
    --out "$MANIFEST"
else
  # Wait for task 0 to create the manifest (max 60s)
  for i in $(seq 1 60); do
    [ -f "$MANIFEST" ] && break
    sleep 1
  done
  if [ ! -f "$MANIFEST" ]; then
    echo "ERROR: Manifest not created by task 0 after 60s" >&2
    exit 1
  fi
fi

python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest "$MANIFEST" \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name smoke_test_aurora_subneptune
