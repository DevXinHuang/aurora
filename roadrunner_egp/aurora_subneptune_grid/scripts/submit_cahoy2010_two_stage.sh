#!/usr/bin/env bash
# Cahoy et al. 2010 replication: 16 climate jobs, then 304 spectrum jobs.
# Usage (from anywhere):
#   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_cahoy2010_two_stage.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
exec bash "$SCRIPT_DIR/submit_two_stage_grid.sh" "$REPO_ROOT" aurora_cahoy2010_replication_v0
