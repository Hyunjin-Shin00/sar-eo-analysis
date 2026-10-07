#!/bin/bash
# Unpack every CSG scene into SLC/<date>/.  Re-running skips finished scenes,
# so this is also the "3~4장 추가분" catch-up command.
set -u
ROOT=<DATA_ROOT>/CSK_PSInSAR
SRC=<DATA_ROOT>/Cosmo-Skymed
JOBS=${JOBS:-6}

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

mkdir -p "$ROOT/SLC" "$ROOT/logs"

unpack_one() {
  d="$1"; date=$(basename "$d")
  out="$ROOT/SLC/$date"
  exp=$(python - "$d" <<'PY'
import glob,sys,h5py
f=sorted(glob.glob(sys.argv[1]+'/*/CSG_*.h5'))[0]
with h5py.File(f,'r') as h:
    s=h['S01/IMG'].shape
print(s[0]*s[1]*8)
PY
)
  if [ -s "$out/$date.slc" ] && [ "$(stat -c%s "$out/$date.slc")" = "$exp" ] && [ -s "$out/data.dat" ]; then
    echo "SKIP  $date (이미 완료)"; return 0
  fi
  if python "$ROOT/code/unpack_csg.py" -i "$d" -o "$out" > "$ROOT/logs/unpack_$date.log" 2>&1; then
    echo "OK    $date  $(stat -c%s "$out/$date.slc") B"
  else
    echo "FAIL  $date  (로그: logs/unpack_$date.log)"; return 1
  fi
}
export -f unpack_one; export ROOT

ls -d "$SRC"/2*/ | sort | xargs -I{} -P "$JOBS" bash -c 'unpack_one "$@"' _ {}
