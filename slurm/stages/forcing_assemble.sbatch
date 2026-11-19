#!/bin/bash
# Pipeline stage job (forcing_<dataset>): assemble station files and/or validate against the author's files.
# Args: <job.env> assemble|validate
#SBATCH --job-name=ngidf-fassemble
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=03:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
mode=${2:?assemble|validate}
case $DATASET in
  WRF_historical) ref=$AUTHOR_FORCING_ROOT/dhsvm_wrf_1hour/hist;;
  WRF_medium) ref=$AUTHOR_FORCING_ROOT/dhsvm_wrf_1hour/medium;;
  WRF_high) ref=$AUTHOR_FORCING_ROOT/dhsvm_wrf_1hour/high;;
  CESM_hist_LE*) ref=$AUTHOR_FORCING_ROOT/dhsvm_cesm_1hour/hC2LE${DATASET##*LE};;
  CESM_futu_LE*) ref=$AUTHOR_FORCING_ROOT/dhsvm_cesm_1hour/fC2LE${DATASET##*LE};;
  *) echo "unknown dataset $DATASET" >&2; exit 2;;
esac
if [[ $mode == assemble ]]; then
    /usr/bin/time -v python -I "$REPO/ngidf/forcing.py" assemble --dataset "$DATASET" --places "$PLACES_CSV" \
        --block-dir "$STAGE_DIR/blocks" --out-dir "$OUT" --workers 8
fi
python -I "$REPO/ngidf/forcing.py" validate --ours-dir "$OUT/$DATASET" --ref-dir "$ref" \
    --places "$PLACES_CSV" --json "$OUT/validation.json" > "$STAGE_DIR/logs/validation.txt"
tail -2 "$STAGE_DIR/logs/validation.txt"
