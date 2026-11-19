#!/bin/bash
# Pipeline stage job (inputs): verify source-data checksums and list the read-only forcing archives.
# Submitted by ngidf/pipeline.py or the Prefect flow:  sbatch slurm/stages/inputs.sbatch <job.env> "<raw dirs>"
#SBATCH --job-name=ngidf-inputs
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=8G
#SBATCH --time=02:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
python -I "$REPO/ngidf/inputs_audit.py" --data-root "$DATA_ROOT" --raw-dirs $2 --pixel-dir "$DATA_ROOT/raw/daymet_v4_pixels" \
    --out "$OUT/inputs.json" --workers 8
