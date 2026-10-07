#!/bin/bash
set -u
R=<DATA_ROOT>/CSK_PSInSAR
S1=<DATA_ROOT>/S1_PSInSAR
source "$R/code/psi_env.sh"
S=${1:?start}; E=${2:?end}
export PSI_MAX_WORKERS=${PSI_MAX_WORKERS:-16}
cd "$S1/INSAR_20241208"
echo "START $(date +'%F %H:%M:%S')  steps $S..$E  workers=$PSI_MAX_WORKERS  MemoryMax=${MEM:-80G}"
systemd-run --user --scope -q -p MemoryMax="${MEM:-80G}" -p MemorySwapMax=0 \
  python -u "$PSI_PYTHON/stamps.py" -s "$S" -e "$E"
echo "EXIT=$?"
echo "END $(date +'%F %H:%M:%S')"
