#!/usr/bin/env bash
#SBATCH --job-name=aurora-smoke
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
#SBATCH --time=00:20:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#
# If your HPC allocation requires an account or partition, uncomment and edit:
##SBATCH --account=YOUR_GROUP_NAME
##SBATCH --partition=standard

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$(pwd)}"
mkdir -p logs

if command -v module >/dev/null 2>&1; then
  module load micromamba || true
fi

eval "$(micromamba shell hook --shell bash)"
micromamba activate "${AURORA_ENV:-picaso4}"
source env/activate_roadrunner_picaso4.sh

python - <<'PY'
import picaso

from roadrunner.system import summarize_slgrid_inventory
from workflows.hybrid_reflected_picaso_thermal_egp import available_egp_temperatures

print("PICASO:", picaso.__file__)
print(summarize_slgrid_inventory())
print("EGP g=31 temperatures:", available_egp_temperatures("31"))
PY
