#!/bin/bash
set -u
S1=<DATA_ROOT>/S1_PSInSAR
for s in 2 3 4 5; do
  echo "===== STEP $s ====="
  env PSI_MAX_WORKERS=16 MEM=80G "$S1/code/run_stamps_s1.sh" $s $s || { echo "ABORT at step $s"; exit 1; }
done
echo "CHAIN DONE"
