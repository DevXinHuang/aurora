#!/bin/bash
# LEGACY exploratory weekend shard — not the production grid runner.
# For science grids use the two-stage workflow:
#   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_two_stage_grid.sh "$(pwd)" aurora_subneptune_v0
#SBATCH --job-name=aurora_weekend
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-799%20
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=04:00:00
#SBATCH --output=logs/weekend_%A_%a.out
#SBATCH --error=logs/weekend_%A_%a.err

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"
mkdir -p logs outputs/weekend_nc

export PYTHONPATH="roadrunner_egp/aurora_subneptune_grid/src:roadrunner_egp"
export PICASO_CK_ROOT="/home/u11/danielxinhuang/Documents/aurora/picaso4_reference/opacities"


module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_roadrunner_picaso4.sh

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

python scripts/run_sharded_manifest.py \
  --manifest manifests/weekend_manifest.csv \
  --output-dir outputs/weekend_nc \
  --shard-id "${SLURM_ARRAY_TASK_ID}" \
  --n-shards 800 \
  --atmosphere-source picaso_climate \
  --picaso-ck-root "$PICASO_CK_ROOT"
