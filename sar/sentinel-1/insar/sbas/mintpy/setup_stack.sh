#!/usr/bin/env bash
# Configure ISCE2 topsStack (interferogram workflow) for one track.
# usage: setup_stack.sh <asc|dsc>
set -eu
TRACK=$1
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

BASE=${DATA_ROOT}
SLCDIR=$BASE/sentinel1/$TRACK
WORK=$BASE/SBAS/${TRACK^^}
DEM=$BASE/SBAS/DEM/GLO30_Usoi.wgs84.dem
ORB=$WORK/orbits
AUX=$BASE/SBAS/aux
BBOX="38.1232 38.3621 72.4535 72.7975"
mkdir -p "$WORK" "$ORB" "$AUX"

# Reference = median acquisition date (minimizes spatial+temporal baselines)
mapfile -t DATES < <(ls "$SLCDIR"/*.zip 2>/dev/null | grep -oE '_20[0-9]{6}T' | grep -oE '20[0-9]{6}' | sort -u)
NREF=${#DATES[@]}
[ "$NREF" -gt 0 ] || { echo "ERROR: no SLCs in $SLCDIR"; exit 1; }
REF=${DATES[$((NREF/2))]}
echo "[$TRACK] $NREF dates, reference(median)=$REF"

# Force the single subswath that fully covers the AOI (avoids IW1/IW2-boundary
# swath-coverage inconsistency across the stack). ASC: IW2 fully covers the AOI.
# DSC: leave empty until verified from its reference geometry.
case "$TRACK" in
  asc) SWATH="2";;
  dsc) SWATH="${USOI_DSC_SWATH:-}";;
  *)   SWATH="";;
esac
SWOPT=""; [ -n "$SWATH" ] && SWOPT="-n $SWATH"
echo "[$TRACK] swath option: ${SWOPT:-<all>}"

cd "$WORK"
stackSentinel.py \
  -s "$SLCDIR" -d "$DEM" -o "$ORB" -a "$AUX" -w "$WORK" \
  -b "$BBOX" -m "$REF" $SWOPT \
  -C geometry -c 4 \
  -z 3 -r 9 -f 0.5 \
  -W interferogram -u snaphu \
  --num_proc 6 --num_proc4topo 4 \
  2>&1 | tee "$WORK/stacksentinel_setup.log"

echo "[$TRACK] run_files:"; ls "$WORK/run_files/" 2>/dev/null
