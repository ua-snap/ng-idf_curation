#!/bin/bash
# Usage: sbatch --array=0-<nblocks-1> slurm/forcing_block.sbatch <dataset> [places_csv] [block_dir]
#SBATCH --job-name=ngidf-fblock
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
source $REPO/config/app.env
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate "$NGIDF_ENV"; set -u
export OMP_NUM_THREADS=1 HDF5_USE_FILE_LOCKING=FALSE
ds=${1:?dataset}
/usr/bin/time -v python -I $REPO/ngidf/forcing.py block --dataset "$ds" --index "$SLURM_ARRAY_TASK_ID" \
    --places ${2:-$REPO/data/places/places_ak.csv} --out-dir ${3:-$DATA_ROOT/work/forcing_blocks} --workers 8
