#!/usr/bin/env bash
set -euo pipefail

# Thin wrapper kept for older docs; canonical script lives under aurora_subneptune_grid/scripts/.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec bash "${REPO_ROOT}/roadrunner_egp/aurora_subneptune_grid/scripts/run_patchy_picaso_climate_native_local.sh" "$@"
