#!/bin/bash
# DSC topsStack run_01~08 순차 실행. 각 단계 내부만 xargs -P 로 병렬.
# GNU parallel 은 이 환경에 없다 — 기존 CSK run_step.sh 와 같은 xargs 방식을 쓴다.
# 서버가 이미 타 세션으로 load ~48 이라 병렬은 4로 낮춰 잡는다.
set -u
D=<DATA_ROOT>/S1_DSC
JOBS="${1:-4}"; MEM="${2:-40G}"
source <DATA_ROOT>/CSK_PSInSAR/code/psi_env.sh
export PATH="$CONDA_PREFIX/share/isce2/topsStack:$PATH"
cd "$D/stack"

run_line() {
  idx="$1"; cmd="$2"
  if eval "$cmd" > "$LG/line_${idx}.log" 2>&1; then echo "  OK   [$idx]"
  else echo "  FAIL [$idx] -> $LG/line_${idx}.log"; fi
}
export -f run_line

date +'COREG START %F %H:%M:%S'
for RF in run_files/run_0*; do
  step=$(basename "$RF"); export LG="$D/logs/coreg/$step"; mkdir -p "$LG"
  n=$(grep -cve '^\s*$' "$RF")
  j=$JOBS; [ "$n" -le 2 ] && j=1
  echo "[$(date +%H:%M:%S)] $step : ${n}개, 병렬 $j"
  grep -ve '^\s*$' "$RF" | nl -ba -w1 -s$'\t' \
    | systemd-run --user --scope -q -p MemoryMax="$MEM" -p MemorySwapMax=0 \
        xargs -d'\n' -I{} -P "$j" bash -c 'l="{}"; idx="${l%%	*}"; cmd="${l#*	}"; run_line "$idx" "$cmd"'
  nf=$(grep -lE "Traceback|Error" "$LG"/line_*.log 2>/dev/null | wc -l)
  echo "[$(date +%H:%M:%S)] $step 종료 (오류로그 $nf개)"
  if [ "$nf" -gt 0 ]; then echo "  !! $step 실패 — 중단"; exit 1; fi
done
date +'COREG END %F %H:%M:%S'
