#!/bin/bash
#SBATCH --job-name=ngidf-dwindfix
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
DATA=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data
$DATA/envs/msim/bin/python -I -W ignore /import/home/jdpaul3/ng-idf_curation/ngidf/daymet_forcing.py compact-wind --wind-dir $DATA/work/daymet_wind
