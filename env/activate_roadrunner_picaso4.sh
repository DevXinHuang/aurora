#!/usr/bin/env bash
# Source this file before running RoadRunner/EGP workflows with PICASO 4.

if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_SOURCE="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  SCRIPT_SOURCE="${(%):-%x}"
else
  SCRIPT_SOURCE="$0"
fi

SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export ROADRUNNER_SCIENCE_INPUTS="${REPO_ROOT}/science_inputs"
export PYTHONPATH="${REPO_ROOT}/roadrunner_egp${PYTHONPATH:+:${PYTHONPATH}}"

export picaso_refdata="${REPO_ROOT}/picaso4_reference"
export PYSYN_CDBS="${REPO_ROOT}/picaso4_reference/stellar_grids"

export SLGRID_BASE_DIR="${REPO_ROOT}/science_inputs/slgrid"
export SLGRID_PT_DIR="${REPO_ROOT}/science_inputs/slgrid/climate"
export SLGRID_CLD_DIR="${REPO_ROOT}/science_inputs/slgrid/clouds"
export EGP_IRFLUX_DIR="${REPO_ROOT}/science_inputs/egp/irflux"
export ROADRUNNER_PICASO_VIRGA_DIR="${REPO_ROOT}/picaso4_reference/virga/virga"

echo "RoadRunner/EGP profile: picaso4"
echo "  PYTHONPATH entry: ${REPO_ROOT}/roadrunner_egp"
echo "  picaso_refdata: ${picaso_refdata}"
echo "  SLGRID climate: ${SLGRID_PT_DIR}"
echo "  SLGRID clouds: ${SLGRID_CLD_DIR}"
echo "  EGP IRflux: ${EGP_IRFLUX_DIR}"
echo "  Virga files: ${ROADRUNNER_PICASO_VIRGA_DIR}"
