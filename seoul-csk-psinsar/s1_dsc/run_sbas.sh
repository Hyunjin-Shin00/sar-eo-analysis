#!/bin/bash
# DSC 간섭도 130쌍. ASC 와 동일한 run_sbas_s1.sh 를 S1_ROOT 만 바꿔 재사용한다.
set -u
D=<DATA_ROOT>/S1_DSC
export S1_ROOT="$D"
export JOBS="${1:-8}"
exec <DATA_ROOT>/S1_PSInSAR/code/run_sbas_s1.sh
