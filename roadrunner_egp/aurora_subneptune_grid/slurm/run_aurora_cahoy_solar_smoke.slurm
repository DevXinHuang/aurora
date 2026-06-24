#!/bin/bash
#SBATCH --job-name=cahoy_smoke
#SBATCH --account=tdrobin
#SBATCH --partition=standard
#SBATCH --array=0-47%12
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=roadrunner_egp/aurora_subneptune_grid/logs/aurora_cahoy_solar_smoke_v0/%x_%A_%a.out
#SBATCH --error=roadrunner_egp/aurora_subneptune_grid/logs/aurora_cahoy_solar_smoke_v0/%x_%A_%a.err

set -eo pipefail

cd "${SLURM_SUBMIT_DIR:-/home/u11/danielxinhuang/Documents/aurora}"

MODEL="aurora_cahoy_solar_smoke_v0"
GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"
CONFIG="$GRID_ROOT/params/${MODEL}.yaml"
MANIFEST="$GRID_ROOT/manifests/${MODEL}_manifest.csv"
SOLAR_SPEC="$GRID_ROOT/data/stellar_spectra/SOLARSPECTRUM.DAT"

mkdir -p "$GRID_ROOT/logs/$MODEL"
mkdir -p "$GRID_ROOT/outputs/$MODEL"
mkdir -p "$GRID_ROOT/manifests"

export PYTHONPATH="roadrunner_egp/aurora_subneptune_grid/src:roadrunner_egp"
export PICASO_CK_ROOT="/home/u11/danielxinhuang/Documents/aurora/picaso4_reference/opacities"

# Solar spectrum path for this Cahoy-matched run.
export AURORA_STELLAR_SPECTRUM="$SOLAR_SPEC"
export AURORA_STELLAR_W_UNIT="Angstrom"
export AURORA_STELLAR_F_UNIT="erg/s/cm2/Angstrom"

module load micromamba/2.0.2-2
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.local/share/mamba}"
eval "$(micromamba shell hook --shell bash)"
micromamba activate picaso4
source env/activate_roadrunner_picaso4.sh

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

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
  --model-name "$MODEL"
