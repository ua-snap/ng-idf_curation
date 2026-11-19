#!/bin/bash
# Pipeline stage job (forcing_Daymet, array over years): daily WRF-historical wind for the Daymet cells.
#SBATCH --job-name=ngidf-dwind
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G
#SBATCH --time=02:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
"$MSIM_ENV/bin/python" -I -W ignore "$REPO/ngidf/daymet_forcing.py" wind --places "$PLACES_CSV" \
    --index "$SLURM_ARRAY_TASK_ID" --out-dir "$OUT/wind" --workers 8
