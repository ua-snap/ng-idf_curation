# Sourced by every pipeline Slurm script:  source <repo>/config/env.sh <job.env>
# job.env is written by ngidf/pipeline.py and holds absolute paths (REPO, DATA_ROOT, STAGE_DIR, env
# prefixes, ...), so a job does not depend on the environment of the shell that submitted it.
set -euo pipefail
[[ -f "${1:?job.env}" ]] || { echo "job env file not found: $1" >&2; exit 2; }
set -a; source "$1"; set +a
: "${REPO:?}" "${DATA_ROOT:?}" "${STAGE_DIR:?}"
export OMP_NUM_THREADS=1 HDF5_USE_FILE_LOCKING=FALSE
# Activate a conda prefix env (sets CC/CFLAGS etc. for the compiler packages too).
ngidf_activate() {
    local base="${CONDA_BASE:-}"
    [[ -n "$base" ]] || base=$(conda info --base 2>/dev/null || true)
    [[ -n "$base" ]] || base="$HOME/miniconda3"
    # shellcheck disable=SC1091
    source "$base/etc/profile.d/conda.sh"
    set +u; conda activate "${1:?env prefix}"; set -u
}
echo "job $SLURM_JOB_ID${SLURM_ARRAY_TASK_ID:+[$SLURM_ARRAY_TASK_ID]} on $(hostname) stage=$STAGE_NAME repo=$REPO@$CURATION_COMMIT"
