#!/usr/bin/env bash
# Grid-runner runtime paths shared by local Mac scripts and HPC Slurm jobs.
# Source after Python is active (via activate_local_picaso4.sh or conda/micromamba).

if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_SOURCE="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  SCRIPT_SOURCE="${(%):-%x}"
else
  SCRIPT_SOURCE="$0"
fi

SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GRID_SRC="${REPO_ROOT}/roadrunner_egp/aurora_subneptune_grid/src"
ROADRUNNER_SRC="${REPO_ROOT}/roadrunner_egp"

case ":${PYTHONPATH:-}:" in
  *":${GRID_SRC}:"*) ;;
  *) export PYTHONPATH="${GRID_SRC}:${ROADRUNNER_SRC}${PYTHONPATH:+:${PYTHONPATH}}" ;;
esac

export PICASO_CK_ROOT="${PICASO_CK_ROOT:-${REPO_ROOT}/picaso4_reference/opacities}"
export ROADRUNNER_PICASO_VIRGA_CONDENSATES="${ROADRUNNER_PICASO_VIRGA_CONDENSATES:-H2O,CH4,NH3}"
export ROADRUNNER_REQUIRE_VIRGA="${ROADRUNNER_REQUIRE_VIRGA:-1}"

echo "Aurora grid runtime:"
echo "  PYTHONPATH grid src: ${GRID_SRC}"
echo "  PICASO_CK_ROOT: ${PICASO_CK_ROOT}"
echo "  ROADRUNNER_PICASO_VIRGA_CONDENSATES: ${ROADRUNNER_PICASO_VIRGA_CONDENSATES}"
echo "  ROADRUNNER_REQUIRE_VIRGA: ${ROADRUNNER_REQUIRE_VIRGA}"
