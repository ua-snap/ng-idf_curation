#!/bin/bash
# Usage: sbatch --array=0-<N-1> slurm/run_batch.sbatch <manifest.csv> <N>
#SBATCH --job-name=ngidf-runs
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=06:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%A_%a.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
source $REPO/config/app.env
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate "$NGIDF_ENV"; set -u
export OMP_NUM_THREADS=1
manifest=${1:?manifest}; n=${2:?ntasks}
work=/tmp/ngidf_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}; mkdir -p $work; trap 'rm -rf $work' EXIT
python -I $REPO/ngidf/run_batch.py run --manifest "$manifest" --task $SLURM_ARRAY_TASK_ID --ntasks $n --workers 16 \
    --app-dir $DATA_ROOT/app/NG_IDF_AWS --dhsvm-bin $DATA_ROOT/build/dhsvm_${APP_COMMIT:0:7}/DHSVM3.2 \
    --out-root $DATA_ROOT/runs --work-root $work
