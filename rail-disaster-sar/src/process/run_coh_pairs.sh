#!/usr/bin/env bash
# 결맞음 페어 일괄 처리(범용).
# 사용: run_coh_pairs.sh <SAFE루트> <출력접두> <subswath> "<AOI wkt>" <cohAz> <cohRg> <nRg> <pix> <a:b> ...
# SAFE루트 아래 <라벨>/ *.SAFE 구조를 전제한다(fetch_bursts.sh 산출).
set -uo pipefail
R=${WORK_ROOT:?set WORK_ROOT}
GPT=${SNAP_GPT:-gpt}
GRAPH=${GRAPH:-$R/src/process/tops_coh_single.xml}   # 버스트 SAFE(단일 subswath) 기본
O=$R/data/interim/coh; mkdir -p "$O"
SRC=$1; PFX=$2; SW=$3; AOI=$4; CAZ=$5; CRG=$6; NRG=$7; PIX=$8; shift 8
XMX=${XMX:-12G}
man() { ls "$SRC/$1"/*.SAFE/manifest.safe 2>/dev/null | head -1; }

for p in "$@"; do
  m=${p%%:*}; s=${p##*:}
  out=$O/${PFX}_${m}_${s}_${SW}_coh.tif
  if [[ -s $out ]]; then echo "건너뜀 $(basename "$out")"; continue; fi
  mz=$(man "$m"); sz=$(man "$s")
  if [[ -z $mz || -z $sz ]]; then echo "입력 없음 $m/$s"; continue; fi
  echo "── ${PFX} ${m}→${s} (${SW})  $(date +%H:%M:%S)"
  _JAVA_OPTIONS="-Xmx${XMX} -XX:MaxMetaspaceSize=512m" \
  "$GPT" "$GRAPH" -c 4G -q 4 \
     -Pmaster="$mz" -Pslave="$sz" -Paoi="$AOI" \
     -PcohAz="$CAZ" -PcohRg="$CRG" -PnRg="$NRG" -Ppix="$PIX" \
     -Pdem="SRTM 1Sec HGT" -Poutput="$out" 2>&1 | tail -3
  if [[ -s $out ]]; then ls -l "$out" | awk '{printf "   산출 %.0f MB\n", $5/1048576}'
  else echo "   ★실패"; fi
done
echo "완료 $(date +%H:%M:%S)"
