#!/bin/bash
# Pipeline stage job (forcing_Daymet): MetSim station files (array), or validation against the author's files.
# Args: <job.env> <ntasks>|validate
#SBATCH --job-name=ngidf-dmetsim
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=04:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
export NUMBA_NUM_THREADS=1
py="$MSIM_ENV/bin/python -I -W ignore $REPO/ngidf/daymet_forcing.py"
if [[ ${2:?ntasks|validate} == validate ]]; then
    $py validate --ours-dir "$OUT/Daymet" --places "$PLACES_CSV" --json "$OUT/validation.json" \
        > "$STAGE_DIR/logs/validation.txt"
    tail -3 "$STAGE_DIR/logs/validation.txt"
else
    work=${TMPDIR:-/tmp}/ngidf_msim_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}; mkdir -p "$work"; trap 'rm -rf "$work"' EXIT
    $py run --wind-dir "$OUT/wind" --pixel-dir "$PIXEL_DIR" --out-dir "$OUT/Daymet" \
        --task "$SLURM_ARRAY_TASK_ID" --ntasks "$2" --workers 16 --work-root "$work"
fi
