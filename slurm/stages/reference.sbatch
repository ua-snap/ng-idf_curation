#!/bin/bash
# Pipeline stage job (reference): reference places on the author's own forcing and defaults; compare with his app.
#SBATCH --job-name=ngidf-reference
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
work=${TMPDIR:-/tmp}/ngidf_ref_${SLURM_JOB_ID}; mkdir -p "$work"; trap 'rm -rf "$work"' EXIT
python -I "$REPO/scripts/tests/reference_runs.py" --app-dir "$APP_DIR" --dhsvm-bin "$DHSVM_BIN" \
    --places "$PLACES_CSV" --author-forcing-root "$AUTHOR_FORCING_ROOT" --hy-reference "$HY_REFERENCE" \
    --ids $REFERENCE_PLACES --datasets $REFERENCE_DATASETS --out "$OUT" --work-root "$work" --workers 15
