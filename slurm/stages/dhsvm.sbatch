#!/bin/bash
# Pipeline stage job (dhsvm): build DHSVM from the pinned app source.
#SBATCH --job-name=ngidf-dhsvm
#SBATCH --partition=t2small
#SBATCH --qos=tier2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00
REPO=$(sed -n 's/^REPO=//p' "$1" | tr -d "'"); source "$REPO/config/env.sh" "$1"
ngidf_activate "$NGIDF_ENV"
bash "$REPO/scripts/setup/build_dhsvm.sh" "$APP_DIR/dhsvm/no_sat_dump" "$STAGE_DIR/build" "$OUT"
