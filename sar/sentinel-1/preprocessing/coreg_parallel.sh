#!/usr/bin/env bash
# 부산(신규 코레지) 지역 처리: 코레지(run_files 병렬) → PS+SBAS(process_region.sh)
# usage: process_busan.sh REGION "TITLE" S N W E WORK MASTER SINKLAT SINKLON NP
set -u
REGION=$1; TITLE=$2; S=$3; N=$4; W=$5; E=$6; WORK=$7; MASTER=$8; SINKLAT=$9; SINKLON=${10}; NP=${11:-8}
STACK=$WORK/stack
source ${DATA_ROOT}/CLAB/regions/seoul/workspace/stamps_seoul/env_seoul.sh 2>/dev/null
export PROJ_DATA=$(python3 -c "import pyproj;print(pyproj.datadir.get_data_dir())" 2>/dev/null); export PROJ_LIB=$PROJ_DATA
CST=$WORK/coreg_status.txt
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$CST"; }
die(){ say "CObeg FAILED: $*"; exit 1; }
cd "$STACK" || die "cd stack"
say "===== $REGION 코레지 시작 (NP=$NP 병렬) ====="
for rf in $(ls run_files/run_* | sort -V); do
  n=$(basename "$rf"); ncmd=$(grep -cve '^\s*$' "$rf")
  say "실행 $n ($ncmd cmds, 병렬 $NP)"; t0=$(date +%s)
  LOGF="$WORK/log_${n}.log"; : > "$LOGF"
  while IFS= read -r cmd; do
    [ -z "$cmd" ] && continue
    ( eval "$cmd" ) >> "$LOGF" 2>&1 &
    while [ "$(jobs -rp | wc -l)" -ge "$NP" ]; do wait -n; done
  done < "$rf"
  wait
  t1=$(date +%s)
  say "완료 $n ($((t1-t0))s)"
  # run_01(topo) 직후 geom_reference 생성 검증 — DEM 문제 등 조기감지
  if [ "$n" = "run_01_unpack_topo_reference" ]; then
    if [ -z "$(find "$STACK/geom_reference" -name '*.rdr' 2>/dev/null | head -1)" ]; then
      die "run_01 topo 실패: geom_reference 비어있음 (DEM .vrt/커버리지 확인) — 로그 $LOGF"
    fi
    say "  topo geom_reference 확인 OK"
  fi
done
nslc=$(ls "$STACK/merged/SLC" 2>/dev/null | wc -l)
say "코레지 완료 — merged SLC ${nslc}개"
[ "$nslc" -lt 2 ] && die "merged SLC 부족($nslc) — 코레지 실패 의심"
# ---- PS + SBAS ----
say "===== $REGION PS+SBAS 착수 ====="
bash ${DATA_ROOT}/CLAB/analysis/insar_bin/process_region.sh "$REGION" "$TITLE" "$S" "$N" "$W" "$E" "$STACK" "$MASTER" "$SINKLAT" "$SINKLON"
say "===== $REGION 전체(코레지+PS+SBAS) 완료 ====="
