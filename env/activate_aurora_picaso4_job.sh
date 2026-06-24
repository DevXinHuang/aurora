#!/usr/bin/env bash
# Activate PICASO 4 for Aurora grid jobs on Mac (.venv-picaso4) or HPC (micromamba/conda).
#
# Usage (from repo root):
#   source env/activate_aurora_picaso4_job.sh
#
# Overrides:
#   AURORA_FORCE_CONDA=1     always use micromamba/conda even if .venv-picaso4 exists
#   AURORA_PICASO4_VENV=...  alternate venv path (same as activate_local_picaso4.sh)

if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_SOURCE="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  SCRIPT_SOURCE="${(%):-%x}"
else
  SCRIPT_SOURCE="$0"
fi

SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${AURORA_PICASO4_VENV:-${REPO_ROOT}/.venv-picaso4}"

_activate_conda_or_micromamba() {
  if command -v micromamba >/dev/null 2>&1; then
    if command -v module >/dev/null 2>&1; then
      module load micromamba 2>/dev/null || true
    fi
    eval "$(micromamba shell hook --shell bash)"
    micromamba activate picaso4 || micromamba activate picaso-env
    return 0
  fi

  if command -v conda >/dev/null 2>&1; then
    if command -v module >/dev/null 2>&1; then
      module load anaconda 2>/dev/null || true
    fi
    # shellcheck source=/dev/null
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate picaso4 || conda activate picaso-env
    return 0
  fi

  echo "ERROR: no micromamba/conda found for PICASO 4." >&2
  echo "On Mac, create the project venv with:" >&2
  echo "  python3 -m venv ${VENV_DIR}" >&2
  echo "  ${VENV_DIR}/bin/python -m pip install picaso jupyter pandas numpy scipy matplotlib astropy numba xarray netcdf4 pyyaml" >&2
  return 1 2>/dev/null || exit 1
}

if [ -n "${SLURM_JOB_ID:-}" ] || [ "${AURORA_FORCE_CONDA:-0}" = "1" ]; then
  _activate_conda_or_micromamba
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/env/activate_roadrunner_picaso4.sh"
elif [ -f "${VENV_DIR}/bin/activate" ]; then
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/env/activate_local_picaso4.sh"
else
  _activate_conda_or_micromamba
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/env/activate_roadrunner_picaso4.sh"
fi

# shellcheck source=/dev/null
source "${REPO_ROOT}/env/activate_aurora_grid_runtime.sh"
