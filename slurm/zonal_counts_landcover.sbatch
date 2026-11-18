#!/bin/bash
#SBATCH --job-name=ngidf-zonal-lc
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
# Count NLCD 2016 AK and NALCMS 2015 classes inside each NG-IDF defaults 1 km cell.
set -euo pipefail
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate snap-geo; set -u
REPO=/import/home/jdpaul3/ng-idf_curation
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
CELLS=/beegfs/SNAP/rltorgerson/Oct-NG-IDF/NG_IDF_AWS/static/gridcell_current_lulc.csv
NLCD_DIR=$DATA/raw/nlcd_2016_ak
mkdir -p $DATA/work/defaults_inference
if [[ ! -f $NLCD_DIR/NLCD_2016_Land_Cover_AK_20200724.img ]]; then
    (cd $NLCD_DIR && unzip -o NLCD_2016_Land_Cover_AK_20200724.zip)
fi
python -I $REPO/scripts/defaults/zonal_counts.py $NLCD_DIR/NLCD_2016_Land_Cover_AK_20200724.img $CELLS \
    $DATA/work/defaults_inference/nlcd2016_counts.npz
python -I $REPO/scripts/defaults/zonal_counts.py /import/beegfs/SNAP/rltorgerson/data/alaska_wildfires/land_cover_2015.tif $CELLS \
    $DATA/work/defaults_inference/nalcms2015_counts.npz
