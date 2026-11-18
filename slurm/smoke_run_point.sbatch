#!/bin/bash
#SBATCH --job-name=ngidf-smoke
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
source $REPO/config/app.env
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate "$NGIDF_ENV"; set -u
bash $REPO/scripts/setup/build_dhsvm.sh
BIN=$DATA_ROOT/build/dhsvm_${APP_COMMIT:0:7}/DHSVM3.2
python -I $REPO/scripts/tests/smoke_run_point.py $DATA_ROOT/work/smoke/$SLURM_JOB_ID $BIN "$@"
