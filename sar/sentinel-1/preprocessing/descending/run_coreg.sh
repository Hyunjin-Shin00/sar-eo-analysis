#!/usr/bin/env bash
# SETUP 완료 후 남은 run_files(run_02~run_13) 병렬 코레지.
# usage: run_coreg_dsc.sh <t061|t134> [NP]
# DSC_incheon/run_coreg_ps.sh 의 실행 패턴을 그대로 따름(run_01 은 SETUP 서 완료).
set -u
source ${WORK_ROOT}/CLAB_DSC/env_isce2_dsc.sh
export PROJ_DATA=$(${CONDA_PREFIX}/bin/python -c "import pyproj;print(pyproj.datadir.get_data_dir())" 2>/dev/null)
export PROJ_LIB=$PROJ_DATA

TAG=${1:?사용법: run_coreg_dsc.sh <t061|t134> [NP]}
NP=${2:-4}
case "$TAG" in
  t061) WORK=$DSC_ROOT/proc_t061_busan;  NAME='부산 (path61/f475)' ;;
  t134) WORK=$DSC_ROOT/proc_t134_capital; NAME='수도권 (path134/f466)' ;;
  *) echo "TAG 는 t061 또는 t134"; exit 1 ;;
esac
STACK=$WORK/stack
ST=$WORK/coreg_status.txt
MASTER=$(cat "$WORK/MASTER.txt" 2>/dev/null || echo "?")
say() { echo "[$(date '+%F %T')] $*" | tee -a "$ST"; }
die() { say "COREG FAILED: $*"; exit 1; }

[ -f "$WORK/SETUP_DONE" ] || die "SETUP 미완료 — setup_coreg_dsc.sh $TAG 먼저 실행"
cd "$STACK" || die "cd stack"

say "===== 코레지 시작 $NAME (run_02~run_13, NP=$NP) master=$MASTER ====="
for rf in $(ls run_files/run_* | sort -V); do
  n=$(basename "$rf")
  case "$n" in run_01_*) say "skip $n (SETUP서 완료)"; continue;; esac
  [ -f "$WORK/DONE_$n" ] && { say "skip $n (이미 완료)"; continue; }
  ncmd=$(grep -cve '^\s*$' "$rf")
  say "실행 $n ($ncmd cmds, 병렬 $NP)"; t0=$(date +%s)
  LOGF="$WORK/log_${n}.log"; : > "$LOGF"
  fail=0; nskip=0
  # run_12 는 DONE 플래그가 단계 단위라 OOM 재시작 때마다 완성된 merged SLC 까지 다시 쓴다
  # (씬당 2.9 GB · 약 2분). 완성된 것은 건너뛴다.
  # 완성 판정 = .slc.full 크기가 최다빈도 크기와 일치. 잘린 파일은 크기가 작아 자동으로 재작업된다.
  # 최다빈도가 10개 미만이면(초기 실행) 기준을 신뢰할 수 없으므로 skip 을 켜지 않는다.
  SKIP_MERGE=0; EXPECT=""
  case "$n" in
    run_12_merge*)
      EXPECT=$(find "$STACK/merged/SLC" -name '*.slc.full' -printf '%s\n' 2>/dev/null \
               | sort | uniq -c | sort -rn | awk 'NR==1 && $1>=10 {print $2}')
      [ -n "$EXPECT" ] && { SKIP_MERGE=1; say "  재개: .slc.full 크기 ${EXPECT}B 인 씬은 건너뜀"; } ;;
  esac
  while IFS= read -r cmd; do
    [ -z "$cmd" ] && continue
    if [ "$SKIP_MERGE" = 1 ]; then
      d=$(printf '%s' "$cmd" | sed -n 's/.*config_merge_\([0-9]\{8\}\).*/\1/p')
      if [ -n "$d" ] && [ "$(stat -c%s "$STACK/merged/SLC/$d/$d.slc.full" 2>/dev/null || echo 0)" = "$EXPECT" ]; then
        nskip=$((nskip+1)); continue
      fi
    fi
    ( eval "$cmd" ) >> "$LOGF" 2>&1 &
    while [ "$(jobs -rp | wc -l)" -ge "$NP" ]; do wait -n || fail=$((fail+1)); done
  done < "$rf"
  while [ "$(jobs -rp | wc -l)" -gt 0 ]; do wait -n || fail=$((fail+1)); done
  t1=$(date +%s)
  [ "$nskip" -gt 0 ] && say "  건너뜀 ${nskip}건 (이미 완성)"
  if [ "$fail" -gt 0 ]; then
    say "완료 $n ($((t1-t0))s) — ★비정상종료 ${fail}건 (로그: $LOGF)"
  else
    say "완료 $n ($((t1-t0))s)"
    touch "$WORK/DONE_$n"
  fi
done
nslc=$(ls "$STACK/merged/SLC" 2>/dev/null | wc -l)
say "코레지 종료 — merged SLC ${nslc}개"
[ "$nslc" -lt 2 ] && die "merged SLC 부족($nslc)"
touch "$WORK/COREG_DONE"
say "===== 코레지 완료 $NAME · merged SLC ${nslc}개 ====="
