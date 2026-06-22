#!/bin/bash
#SBATCH --job-name=patchy_native
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=06:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/patchy_native_%j.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/patchy_native_%j.err

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"

source ~/.bashrc || true
conda activate picaso4 || conda activate picaso-env || true

export PYTHONPATH="$PWD/roadrunner_egp/aurora_subneptune_grid/src:$PWD/roadrunner_egp:${PYTHONPATH:-}"
export ROADRUNNER_PICASO_VIRGA_CONDENSATES="MgSiO3,Mg2SiO4,Na2S,KCl,MnS,ZnS"
export ROADRUNNER_REQUIRE_VIRGA=1
export PICASO_CK_ROOT="$PWD/picaso4_reference/opacities"

mkdir -p roadrunner_egp/aurora_subneptune_grid/logs

python roadrunner_egp/aurora_subneptune_grid/scripts/make_manifest.py \
  --config roadrunner_egp/aurora_subneptune_grid/params/patchy_picaso_climate_native.yaml \
  --out roadrunner_egp/aurora_subneptune_grid/manifests/patchy_picaso_climate_native_manifest.csv

python roadrunner_egp/aurora_subneptune_grid/scripts/run_grid_chunk.py \
  --manifest roadrunner_egp/aurora_subneptune_grid/manifests/patchy_picaso_climate_native_manifest.csv \
  --array-index 0 \
  --model-name patchy_picaso_climate_native \
  --use-picaso-climate \
  --picaso-ck-root "$PICASO_CK_ROOT" \
  --overwrite
