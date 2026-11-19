#!/bin/bash
# Pipeline stage job (qa): run QA, comparison with the baseline release, HTML report.
#SBATCH --job-name=ngidf-qa
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
export MPLCONFIGDIR=$STAGE_DIR/.mpl
py="$REPORT_ENV/bin/python -I"
$py "$REPO/ngidf/qa/run_qa.py" --runs-root "$RUNS_ROOT" --manifest "$MANIFEST" --coverage-dir "$COVERAGE_DIR" \
    --places "$PLACES_CSV" --defaults "$DEFAULTS_CSV" --out-dir "$OUT"
cmp_args=()
if [[ -n $BASELINE_COVERAGE ]]; then
    $py "$REPO/ngidf/qa/compare_release.py" --current "$COVERAGE_DIR" --baseline "$BASELINE_COVERAGE" \
        --defaults "$DEFAULTS_CSV" --places "$PLACES_CSV" --out-dir "$OUT/compare" \
        --label-current "$MODEL_LABEL (this release)" --label-baseline "$BASELINE_LABEL"
    cmp_args=(--compare "$OUT/compare")
fi
mc_args=(); [[ -n $MODEL_CHANGE_JSON ]] && mc_args=(--model-change "$MODEL_CHANGE_JSON")
$py "$REPO/ngidf/qa/report.py" --stages "$STAGE_DIR/stages.json" --qa "$OUT" "${cmp_args[@]}" "${mc_args[@]}" \
    --title "$REPORT_TITLE" --out "$OUT/report.html"
