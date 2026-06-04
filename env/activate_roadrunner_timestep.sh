#!/usr/bin/env bash
# Source this file before running the original timestep RoadRunner/EGP workflows.

TIMESTEP_ROOT="${TIMESTEP_ROOT:-/Users/xin/Documents/Documents/College/timestep}"

export TIMESTEP_ROOT
export PYTHONPATH="${TIMESTEP_ROOT}/roadrunner_project${PYTHONPATH:+:${PYTHONPATH}}"

export picaso_refdata="${TIMESTEP_ROOT}/picaso/reference"
export PYSYN_CDBS="${TIMESTEP_ROOT}/picaso/reference/grp/redcat/trds"

export SLGRID_BASE_DIR="${TIMESTEP_ROOT}/2_9_2026"
export SLGRID_PT_DIR="${TIMESTEP_ROOT}/2_9_2026/SLGRID Climate Files"
export SLGRID_CLD_DIR="${TIMESTEP_ROOT}/2_9_2026/SLGRID Cloud Files"
export EGP_IRFLUX_DIR="${TIMESTEP_ROOT}/roadrunner_project/EGP/EGP Grid for Daniel"
export ROADRUNNER_PICASO_VIRGA_DIR="${TIMESTEP_ROOT}/picaso/reference/virga"

echo "RoadRunner/EGP profile: timestep"
echo "  PYTHONPATH entry: ${TIMESTEP_ROOT}/roadrunner_project"
echo "  picaso_refdata: ${picaso_refdata}"
echo "  SLGRID climate: ${SLGRID_PT_DIR}"
echo "  SLGRID clouds: ${SLGRID_CLD_DIR}"
echo "  EGP IRflux: ${EGP_IRFLUX_DIR}"
echo "  Virga files: ${ROADRUNNER_PICASO_VIRGA_DIR}"
