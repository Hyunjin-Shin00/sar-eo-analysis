#!/usr/bin/env bash
# ISCE2 topsStack (interferogram) 설정 — 2026 네팔 홍수 (Rasuwa/Nuwakot + 붕괴원점)
# usage: setup_stack.sh <ASC_085|DSC_019|DSC_121>
set -eu
TRK=$1
source ~/miniconda3/etc/profile.d/conda.sh
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PROJ_DATA=$CONDA_PREFIX/share/proj PROJ_LIB=$CONDA_PREFIX/share/proj

BASE=${DATA_ROOT}
SLCDIR=$BASE/work/safe_${TRK}
WORK=$BASE/work/stack_${TRK}
DEM=$BASE/DEM/nepal_flood.wgs84.dem
ORB=$BASE/orbits
AUX=$BASE/aux

case "$TRK" in
  ASC_085) SWATH=2; BBOX="27.85 28.40 85.08 85.58"; REF=20260816 ;;
  DSC_019) SWATH=1; BBOX="27.85 28.40 85.08 85.58"; REF=20260824 ;;
  DSC_121) SWATH=3; BBOX="28.10 28.36 85.43 85.62"; REF=20260819 ;;
  *) echo "unknown track $TRK"; exit 1 ;;
esac

mkdir -p "$WORK"
echo "[$TRK] swath=IW$SWATH bbox=($BBOX) ref=$REF"
ls "$SLCDIR"/*.SAFE -d | sed 's/^/  SAFE: /'

cd "$WORK"
stackSentinel.py \
  -s "$SLCDIR" -d "$DEM" -o "$ORB" -a "$AUX" -w "$WORK" \
  -b "$BBOX" -m "$REF" -n "$SWATH" \
  -C geometry -c 1 \
  -z ${AZL:-3} -r ${RGL:-9} -f 0.4 \
  -W interferogram -u snaphu \
  --num_proc 6 --num_proc4topo 4 \
  2>&1 | tee "$WORK/stacksentinel_setup.log"

echo "[$TRK] run_files:"; ls "$WORK/run_files/" 2>/dev/null
