#!/bin/bash
# DEPRECATED — superseded by aurora_cahoy2010_replication_v0 two-stage workflow.
# This 768-case job re-runs PICASO climate for every phase. Use instead:
#   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh
echo "ERROR: Obsolete single-stage Cahoy solar climate grid." >&2
echo "Use: bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh" >&2
exit 1

#SBATCH --job-name=cahoy_clim
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-767%6
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/aurora_cahoy_solar_climate_v0/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/aurora_cahoy_solar_climate_v0/%x_%A_%a.err

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"

MODEL="aurora_cahoy_solar_climate_v0"
GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"
CONFIG="$GRID_ROOT/params/${MODEL}.yaml"
MANIFEST="$GRID_ROOT/manifests/${MODEL}_manifest.csv"
SOLAR_SPEC="$GRID_ROOT/data/stellar_spectra/SOLARSPECTRUM.DAT"

mkdir -p "$GRID_ROOT/logs/$MODEL"
mkdir -p "$GRID_ROOT/outputs/$MODEL/nc"
mkdir -p "$GRID_ROOT/manifests"

export AURORA_FORCE_CONDA=1
export AURORA_STELLAR_SPECTRUM="$SOLAR_SPEC"
export AURORA_STELLAR_W_UNIT="Angstrom"
export AURORA_STELLAR_F_UNIT="erg/s/cm2/Angstrom"

module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_aurora_picaso4_job.sh

export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export NUMEXPR_NUM_THREADS=4

echo "job_id=${SLURM_JOB_ID}"
echo "array_task_id=${SLURM_ARRAY_TASK_ID}"
echo "python=$(which python)"
python --version
echo "CONDA_DEFAULT_ENV=${CONDA_DEFAULT_ENV:-none}"
echo "PICASO_CK_ROOT=$PICASO_CK_ROOT"
echo "SOLAR_SPEC=$SOLAR_SPEC"

if [ ! -f "$SOLAR_SPEC" ]; then
  echo "ERROR: missing solar spectrum file: $SOLAR_SPEC"
  exit 2
fi

if [ ! -f "$MANIFEST" ]; then
  python "$GRID_ROOT/scripts/make_manifest.py" \
    --config "$CONFIG" \
    --out "$MANIFEST"
fi

python "$GRID_ROOT/scripts/run_grid_chunk.py" \
  --manifest "$MANIFEST" \
  --array-index "${SLURM_ARRAY_TASK_ID}" \
  --model-name "$MODEL" \
  --use-picaso-climate \
  --picaso-ck-root "$PICASO_CK_ROOT" \
  --overwrite
