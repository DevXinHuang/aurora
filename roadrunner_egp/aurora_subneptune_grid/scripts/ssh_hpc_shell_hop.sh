#!/bin/bash
# Remote-shell adapter for rsync: local -> gatekeeper -> Puma submission host.

set -euo pipefail

if [[ "$#" -lt 2 ]]; then
  echo "usage: $0 IGNORED_RSYNC_HOST REMOTE_COMMAND [ARGS...]" >&2
  exit 2
fi

# rsync supplies a host argument. Authentication and routing are instead
# handled by the two configured HPC hops below.
shift
exec ssh \
  -o BatchMode=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=10 \
  ua-hpc \
  ssh \
  -o BatchMode=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=10 \
  shell.hpc.arizona.edu \
  "$@"
