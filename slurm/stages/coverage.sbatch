#!/bin/bash
# Pipeline stage job (coverage): netCDF coverages + rasdaman metadata check.
#SBATCH --job-name=ngidf-coverage
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:00:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
python -I "$REPO/ngidf/build_coverage.py" --runs-root "$RUNS_ROOT" --places "$PLACES_CSV" --defaults "$DEFAULTS_CSV" \
    --app-dir "$APP_DIR" --model-file "$MODEL_FILE" --out-dir "$OUT"
# "into" check from github.com/ua-snap/rasdaman-audit (RASDAMAN_AUDIT = a clone of it)
A=${RASDAMAN_AUDIT:-}/scripts/rasdaman_metadata_check.py
if [[ -n ${RASDAMAN_AUDIT:-} && -f $A ]]; then
    for f in "$OUT"/*.nc; do echo "== $(basename "$f")"; ncdump -h "$f" | python3 "$A" --text -; done > "$OUT/metadata_check.txt" 2>&1
fi
