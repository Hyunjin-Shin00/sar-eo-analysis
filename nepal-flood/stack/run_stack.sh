#!/usr/bin/env bash
# topsStack run_files 순차 실행.
# run_file의 각 줄은 '&'로 끝나 병렬 실행을 의도하지만, 그러면 종료코드를 잃고
# 다음 run과 경합한다. 여기서는 '&'를 제거해 순차 실행 + 종료코드 검사.
# usage: run_stack.sh <TRACK> [first] [last]
set -eu
TRK=$1; FIRST=${2:-1}; LAST=${3:-10}
source ~/miniconda3/etc/profile.d/conda.sh
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PROJ_DATA=$CONDA_PREFIX/share/proj PROJ_LIB=$CONDA_PREFIX/share/proj

WORK=${DATA_ROOT}/work/stack_${TRK}
cd "$WORK"
for f in $(ls run_files/run_* | sort -V); do
  N=$(basename "$f" | grep -oE 'run_[0-9]+' | grep -oE '[0-9]+'); N=$((10#$N))
  { [ "$N" -ge "$((10#$FIRST))" ] && [ "$N" -le "$((10#$LAST))" ]; } || { echo "SKIP $(basename $f)"; continue; }
  echo "=== START $(basename $f) ($(date +%H:%M:%S)) ==="
  mapfile -t CMDS < "$f"
  i=0
  for line in "${CMDS[@]}"; do
    line="${line%%&}"; line="$(echo "$line" | sed 's/[[:space:]]*$//')"
    [ -z "$line" ] && continue
    i=$((i+1)); echo "  -- cmd $i: ${line:0:110}"
    eval "$line" < /dev/null || { echo "FAILED_RUN=$(basename $f) cmd=$i"; exit 1; }
  done
  echo "=== DONE $(basename $f) ($(date +%H:%M:%S)) ==="
done
echo "ALL_DONE ${TRK}"
