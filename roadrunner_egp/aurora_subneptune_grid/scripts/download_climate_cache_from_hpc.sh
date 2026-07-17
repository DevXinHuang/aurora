#!/bin/bash
# Download Stage 1 climate-cache NPZ/PKL files from the HPC group disk.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRID_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HPC_HOST="${AURORA_HPC_TRANSFER_HOST:-hpc-shell}"
REMOTE_DIR="${AURORA_HPC_CACHE_DIR:-/groups/tdrobin/dhuang/aurora_subneptune_v1_dhuang/climate_cache}"
LOCAL_DIR="${AURORA_LOCAL_CACHE_DIR:-$GRID_ROOT/outputs/aurora_subneptune_v1_dhuang/climate_cache}"
NESTED_SSH="$SCRIPT_DIR/ssh_hpc_shell_hop.sh"

mkdir -p "$LOCAL_DIR"

echo "HPC host:   $HPC_HOST"
echo "Remote:     $REMOTE_DIR"
echo "Local:      $LOCAL_DIR"
echo "File types: .npz and .pkl"

# --partial makes reconnects resumable. The include/exclude
# rules prevent logs, NetCDF products, or controller files from being copied.
rsync \
  --rsh="$NESTED_SSH" \
  --archive \
  --human-readable \
  --progress \
  --stats \
  --partial \
  --timeout=120 \
  --include='*.npz' \
  --include='*.pkl' \
  --exclude='*' \
  "${HPC_HOST}:${REMOTE_DIR}/" \
  "${LOCAL_DIR}/"

npz_count="$(find "$LOCAL_DIR" -maxdepth 1 -type f -name '*.npz' | wc -l | tr -d ' ')"
pkl_count="$(find "$LOCAL_DIR" -maxdepth 1 -type f -name '*.pkl' | wc -l | tr -d ' ')"
total_bytes="$(find "$LOCAL_DIR" -maxdepth 1 -type f \( -name '*.npz' -o -name '*.pkl' \) -exec stat -f '%z' {} + | awk '{sum += $1} END {printf "%.0f", sum}')"

echo "Downloaded NPZ files: $npz_count"
echo "Downloaded PKL files: $pkl_count"
echo "Downloaded bytes:     $total_bytes"
