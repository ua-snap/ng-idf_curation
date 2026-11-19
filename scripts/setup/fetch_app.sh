#!/bin/bash
# Fetch H. Yan's NG-IDF app at the pinned commit, without the large spatial_map/ tree, and verify the hash.
# The upstream repo has no LICENSE, so it is not vendored here: pinned commits are mirrored (as tags
# app-<sha7>) into the private ua-snap/NG_IDF and fetched from there.
# Runs on a login node (needs network). Usage: fetch_app.sh <job.env> <dest>
# job.env provides APP_REPO, APP_REF, APP_COMMIT.
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/../../config/env.sh" "$1"
dest=${2:?dest}
if [[ -e "$dest/.git" ]]; then
    have=$(git -C "$dest" rev-parse HEAD)
    [[ "$have" == "$APP_COMMIT" ]] || { echo "ERROR: $dest is at $have, expected $APP_COMMIT" >&2; exit 1; }
    echo "$dest already at $APP_COMMIT"; exit 0
fi
git clone --filter=blob:none --no-checkout "$APP_REPO" "$dest"
git -C "$dest" sparse-checkout set --no-cone '/*' '!/spatial_map/'
git -C "$dest" fetch --quiet origin "refs/tags/$APP_REF:refs/tags/$APP_REF" 2>/dev/null || true
git -C "$dest" checkout --quiet --detach "$APP_REF"
have=$(git -C "$dest" rev-parse HEAD)
[[ "$have" == "$APP_COMMIT" ]] || { echo "ERROR: $APP_REF is $have, expected $APP_COMMIT" >&2; exit 1; }
echo "fetched $APP_REPO $APP_REF = $APP_COMMIT into $dest"
