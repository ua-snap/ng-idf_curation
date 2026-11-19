#!/bin/bash
# Pipeline stage job (runs, array): one slice of the run manifest, 16 runs in parallel in node-local /tmp.
# Args: <job.env> <ntasks>
#SBATCH --job-name=ngidf-runs
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=06:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
work=${TMPDIR:-/tmp}/ngidf_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}; mkdir -p "$work"; trap 'rm -rf "$work"' EXIT
python -I "$REPO/ngidf/run_batch.py" run --manifest "$STAGE_DIR/manifest.csv" --task "$SLURM_ARRAY_TASK_ID" \
    --ntasks "${2:?ntasks}" --workers 16 --app-dir "$APP_DIR" --dhsvm-bin "$DHSVM_BIN" --out-root "$OUT" --work-root "$work"
