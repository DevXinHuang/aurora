#!/usr/bin/env bash
# Submit the standard Aurora two-stage PICASO grid workflow:
#   Stage 1: converge climate once per climate_group_index
#   Stage 2: compute reflected spectra for every manifest row (phase, etc.)
#
# Usage:
#   bash roadrunner_egp/aurora_subneptune_grid/scripts/submit_two_stage_grid.sh <repo_root> <model_name>
#
# Examples:
#   bash .../submit_two_stage_grid.sh "$(pwd)" smoke_test_aurora_subneptune
#   bash .../submit_two_stage_grid.sh "$(pwd)" hpc_validation_aurora_subneptune
#   bash .../submit_two_stage_grid.sh "$(pwd)" aurora_cahoy2010_replication_v0
#   bash .../submit_two_stage_grid.sh "$(pwd)" aurora_subneptune_v1   # batched — see README

set -eo pipefail

REPO_ROOT="${1:-/home/u11/danielxinhuang/Documents/aurora}"
MODEL="${2:?usage: submit_two_stage_grid.sh <repo_root> <model_name>}"
cd "$REPO_ROOT"

GRID_ROOT="roadrunner_egp/aurora_subneptune_grid"
CONFIG="$GRID_ROOT/params/${MODEL}.yaml"
MANIFEST="$GRID_ROOT/manifests/${MODEL}_manifest.csv"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: missing config $CONFIG" >&2
  exit 1
fi

if [ ! -f "$MANIFEST" ] || ! head -1 "$MANIFEST" | tr ',' '\n' | grep -qx climate_group_index; then
  echo "Regenerating manifest (missing or stale): $MANIFEST"
  if [ "$MODEL" = "aurora_cahoy2010_replication_v0" ]; then
    python "$GRID_ROOT/scripts/make_cahoy2010_manifest.py" --config "$CONFIG" --out "$MANIFEST"
  else
    python "$GRID_ROOT/scripts/make_manifest.py" --config "$CONFIG" --out "$MANIFEST"
  fi
fi

read -r N_ROWS N_GROUPS <<EOF
$(python - <<PY
import csv
from pathlib import Path
import sys
sys.path.insert(0, "roadrunner_egp/aurora_subneptune_grid/src")
from aurora_grid.climate_groups import count_climate_groups

manifest = Path("${MANIFEST}")
with manifest.open() as f:
    rows = list(csv.DictReader(f))
print(len(rows), count_climate_groups(rows))
PY
)
EOF

export MODEL MANIFEST
CLIMATE_MAX=$((N_GROUPS - 1))
SPECTRUM_MAX=$((N_ROWS - 1))

echo "model: $MODEL"
echo "manifest: $MANIFEST"
echo "spectrum_rows: $N_ROWS"
echo "climate_groups: $N_GROUPS"

# Full grid exceeds typical Slurm MaxArraySize — submit in batches of 1000.
MAX_ARRAY=1000
if [ "$N_GROUPS" -gt "$MAX_ARRAY" ] || [ "$N_ROWS" -gt "$MAX_ARRAY" ]; then
  echo "Large grid: submitting batched climate + spectrum jobs (batch size $MAX_ARRAY)."
  CLIMATE_JOBS=()
  for start in $(seq 0 "$MAX_ARRAY" "$CLIMATE_MAX"); do
    end=$((start + MAX_ARRAY - 1))
    [ "$end" -gt "$CLIMATE_MAX" ] && end=$CLIMATE_MAX
    job=$(sbatch --parsable --array="${start}-${end}%6" \
      --export=ALL,MODEL,MANIFEST \
      "$GRID_ROOT/slurm/run_climate_cache.slurm")
    CLIMATE_JOBS+=("$job")
    echo "  climate batch ${start}-${end}: $job"
  done
  CLIMATE_DEP=$(IFS=,; echo "${CLIMATE_JOBS[*]}")
  for start in $(seq 0 "$MAX_ARRAY" "$SPECTRUM_MAX"); do
    end=$((start + MAX_ARRAY - 1))
    [ "$end" -gt "$SPECTRUM_MAX" ] && end=$SPECTRUM_MAX
    job=$(sbatch --parsable --dependency=afterok:"${CLIMATE_DEP}" --array="${start}-${end}%12" \
      --export=ALL,MODEL,MANIFEST \
      "$GRID_ROOT/slurm/run_spectrum_from_cache.slurm")
    echo "  spectrum batch ${start}-${end}: $job (after climate)"
  done
else
  CLIMATE_JOB=$(sbatch --parsable --array="0-${CLIMATE_MAX}%6" \
    --export=ALL,MODEL,MANIFEST \
    "$GRID_ROOT/slurm/run_climate_cache.slurm")
  echo "climate job: $CLIMATE_JOB (0-${CLIMATE_MAX})"
  SPECTRUM_JOB=$(sbatch --parsable --dependency=afterok:"${CLIMATE_JOB}" \
    --array="0-${SPECTRUM_MAX}%12" \
    --export=ALL,MODEL,MANIFEST \
    "$GRID_ROOT/slurm/run_spectrum_from_cache.slurm")
  echo "spectrum job: $SPECTRUM_JOB (0-${SPECTRUM_MAX}, after climate)"
fi

echo "Caches:  outputs under yaml output_root → climate_cache/climate_XX.npz"
echo "Spectra: outputs under yaml output_root → nc/run_XXXXXX.nc"
