#!/bin/bash
# Usage: sbatch slurm/build_coverage.sbatch [out_subdir]
#SBATCH --job-name=ngidf-coverage
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data/logs/%x_%j.out
set -euo pipefail
REPO=/import/home/jdpaul3/ng-idf_curation
source $REPO/config/app.env
source ~/miniconda3/etc/profile.d/conda.sh
set +u; conda activate "$NGIDF_ENV"; set -u
out=$DATA_ROOT/output/${1:-coverage}
python -I $REPO/ngidf/build_coverage.py --runs-root $DATA_ROOT/runs --out-dir $out
# "into" check from github.com/ua-snap/rasdaman-audit (set RASDAMAN_AUDIT to a clone of it)
A=${RASDAMAN_AUDIT:-}/scripts/rasdaman_metadata_check.py
if [[ -f $A ]]; then for f in $out/*.nc; do ncdump -h $f | python3 $A --text -; done
else echo "RASDAMAN_AUDIT not set: skipped the metadata check"; fi
ls -la $out
