#!/bin/bash
# 수도권 광역 SBAS 타일 러너 (v3)
#  - 동시 실행 상한을 '실제 run_sbas_tile.py 프로세스 수'로 제어(MAXPROC).
#    여유 RAM 기준 게이트는 크롭 중 점진 증가분을 못 막아 OOM을 냈다(t22 손실).
#  - python을 락을 쥔 채로 띄우고 30초 대기해, 다음 대기자가 낡은 카운트를 읽는 경합을 막는다.
#  - .claim(mkdir 원자성)으로 타일 선점, tile_meta.json 있으면 완료로 보고 건너뜀.
set -u
PY=${CONDA_PREFIX}/bin/python
BIN=${DATA_ROOT}/CLAB/analysis/insar_bin
MERGED=${MERGED:?}
ROOT=${ROOT:?}
LOGS=${LOGS:?}
MAXPROC=${MAXPROC:-24}
PREFIX=${PREFIX:-}
TJ=${TJ:-tiles.json}      # 타일 정의 파일명
TD=${TD:-tiles}          # 타일 출력 하위디렉토리
RESERVE=${RESERVE:-25}   # 새 타일을 들일 때 요구하는 여유 RAM(GB)
mkdir -p "$LOGS" "$ROOT/$TD"
echo "[$(date '+%F %T')] ===== 러너 v4 시작 (상한 $MAXPROC, 여유RAM ${RESERVE}GB) ====="

count_tiles() {
  local n=0 c
  for p in /proc/[0-9]*; do
    c=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null) || continue
    case "$c" in
      *"$BIN"/run_sbas_tile.py*) n=$((n+1)) ;;
    esac
  done
  echo $n
}

$PY - "$ROOT/$TJ" "$ROOT/$TD" <<'PYE' > "$ROOT/_tasklist.txt"
import json,sys,os
d=json.load(open(sys.argv[1])); TD=sys.argv[2]
for t in sorted(d['tiles'], key=lambda x:-(x.get('n_acc') or x.get('parent_acc') or 0)):
    b=os.path.join(TD,t['name'])
    if os.path.exists(os.path.join(b,'tile_meta.json')) or os.path.exists(os.path.join(b,'.claim')): continue
    print(t['name'], *t['win'])
PYE
echo "[$(date '+%F %T')] 실행 대상 $(wc -l < "$ROOT/_tasklist.txt") 타일 (현재 실행중 $(count_tiles))"

run_one() {
  set -- $1
  nm=$1; r0=$2; r1=$3; c0=$4; c1=$5
  mkdir -p "$ROOT/$TD/$nm"
  mkdir "$ROOT/$TD/$nm/.claim" 2>/dev/null || return 0
  # 9>&- 필수: 락을 쥔 채 python을 띄우면 자식이 fd9를 상속해
  # 서브셸이 끝나도 락이 안 풀린다(타일 1개가 끝날 때까지 전체가 막힘).
  ( flock 9
    # 상한(프로세스 수)과 여유 RAM을 함께 본다. v1은 타일당 ~14GB로 커져 RAM게이트만으론
    # OOM을 냈지만(t22), v3는 피크 ~6GB라 두 조건을 병용하면 혼재 상태에서도 안전하다.
    while [ "$(count_tiles)" -ge "$MAXPROC" ] ||           [ "$(free -g | awk 'NR==2{print $7}')" -lt "$RESERVE" ]; do sleep 30; done
    echo "[$(date '+%F %T')] >>> $nm 시작 (R$r0:$r1 C$c0:$c1)"
    env -u PYTHONPATH OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
      "$PY" "$BIN/run_sbas_tile.py" --merged "$MERGED" --win "$r0" "$r1" "$c0" "$c1" \
      --out "$ROOT/$TD/$nm" --region "${PREFIX}$nm" > "$LOGS/$nm.log" 2>&1 9>&- &
    echo $! > "$ROOT/$TD/$nm/.pid"
    sleep 30
  ) 9>"$ROOT/.startlock2"
  pid=$(cat "$ROOT/$TD/$nm/.pid" 2>/dev/null)
  while [ -n "$pid" ] && [ -d "/proc/$pid" ]; do sleep 30; done
  if [ -f "$ROOT/$TD/$nm/tile_meta.json" ]; then
    echo "[$(date '+%F %T')] <<< $nm 완료  $(grep -o '채택 [0-9]*/[0-9]*' "$LOGS/$nm.log" | tail -1)"
  else
    rm -rf "$ROOT/$TD/$nm/.claim"
    echo "[$(date '+%F %T')] !!! $nm 실패  $(tail -2 "$LOGS/$nm.log" 2>/dev/null | tr '\n' ' ' | cut -c1-160)"
  fi
}
export -f run_one count_tiles; export PY BIN MERGED ROOT LOGS MAXPROC RESERVE PREFIX TD TJ

cat "$ROOT/_tasklist.txt" | xargs -d'\n' -I{} -P "${XP:-24}" bash -c 'run_one "$@"' _ {}
while [ "$(count_tiles)" -gt 0 ]; do sleep 60; done
echo "[$(date '+%F %T')] ===== 전체 종료: 완료 타일 $(ls -d "$ROOT"/$TD/*/tile_meta.json 2>/dev/null | wc -l)/$(python3 -c "import json;print(len(json.load(open('$ROOT/$TJ'))['tiles']))") ====="
