#!/bin/bash
# Daily WRF-historical wind for the Daymet cells.
# Usage: sbatch --array=0-32%2 slurm/daymet_wind.sbatch [places_csv] [out_dir]
#SBATCH --job-name=ngidf-dwind
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%A_%a.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
export HDF5_USE_FILE_LOCKING=FALSE OMP_NUM_THREADS=1
$DATA/envs/msim/bin/python -I -W ignore $REPO/ngidf/daymet_forcing.py wind --places ${1:-$REPO/data/places/places_ak.csv} \
    --index $SLURM_ARRAY_TASK_ID --out-dir ${2:-$DATA/work/daymet_wind} --workers 8
