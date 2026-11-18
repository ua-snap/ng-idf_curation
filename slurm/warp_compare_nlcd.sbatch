#!/bin/bash
#SBATCH --job-name=ngidf-warp-nlcd
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate snap-geo; set -u
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
python -I /import/home/jdpaul3/ng-idf_curation/scripts/defaults/warp_compare.py \
  $DATA/raw/nlcd_2016_ak/NLCD_2016_Land_Cover_AK_20200724.img \
  /beegfs/SNAP/rltorgerson/Oct-NG-IDF/NG_IDF_AWS/static/gridcell_current_lulc.csv $DATA/work/defaults_inference
