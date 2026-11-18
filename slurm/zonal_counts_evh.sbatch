#!/bin/bash
#SBATCH --job-name=ngidf-zonal-evh
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
# Count LANDFIRE 2016 EVH AK codes inside each NG-IDF defaults 1 km cell, then test height rules.
set -euo pipefail
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate snap-geo; set -u
REPO=/import/home/jdpaul3/ng-idf_curation
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
CELLS=/beegfs/SNAP/rltorgerson/Oct-NG-IDF/NG_IDF_AWS/static/gridcell_current_lulc.csv
LF=$DATA/raw/landfire_evh_2016_ak
TIF=$LF/LF2016_EVH_AK/Tif/LF2016_EVH_AK.tif
[[ -f $TIF ]] || (cd $LF && unzip -o LF2016_EVH_AK.zip)
python -I $REPO/scripts/defaults/zonal_counts.py $TIF $CELLS $DATA/work/defaults_inference/evh2016_counts.npz
python -I $REPO/scripts/defaults/infer_height.py $DATA/work/defaults_inference/evh2016_counts.npz $CELLS
