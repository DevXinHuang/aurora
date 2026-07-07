#!/bin/bash
#SBATCH --job-name=aurora_ctl
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=9-23:00:00
#SBATCH --output=/groups/tdrobin/dhuang/aurora_subneptune_v1_dhuang/controller/slurm_%j.out
#SBATCH --error=/groups/tdrobin/dhuang/aurora_subneptune_v1_dhuang/controller/slurm_%j.err

set -eo pipefail

REPO_ROOT="${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"
cd "$REPO_ROOT"

RUN_ROOT="/groups/tdrobin/dhuang/aurora_subneptune_v1_dhuang"
mkdir -p "$RUN_ROOT/controller"

python roadrunner_egp/aurora_subneptune_grid/scripts/submit_climate_wave_controller.py \
  --repo-root "$REPO_ROOT" \
  --wave-dir "$RUN_ROOT/manifests/climate_waves" \
  --output-root "$RUN_ROOT" \
  --model "aurora_subneptune_v1_dhuang" \
  --start-wave "${START_WAVE:-0}" \
  --end-wave "${END_WAVE:-180}" \
  --throttle "${CLIMATE_WAVE_THROTTLE:-999}" \
  --poll-seconds "${CLIMATE_WAVE_POLL_SECONDS:-300}" \
  --post-wave-sleep-seconds "${CLIMATE_WAVE_POST_SLEEP_SECONDS:-30}" \
  --max-retries "${CLIMATE_WAVE_MAX_RETRIES:-2}" \
  --adopt-first-job-id "${ADOPT_FIRST_JOB_ID:-}" \
  --state-path "$RUN_ROOT/controller/state.json" \
  --log-path "$RUN_ROOT/controller/controller.log" \
  --failed-indices-path "$RUN_ROOT/controller/failed_climate_indices.csv"
