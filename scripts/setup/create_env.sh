#!/bin/bash
# Create a conda prefix env from an explicit lock file (conda list --explicit), plus optional pip pins.
# Runs on a login node (needs network). Usage: create_env.sh <job.env> <prefix> <lock> [pip_lock]
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/../../config/env.sh" "$1"
prefix=$2; lock=$3; pip_lock=${4:-}
[[ -e $prefix ]] && { echo "$prefix exists" >&2; exit 1; }
base=${CONDA_BASE:-$(conda info --base)}
source "$base/etc/profile.d/conda.sh"
CONDA_PKGS_DIRS=$DATA_ROOT/conda_pkgs conda create --yes --quiet -p "$prefix" --file "$lock"
if [[ -n $pip_lock ]]; then
    "$prefix/bin/python" -m pip install --no-deps --no-cache-dir -r "$pip_lock"
fi
conda list -p "$prefix" --explicit > "$(dirname "$prefix")/installed.lock.txt"
echo "created $prefix"
