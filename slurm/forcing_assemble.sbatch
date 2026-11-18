#!/bin/bash
# Usage: sbatch slurm/forcing_assemble.sbatch <dataset>
#SBATCH --job-name=ngidf-fassemble
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=03:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
source $REPO/config/app.env
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate "$NGIDF_ENV"; set -u
ds=${1:?dataset}
NGIDL=/import/beegfs/CMIP6/arctic-cmip6/NG-IDL
case $ds in
  WRF_historical) ref=$NGIDL/dhsvm_wrf_1hour/hist;;
  WRF_medium) ref=$NGIDL/dhsvm_wrf_1hour/medium;;
  WRF_high) ref=$NGIDL/dhsvm_wrf_1hour/high;;
  CESM_hist_LE*) ref=$NGIDL/dhsvm_cesm_1hour/hC2LE${ds##*LE};;
  CESM_futu_LE*) ref=$NGIDL/dhsvm_cesm_1hour/fC2LE${ds##*LE};;
esac
/usr/bin/time -v python -I $REPO/ngidf/forcing.py assemble --dataset $ds --places $REPO/data/places/places_ak.csv \
    --block-dir $DATA_ROOT/work/forcing_blocks --out-dir $DATA_ROOT/work/forcing --workers 8
python -I $REPO/ngidf/forcing.py validate --ours-dir $DATA_ROOT/work/forcing/$ds --ref-dir $ref \
    > $DATA_ROOT/work/forcing/$ds/VALIDATION.txt
tail -2 $DATA_ROOT/work/forcing/$ds/VALIDATION.txt
