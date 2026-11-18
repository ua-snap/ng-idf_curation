#!/bin/bash
# MetSim Daymet station files.
# Usage: sbatch --array=0-<N-1> slurm/daymet_run.sbatch <N> [wind=<dir>] [out=<dir>] [--overwrite]
#SBATCH --job-name=ngidf-dmetsim
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%A_%a.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
export HDF5_USE_FILE_LOCKING=FALSE OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1
n=${1:?ntasks}; shift; wind=$DATA/work/daymet_wind; out=$DATA/work/forcing/Daymet; extra=""
for a in "$@"; do case $a in wind=*) wind=${a#wind=};; out=*) out=${a#out=};; *) extra="$extra $a";; esac; done
work=/tmp/ngidf_msim_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}; mkdir -p $work; trap 'rm -rf $work' EXIT
$DATA/envs/msim/bin/python -I -W ignore $REPO/ngidf/daymet_forcing.py run --wind-dir $wind \
    --pixel-dir $DATA/raw/daymet_v4_pixels --out-dir $out \
    --task $SLURM_ARRAY_TASK_ID --ntasks $n --workers 16 --work-root $work $extra
