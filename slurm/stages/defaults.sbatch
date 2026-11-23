#!/bin/bash
# Pipeline stage job (defaults): NLCD / LANDFIRE EVH / GLASS LAI per 1 km defaults cell, then the app's rules.
#SBATCH --job-name=ngidf-defaults
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$GEO_ENV"
work=$STAGE_DIR/work; mkdir -p "$work"
cells=$STAGE_DIR/defaults_cells.csv
python -I - "$PLACES_CSV" "$cells" <<'PY'
import sys, pandas as pd
p = pd.read_csv(sys.argv[1])
p = p[p.defaults_status == 'ok'][['defaults_lat', 'defaults_lon']].drop_duplicates()
p.rename(columns={'defaults_lat': 'latitude', 'defaults_lon': 'longitude'}).to_csv(sys.argv[2], index=False)
print(len(p), 'defaults cells')
PY
python -I "$REPO/scripts/defaults/cell_counts.py" "$NLCD_RASTER" "$cells" "$work/nlcd2016_counts.npz" & p1=$!
python -I "$REPO/scripts/defaults/cell_counts.py" "$EVH_RASTER" "$cells" "$work/evh2016_counts.npz" & p2=$!
python -I "$REPO/scripts/defaults/cell_lai.py" "$GLASS_DIR" "$cells" "$work/glass_lai.csv" & p3=$!
# check: the same LAI rule over every cell of the author's table, compared with his max_LAI by the stage
table_cells=$STAGE_DIR/table_cells.csv
python -I -c "import sys, pandas as pd; pd.read_csv(sys.argv[1])[['latitude', 'longitude']].to_csv(sys.argv[2], index=False)" \
    "$APP_DIR/static/gridcell_current_lulc.csv" "$table_cells"
python -I "$REPO/scripts/defaults/cell_lai.py" "$GLASS_DIR" "$table_cells" "$OUT/table_lai.csv" & p4=$!
wait $p1; wait $p2; wait $p3; wait $p4
python -I "$REPO/scripts/defaults/build_place_defaults.py" "$PLACES_CSV" "$APP_DIR/static/gridcell_current_lulc.csv" \
    "$work" "$OUT/place_defaults.csv"
