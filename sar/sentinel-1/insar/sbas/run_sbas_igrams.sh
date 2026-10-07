#!/bin/bash
# SBAS pair processing: multilooked ifg -> Goldstein filter + coherence -> snaphu.
# Resumable: a pair whose .unw is already the right size is skipped.
set -u
R=<DATA_ROOT>/CSK_PSInSAR
source "$R/code/psi_env.sh"
SS=$CONDA_PREFIX/share/isce2/stripmapStack
SB=$R/seoul/sbas
JOBS=${JOBS:-8}
LOG=$R/logs/sbas_igrams; mkdir -p "$LOG"
EXP=$((1735*2000*8))

do_pair() {
  a=$1; b=$2; p="${a}_${b}"; dir="$SB/Igrams/$p"
  mkdir -p "$dir"; cd "$dir" || return 1
  if [ -s "filt_${p}_snaphu.unw" ] && [ "$(stat -c%s "filt_${p}_snaphu.unw")" = "$EXP" ]; then
    echo "SKIP $p"; return 0; fi
  t0=$(date +%s)
  python3 - "$a" "$b" "$dir" <<'PY' > "$LOG/$p.ifg.log" 2>&1 || { echo "FAIL $p ifg"; return 1; }
import sys; sys.path.insert(0,'<DATA_ROOT>/CSK_PSInSAR/code')
import sbas_lib as S; S.make_ifg(sys.argv[1],sys.argv[2],sys.argv[3])
PY
  python3 "$SS/FilterAndCoherence.py" -i "${p}.int" -f "filt_${p}.int" -c "filt_${p}.cor" -s 0.5 \
      > "$LOG/$p.filt.log" 2>&1 || { echo "FAIL $p filt"; return 1; }
  rm -rf referenceShelve
  python3 "$SS/unwrap.py" -i "filt_${p}.int" -u "filt_${p}" -c "filt_${p}.cor" \
      -a 8 -r 10 -m snaphu -s "$R/SLC/20260420/data" > "$LOG/$p.unw.log" 2>&1 \
      || { echo "FAIL $p unwrap"; return 1; }
  rm -f "${p}.int" "${p}.int.vrt" "${p}.int.xml"   # 원본 랩 간섭도는 필터본이 있으면 불필요
  echo "OK   $p  $(( $(date +%s) - t0 ))s"
}
export -f do_pair; export R SB SS LOG EXP

date +'START %F %H:%M:%S'
awk '{print $1, $2}' "$SB/pairs.txt" | xargs -P "$JOBS" -n2 bash -c 'do_pair "$@"' _
date +'END %F %H:%M:%S'
