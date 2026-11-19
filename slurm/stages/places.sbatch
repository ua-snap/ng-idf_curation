#!/bin/bash
# Pipeline stage job (places): place table with the app's nearest-cell rules.
#SBATCH --job-name=ngidf-places
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
# work on a copy of the land-status cache: it is an input and must not change
cp "$DAYMET_LAND_CACHE" "$STAGE_DIR/land_cache.json"
python -I "$REPO/scripts/places/build_place_table.py" --communities "$PLACES_SNAPSHOT" \
    --wrf-file "$WRF_GRID_FILE" --cesm-file "$CESM_GRID_FILE" \
    --defaults-csv "$APP_DIR/static/gridcell_current_lulc.csv" \
    --land-cache "$STAGE_DIR/land_cache.json" --daymet-pixel-dir "$DATA_ROOT/raw/daymet_v4_pixels" --offline \
    --out "$OUT/places_ak.csv"
