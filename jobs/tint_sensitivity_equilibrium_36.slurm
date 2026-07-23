#!/bin/bash
#SBATCH --job-name=aurora_tint_eq36
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-35%4
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=08:00:00
#SBATCH --output=logs/tint_sensitivity_equilibrium_36/%A_%a.out
#SBATCH --error=logs/tint_sensitivity_equilibrium_36/%A_%a.err

set -euo pipefail

REPO_ROOT="${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"
cd "$REPO_ROOT"

source .venv-picaso4/bin/activate
source env/activate_roadrunner_picaso4.sh >/dev/null
export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT/roadrunner_egp${PYTHONPATH:+:$PYTHONPATH}"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export ROADRUNNER_REQUIRE_VIRGA=1

python -m aurora_grid.tint \
  --config params/tint_sensitivity_equilibrium_36.yaml \
  run-one --index "$SLURM_ARRAY_TASK_ID"
