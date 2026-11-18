#!/bin/bash
# Fit the elevation the author used for one Daymet cell. Usage: sbatch slurm/metsim_elev_fit.sbatch <daymet_key> <wrf_key> <elev...>
#SBATCH --job-name=ngidf-elevfit
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation; DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
key=$1; wkey=$2; shift 2
for e in "$@"; do
  ( $DATA/envs/msim/bin/python -I -W ignore $REPO/scripts/daymet/metsim_probe.py $key $wkey $DATA/work/metsim_probe/elev_${key}_$e \
      1989-06-01 1990-05-31 elev=$e dec31=mean 2>&1 | grep -E "opts=| SW | LW |RH " | tr '\n' ' '; echo ) &
done
wait
