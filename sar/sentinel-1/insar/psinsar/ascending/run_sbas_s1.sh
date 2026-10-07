#!/bin/bash
set -u
R=<DATA_ROOT>/CSK_PSInSAR
S1=${S1_ROOT:-<DATA_ROOT>/S1_PSInSAR}
export S1_ROOT="$S1"
source "$R/code/psi_env.sh"
SS=$CONDA_PREFIX/share/isce2/stripmapStack
SB=$S1/sbas
JOBS=${JOBS:-12}
LOG=$S1/logs/sbas; mkdir -p "$LOG"
# 언랩 산출물 크기는 크롭박스와 멀티룩(8rg x 2az)에서 유도한다 — 궤도마다 다르다.
EXP=$(python3 -c "import json;b=json.load(open('$S1/crop_box.json'));print(((b['R1']-b['R0'])//2)*((b['C1']-b['C0'])//8)*8)")
do_pair() {
  a=$1; b=$2; p="${a}_${b}"; d="$SB/Igrams/$p"
  mkdir -p "$d"; cd "$d" || return 1
  [ -s "filt_${p}.unw" ] && [ "$(stat -c%s "filt_${p}.unw")" = "$EXP" ] && { echo "SKIP $p"; return 0; }
  t0=$(date +%s)
  python3 -c "
import sys; sys.path.insert(0,'<DATA_ROOT>/S1_PSInSAR/code'); import sbas_lib_s1 as S
S.make_ifg('$a','$b','$d')" > "$LOG/$p.ifg.log" 2>&1 || { echo "FAIL $p ifg"; return 1; }
  python3 "$SS/FilterAndCoherence.py" -i "${p}.int" -f "filt_${p}.int" -c "filt_${p}.cor" -s 0.5 \
     > "$LOG/$p.filt.log" 2>&1 || { echo "FAIL $p filt"; return 1; }
  python3 "<DATA_ROOT>/S1_PSInSAR/code/unwrap_s1.py" -i "filt_${p}.int" -c "filt_${p}.cor" -u "filt_${p}.unw" -r 8 -a 2 \
     > "$LOG/$p.unw.log" 2>&1 || { echo "FAIL $p unw"; return 1; }
  rm -f "${p}.int" "${p}.int.vrt" "${p}.int.xml"
  echo "OK   $p  $(( $(date +%s) - t0 ))s"
}
export -f do_pair; export R S1 SS SB LOG EXP
date +'START %F %H:%M:%S'
awk '{print $1,$2}' "$SB/pairs.txt" | xargs -P "$JOBS" -n2 bash -c 'do_pair "$@"' _
date +'END %F %H:%M:%S'
