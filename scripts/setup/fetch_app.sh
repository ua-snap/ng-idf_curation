#!/bin/bash
# Fetch H. Yan's NG-IDF app at the pinned commit (config/app.env), without the
# large spatial_map/ tree. The upstream repo has no LICENSE, so we fetch it by
# commit hash instead of vendoring it.
# Usage: fetch_app.sh [dest_dir]   (default: $DATA_ROOT/app/NG_IDF_AWS)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
source "$here/../../config/app.env"
dest=${1:-$DATA_ROOT/app/NG_IDF_AWS}

if [[ -e "$dest/.git" ]]; then
    have=$(git -C "$dest" rev-parse HEAD)
    [[ "$have" == "$APP_COMMIT" ]] || { echo "ERROR: $dest is at $have, expected $APP_COMMIT" >&2; exit 1; }
    git -C "$dest" diff --quiet || { echo "ERROR: $dest has local modifications" >&2; exit 1; }
    echo "$dest already at $APP_COMMIT"
    exit 0
fi

git clone --filter=blob:none --no-checkout "$APP_REPO" "$dest"
git -C "$dest" sparse-checkout set --no-cone '/*' '!/spatial_map/'
git -C "$dest" checkout --detach "$APP_COMMIT"
have=$(git -C "$dest" rev-parse HEAD)
[[ "$have" == "$APP_COMMIT" ]] || { echo "ERROR: checkout gave $have" >&2; exit 1; }
echo "fetched $APP_REPO @ $APP_COMMIT into $dest"
