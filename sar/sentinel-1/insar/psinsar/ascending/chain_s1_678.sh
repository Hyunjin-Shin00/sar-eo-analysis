#!/bin/bash
set -u
S1=<DATA_ROOT>/S1_PSInSAR
echo "===== STEP 6 (언래핑) ====="
env PSI_MAX_WORKERS=16 MEM=96G "$S1/code/run_stamps_s1.sh" 6 6 || { echo "ABORT step6"; exit 1; }
echo "===== STEP 7~8 (SCLA + 대기필터) ====="
env PSI_MAX_WORKERS=16 MEM=96G "$S1/code/run_stamps_s1.sh" 7 8 || { echo "ABORT step78"; exit 1; }
echo "CHAIN DONE"
