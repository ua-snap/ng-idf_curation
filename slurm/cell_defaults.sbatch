#!/bin/bash
# DHSVM defaults (land cover, LAI, height) for arbitrary 1 km cells, e.g. the neighbourhood pilot.
# <cells_csv> needs id, latitude, longitude, defaults_lat, defaults_lon, defaults_status.
# Usage: sbatch slurm/cell_defaults.sbatch <cells_csv> <work_dir> <out_csv>
#SBATCH --job-name=ngidf-celldefaults
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
cells=${1:?cells_csv}; work=${2:?work_dir}; out=${3:?out_csv}
mkdir -p $work
python -I $REPO/scripts/defaults/cell_counts.py $DATA/raw/nlcd_2016_ak/NLCD_2016_Land_Cover_AK_20200724.img $cells $work/nlcd2016_counts.npz &
python -I $REPO/scripts/defaults/cell_counts.py $DATA/raw/landfire_evh_2016_ak/LF2016_EVH_AK/Tif/LF2016_EVH_AK.tif $cells $work/evh2016_counts.npz &
python -I $REPO/scripts/defaults/cell_lai.py $DATA/raw/glass_lai_2016_500m $cells $work/glass_lai_L2.csv &
wait
python -I $REPO/scripts/defaults/build_place_defaults.py $cells $DATA/app/NG_IDF_AWS/static/gridcell_current_lulc.csv $work $out
