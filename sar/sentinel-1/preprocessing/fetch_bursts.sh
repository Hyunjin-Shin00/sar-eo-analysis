#!/usr/bin/env bash
# ASF BURST 제품을 받아 SAFE 로 조립한다(전체 SLC 대비 8~10배 절약).
# 사용: fetch_bursts.sh <출력루트> "<W S E N>" <subswath> <라벨:절대궤도> ...
# 주의 ① b2s 환경은 PROJ_DATA 를 명시하지 않으면 osgeo 가 proj.db 를 못 연다.
#      ② 날짜마다 별도 디렉터리에 받는다(공용 디렉터리면 서로 간섭한다).
set -uo pipefail
B=${B2S_ENV:-$CONDA_PREFIX}   # conda env with burst2safe
LOG=${LOG_DIR:-/tmp}
OUT=$1; EXT=$2; SW=$3; shift 3
export PROJ_DATA="$B/share/proj" PROJ_LIB="$B/share/proj" GDAL_DATA="$B/share/gdal"
ok() { ls "$1"/*.SAFE/annotation/*.xml >/dev/null 2>&1; }

for kv in "$@"; do
  k=${kv%%:*}; orb=${kv##*:}
  D="$OUT/$k"
  if ok "$D"; then echo "건너뜀 $k"; continue; fi
  rm -rf "$D"; mkdir -p "$D"
  echo "── $k  절대궤도 $orb  $SW  $(date +%H:%M:%S)"
  for try in 1 2; do
    ( cd "$D" && env -u PYTHONPATH "$B/bin/burst2safe" --orbit "$orb" --extent $EXT \
        --pols VV --swaths "$SW" --min-bursts 2 --output-dir . -v ) > "$LOG/b2s_$(basename "$OUT")_$k.log" 2>&1
    ok "$D" && break
    echo "   재시도 $try  ($(tail -1 "$LOG/b2s_$(basename "$OUT")_$k.log"))"
  done
  if ok "$D"; then rm -f "$D"/*.tiff "$D"/*_VV.xml; du -sh "$D"/*.SAFE
  else echo "   ★실패 $k"; fi
done
echo "── 완료 $(date +%H:%M:%S)"; du -sh "$OUT"/*/*.SAFE 2>/dev/null
