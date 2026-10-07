#!/bin/bash
# Execute one stripmapStack run_file with a hard memory cap and bounded parallelism.
#   run_step.sh <run_file> [JOBS] [MEMMAX]
set -u
RF="$1"; JOBS="${2:-6}"; MEM="${3:-48G}"
R=<DATA_ROOT>/CSK_PSInSAR
LOG="$R/logs/$(basename "$RF")"
mkdir -p "$LOG"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PATH="$CONDA_PREFIX/share/isce2/stripmapStack:$PATH"

n=$(grep -cve '^\s*$' "$RF")
echo "[$(date +%H:%M:%S)] $(basename "$RF"): ${n}개 작업, 병렬 ${JOBS}, 메모리상한 ${MEM}"

i=0
run_line() {
  idx="$1"; shift
  out="$LOG/line_${idx}.log"
  if eval "$@" > "$out" 2>&1; then echo "  OK   [$idx]"; else echo "  FAIL [$idx] -> $out"; return 1; fi
}
export -f run_line; export LOG

grep -ve '^\s*$' "$RF" | nl -ba -w1 -s$'\t' \
 | systemd-run --user --scope -q -p MemoryMax="$MEM" -p MemorySwapMax=0 \
     xargs -d'\n' -I{} -P "$JOBS" bash -c 'l="{}"; idx="${l%%	*}"; cmd="${l#*	}"; run_line "$idx" "$cmd"'

echo "[$(date +%H:%M:%S)] $(basename "$RF") 종료. FAIL: $(grep -c FAIL <<< "$(ls $LOG)" 2>/dev/null || echo 0)"
