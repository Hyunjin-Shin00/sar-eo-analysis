#!/bin/bash
# StaMPS steps, run from INSAR_20260420. Sequential over patches (stamps.py
# already loops), bounded fork workers, hard memory cap.
set -u
R=<DATA_ROOT>/CSK_PSInSAR
source "$R/code/psi_env.sh"
S=${1:?start step}; E=${2:?end step}
export PSI_MAX_WORKERS=${PSI_MAX_WORKERS:-8}
MEM=${MEM:-80G}
cd "$R/seoul/psi/INSAR_20260420"
echo "START $(date +'%F %H:%M:%S')  steps $S..$E  PSI_MAX_WORKERS=$PSI_MAX_WORKERS  MemoryMax=$MEM"
systemd-run --user --scope -q -p MemoryMax="$MEM" -p MemorySwapMax=0 \
  python -u "$PSI_PYTHON/stamps.py" -s "$S" -e "$E"
echo "EXIT=$?"
echo "END $(date +'%F %H:%M:%S')"
