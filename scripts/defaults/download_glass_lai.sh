#!/bin/bash
# Download GLASS LAI V60 500 m 8-day (GLASS01E01) tiles covering Alaska for one year.
# Usage: download_glass_lai.sh <year> <outdir>
set -euo pipefail
YEAR=$1; OUT=$2
BASE=https://glass.hku.hk/archive/LAI/MODIS/500M/$YEAR
TILES="h06v03 h07v03 h08v03 h09v02 h09v03 h10v02 h10v03 h11v02 h11v03 h12v01 h12v02 h13v01 h13v02 h28v03 h29v03"
mkdir -p "$OUT"
for DOY in $(seq -w 1 8 361); do
  DOY=$(printf %03d $((10#$DOY)))
  listing=$(curl -sS --retry 5 --retry-all-errors -m 120 "$BASE/$DOY/")
  for T in $TILES; do
    f=$(grep -oE "GLASS01E01\.V60\.A${YEAR}${DOY}\.${T}\.[0-9]+\.hdf\"" <<<"$listing" | tr -d '"' | head -1 || true)
    if [[ -z "$f" ]]; then echo "MISSING $DOY $T"; continue; fi
    if [[ ! -s "$OUT/$f" ]]; then
      curl -sS --retry 5 --retry-all-errors -m 600 -o "$OUT/$f.part" "$BASE/$DOY/$f" && mv "$OUT/$f.part" "$OUT/$f"
    fi
  done
done
(cd "$OUT" && sha256sum *.hdf > SHA256SUMS)
ls "$OUT"/*.hdf | wc -l
