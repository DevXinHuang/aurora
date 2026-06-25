#!/usr/bin/env bash
# Download and extract the official Cahoy et al. 2010 albedo spectra archive (~3.8 MB).
#
# Usage:
#   bash roadrunner_egp/aurora_subneptune_grid/scripts/install_cahoy2010_reference.sh
#
# Or copy your local copy from Mac Downloads:
#   scp ~/Downloads/cahoy2010_spectra.tgz hpc:~/Documents/aurora/roadrunner_egp/aurora_subneptune_grid/data/cahoy2010_reference/
#   bash .../install_cahoy2010_reference.sh --from-tarball

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="$(cd "$SCRIPT_DIR/../data/cahoy2010_reference" && pwd)"
TARBALL="$DATA_ROOT/cahoy2010_spectra.tgz"
URL="https://roman.ipac.caltech.edu/data/sims/cahoy2010_spectra.tgz"
SPECTRA_DIR="$DATA_ROOT/Cahoy_et_al_2010_Albedo_Spectra/albedo_spectra"

mkdir -p "$DATA_ROOT"

if [ "${1:-}" = "--from-tarball" ] && [ ! -f "$TARBALL" ]; then
  echo "ERROR: expected tarball at $TARBALL" >&2
  exit 1
fi

if [ ! -f "$TARBALL" ]; then
  echo "Downloading $URL"
  curl -fsSL -o "$TARBALL" "$URL"
fi

if [ ! -d "$SPECTRA_DIR" ] || [ "$(find "$SPECTRA_DIR" -maxdepth 1 -name '*.dat' | wc -l)" -lt 300 ]; then
  echo "Extracting $TARBALL"
  tar --no-same-owner -xzf "$TARBALL" -C "$DATA_ROOT"
fi

N_FILES="$(find "$SPECTRA_DIR" -maxdepth 1 -name '*.dat' | wc -l)"
echo "Cahoy reference spectra: $N_FILES files under $SPECTRA_DIR"
if [ "$N_FILES" -lt 300 ]; then
  echo "WARNING: expected ~304 .dat files" >&2
  exit 1
fi

echo "Ready for compare:"
echo "  python roadrunner_egp/aurora_subneptune_grid/scripts/run_cahoy2010_compare.py --plot"
