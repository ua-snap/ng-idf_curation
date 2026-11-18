#!/bin/bash
# Usage: sbatch slurm/metsim_probe.sbatch <daymet_key> <wrf_key> <tag> [start stop] [key=value ...]
#SBATCH --job-name=ngidf-metsim
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
key=$1; wkey=$2; tag=$3; start=${4:-1989-06-01}; stop=${5:-2021-09-30}; shift 5 || shift $#
rm -rf $DATA/work/metsim_probe/$tag
$DATA/envs/msim/bin/python -I -W ignore $REPO/scripts/daymet/metsim_probe.py $key $wkey $DATA/work/metsim_probe/$tag $start $stop "$@"
