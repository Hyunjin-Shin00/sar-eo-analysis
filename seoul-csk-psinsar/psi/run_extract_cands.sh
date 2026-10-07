#!/bin/bash
# Per-patch candidate extraction (selpsc -> lonlat -> hgt -> phase), N patches
# in parallel. Equivalent to mt_extract_cands but with bounded concurrency and
# resumability (a patch with all four outputs is skipped).
set -u
R=<DATA_ROOT>/CSK_PSInSAR
source "$R/code/psi_env.sh"
D=$R/seoul/psi/INSAR_20260420
JOBS=${JOBS:-5}
MASK=$(grep maskfile "$D/input_file" | awk '{print $2}')
LOG=$R/logs/extract_cands; mkdir -p "$LOG"

do_patch() {
  p="$1"; n=$(basename "$p")
  cd "$p" || return 1
  if [ -s pscands.1.ij ] && [ -s pscands.1.ll ] && [ -s pscands.1.hgt ] && [ -s pscands.1.ph ]; then
    echo "SKIP $n"; return 0
  fi
  t0=$(date +%s)
  python "$ISCE2PSI/selpsc_patch.py" "$D/selpsc.in" patch.in pscands.1.ij pscands.1.da mean_amp.flt f 0 "$MASK" > "$LOG/$n.selpsc.log" 2>&1 || { echo "FAIL $n selpsc"; return 1; }
  t1=$(date +%s); c=$(wc -l < pscands.1.ij)
  python "$ISCE2PSI/psclonlat.py" "$D/psclonlat.in" pscands.1.ij pscands.1.ll > "$LOG/$n.ll.log" 2>&1 || { echo "FAIL $n lonlat"; return 1; }
  python "$ISCE2PSI/pscdem.py"    "$D/pscdem.in"    pscands.1.ij pscands.1.hgt f > "$LOG/$n.hgt.log" 2>&1 || { echo "FAIL $n hgt"; return 1; }
  t2=$(date +%s)
  python "$ISCE2PSI/pscphase.py"  "$D/pscphase.in"  pscands.1.ij pscands.1.ph > "$LOG/$n.ph.log" 2>&1 || { echo "FAIL $n phase"; return 1; }
  t3=$(date +%s)
  echo "OK   $n  후보 $c  (selpsc $((t1-t0))s / ll+hgt $((t2-t1))s / phase $((t3-t2))s)"
}
export -f do_patch; export D ISCE2PSI MASK LOG

date +'START %F %H:%M:%S'
ls -d "$D"/PATCH_* | sort -V | xargs -I{} -P "$JOBS" bash -c 'do_patch "$@"' _ {}
date +'END %F %H:%M:%S'
