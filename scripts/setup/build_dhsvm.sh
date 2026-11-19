#!/bin/bash
# Build DHSVM 3.2 (no_sat_dump) from the pinned app checkout, with the app's own
# makefile_for_binary. The binary shipped in the repo is a Cray build and does not
# run on Chinook. Flags match the makefile (no optimisation, -DHAVE_X11). We only
# point it at the conda toolchain and add:
#   -fcommon               GCC >= 10 (as in the colleague's container build)
#   -std=gnu17 -fpermissive GCC >= 14 turned old warnings into errors. The one hit,
#                          DHSVMChannel.c:107, is an upstream misplaced parenthesis in the
#                          road-network reader, which the app never runs (no roads).
#                          These flags restore the GCC 11/12 behaviour of the author's build.
# Usage: build_dhsvm.sh <src: app/dhsvm/no_sat_dump> <build_dir> <out_dir>   (ngidf env active)
# Writes <out_dir>/DHSVM3.2, build.log and build.json (sha256, compiler, flags, warning/error counts).
set -euo pipefail
: "${CONDA_PREFIX:?activate the ngidf env first}"
src=${1:?src}; build=${2:?build_dir}; out=${3:?out_dir}
rm -rf "$build"; mkdir -p "$build" "$out"
cp -a "$src"/. "$build"/
rm -f "$build/DHSVM3.2" "$build"/*.o
cc_cmd="${CC:-cc} -fcommon -std=gnu17 -fpermissive"
cflags="-g -Wall -I$CONDA_PREFIX/include -DHAVE_X11"
libs="-lm -L$CONDA_PREFIX/lib -Wl,-rpath,$CONDA_PREFIX/lib -lX11"
cd "$build"
rc=0
make -f makefile_for_binary CC="$cc_cmd" FLEX="$(command -v flex)" CFLAGS="$cflags" LIBS="$libs" > "$out/build.log" 2>&1 || rc=$?
[[ $rc -eq 0 && -x DHSVM3.2 ]] || { tail -40 "$out/build.log"; exit 1; }
cp DHSVM3.2 "$out/DHSVM3.2"
sha=$(sha256sum "$out/DHSVM3.2" | cut -d' ' -f1)
python -I - "$out" "$sha" "$cc_cmd" "$cflags" "$libs" "$($cc_cmd --version | head -1)" <<'PY'
import json, re, sys
out, sha, cc, cflags, libs, ver = sys.argv[1:]
log = open(f'{out}/build.log').read()
json.dump(dict(sha256=sha, compiler=ver, cc=cc, cflags=cflags, libs=libs,
               warnings=len(re.findall(r'warning:', log)), errors=len(re.findall(r'error:', log))),
          open(f'{out}/build.json', 'w'), indent=1)
PY
echo "built $out/DHSVM3.2 ($sha)"
