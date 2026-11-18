#!/bin/bash
# Zonal NLCD/EVH counts and GLASS LAI for the 1 km defaults cells of the Phase 1 places,
# plus a re-run of the LAI rule over the author's Interior table as a consistency check.
#SBATCH --job-name=ngidf-pdefaults
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate snap-geo; set -u
CELLS=$REPO/data/places/defaults_cells.csv
OUT=$DATA/work/place_defaults; mkdir -p $OUT
for r in nlcd2016:$DATA/raw/nlcd_2016_ak/NLCD_2016_Land_Cover_AK_20200724.img evh2016:$DATA/raw/landfire_evh_2016_ak/LF2016_EVH_AK/Tif/LF2016_EVH_AK.tif; do
    python -I $REPO/scripts/defaults/cell_counts.py ${r#*:} $CELLS $OUT/${r%%:*}_counts.npz &
    # consistency check against zonal_counts.py on 300 cells of the author's table
    python -I $REPO/scripts/defaults/cell_counts.py ${r#*:} $OUT/check_cells.csv $OUT/${r%%:*}_check_counts.npz &
done
[[ -f $OUT/glass_lai_L2.csv ]] || python -I $REPO/scripts/defaults/cell_lai.py $DATA/raw/glass_lai_2016_500m $CELLS $OUT/glass_lai_L2.csv &
wait
