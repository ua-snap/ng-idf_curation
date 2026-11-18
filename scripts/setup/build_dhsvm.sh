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
# Usage: build_dhsvm.sh   (requires the ngidf conda env to be active)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
source "$here/../../config/app.env"
: "${CONDA_PREFIX:?activate the ngidf env first}"
src=$DATA_ROOT/app/NG_IDF_AWS/dhsvm/no_sat_dump
build=$DATA_ROOT/build/dhsvm_${APP_COMMIT:0:7}
rm -rf "$build"
mkdir -p "$build"
cp -a "$src"/. "$build"/
rm -f "$build/DHSVM3.2" "$build"/*.o
cd "$build"
make -f makefile_for_binary \
    CC="${CC:-cc} -fcommon -std=gnu17 -fpermissive" \
    FLEX="$(command -v flex)" \
    CFLAGS="-g -Wall -I$CONDA_PREFIX/include -DHAVE_X11" \
    LIBS="-lm -L$CONDA_PREFIX/lib -Wl,-rpath,$CONDA_PREFIX/lib -lX11" \
    > build.log 2>&1 || { tail -40 build.log; exit 1; }
test -x DHSVM3.2
sha256sum DHSVM3.2 > DHSVM3.2.sha256
echo "built $build/DHSVM3.2"
