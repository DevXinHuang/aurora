#!/usr/bin/env bash
# Source this file to use Aurora's project-local PICASO 4 virtualenv.

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

if [ ! -f "${VENV_DIR}/bin/activate" ]; then
  echo "ERROR: PICASO 4 virtualenv not found: ${VENV_DIR}" >&2
  echo "Create it with:" >&2
  echo "  python3 -m venv ${VENV_DIR}" >&2
  echo "  ${VENV_DIR}/bin/python -m pip install picaso jupyter ipykernel pandas numpy scipy matplotlib astropy numba" >&2
  return 1 2>/dev/null || exit 1
fi

# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

# shellcheck source=/dev/null
source "${REPO_ROOT}/env/activate_roadrunner_picaso4.sh"

echo "  python: $(command -v python)"
