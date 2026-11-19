#!/bin/bash
#SBATCH --job-name=ngidf-sens
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
set -a; source $REPO/config/paths.env; source $REPO/config/model_versions/a582a5c.env; set +a; NGIDF_ENV=$DATA_ROOT/envs/ngidf  # research job, outside the pipeline
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate "$NGIDF_ENV"; set -u
python -I $REPO/scripts/tests/sensitivity_defaults.py $DATA_ROOT/work/sensitivity/$SLURM_JOB_ID $DATA_ROOT/build/dhsvm_${APP_COMMIT:0:7}/DHSVM3.2
