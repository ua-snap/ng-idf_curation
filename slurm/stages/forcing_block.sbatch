#!/bin/bash
# Pipeline stage job (forcing_<dataset>, array over calendar years): read each daily file once, keep the cells.
#SBATCH --job-name=ngidf-fblock
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G
#SBATCH --time=02:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
/usr/bin/time -v python -I "$REPO/ngidf/forcing.py" block --dataset "$DATASET" --index "$SLURM_ARRAY_TASK_ID" \
    --places "$PLACES_CSV" --out-dir "$STAGE_DIR/blocks" --workers 8
