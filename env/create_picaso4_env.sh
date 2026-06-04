#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="picaso4"
PYTHON_VERSION="3.11"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PICASO4_REFDATA="${REPO_ROOT}/picaso4_reference"
PICASO4_PYSYN_CDBS="${PICASO4_REFDATA}/stellar_grids"
CONDA_BIN="${CONDA_BIN:-/Users/xin/anaconda3/bin/conda}"

if [ ! -x "${CONDA_BIN}" ]; then
  CONDA_BIN="$(command -v conda || true)"
fi

if [ -z "${CONDA_BIN}" ] || [ ! -x "${CONDA_BIN}" ]; then
  echo "ERROR: conda was not found on PATH." >&2
  exit 1
fi

if "${CONDA_BIN}" env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "Conda environment ${ENV_NAME} already exists; leaving it in place."
else
  "${CONDA_BIN}" create -y -n "${ENV_NAME}" "python=${PYTHON_VERSION}"
fi

# Optional alternative install path:
# conda install -y -n "${ENV_NAME}" conda-forge::picaso

PICASO4_PYTHON="$("${CONDA_BIN}" env list | awk -v env="${ENV_NAME}" '$1 == env {print $NF "/bin/python"}')"
if [ ! -x "${PICASO4_PYTHON}" ]; then
  echo "ERROR: could not find Python for ${ENV_NAME}." >&2
  exit 1
fi

"${PICASO4_PYTHON}" -m pip install --upgrade pip
"${PICASO4_PYTHON}" -m pip install picaso

CONDA_PREFIX_FOR_ENV="$("${PICASO4_PYTHON}" -c 'import sys; print(sys.prefix)')"
mkdir -p "${CONDA_PREFIX_FOR_ENV}/etc/conda/activate.d"
mkdir -p "${CONDA_PREFIX_FOR_ENV}/etc/conda/deactivate.d"

cat > "${CONDA_PREFIX_FOR_ENV}/etc/conda/activate.d/env_vars.sh" <<EOF
export picaso_refdata="${PICASO4_REFDATA}"
export PYSYN_CDBS="${PICASO4_PYSYN_CDBS}"
EOF

cat > "${CONDA_PREFIX_FOR_ENV}/etc/conda/deactivate.d/env_vars.sh" <<'EOF'
unset picaso_refdata
unset PYSYN_CDBS
EOF

echo "Configured ${ENV_NAME}:"
echo "  picaso_refdata=${PICASO4_REFDATA}"
echo "  PYSYN_CDBS=${PICASO4_PYSYN_CDBS}"
echo
echo "Next reference-data step:"
echo "  ${PICASO4_PYTHON} ${REPO_ROOT}/env/setup_picaso4_reference_data.py"
