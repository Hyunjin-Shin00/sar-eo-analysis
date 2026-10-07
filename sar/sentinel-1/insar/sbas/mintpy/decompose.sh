#!/usr/bin/env bash
# Combine ASC + DSC LOS velocities into vertical (Up) + horizontal (E-W).
# asc_desc2horz_vert.py needs BOTH tracks on an identical geocoded grid, so we
# mask each track's velocity by temporal coherence then geocode velocity+geometry
# onto a common lat/lon grid before decomposition.
# usage: decompose.sh
set -eu
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
unset PYTHONPATH || true

BASE=${DATA_ROOT}
OUT=$BASE/SBAS/DECOMP
mkdir -p "$OUT"; cd "$OUT"
LOG="$OUT/decompose.log"; : > "$LOG"

# Common grid: AOI bbox, ~0.0005 deg (~55 m) posting
S=38.1232; N=38.3621; W=72.4535; E=72.7975
PX=0.0005

for TRK in ASC DSC; do
  MP=$BASE/SBAS/${TRK}/mintpy
  [ -f "$MP/velocity.h5" ] || { echo "ERROR missing $MP/velocity.h5" | tee -a "$LOG"; exit 1; }
  echo "[decomp] $TRK: mask + geocode to common grid" | tee -a "$LOG"
  ( cd "$MP"
    mask.py velocity.h5 -m maskTempCoh.h5 -o velocity_msk.h5 >>"$LOG" 2>&1
    geocode.py velocity_msk.h5 -l inputs/geometryRadar.h5 \
      --lalo -$PX $PX --bbox $S $N $W $E -o "$OUT/${TRK}_vel_geo.h5" >>"$LOG" 2>&1
    geocode.py inputs/geometryRadar.h5 -l inputs/geometryRadar.h5 \
      --lalo -$PX $PX --bbox $S $N $W $E -o "$OUT/${TRK}_geom_geo.h5" >>"$LOG" 2>&1
  )
done

echo "[decomp] project ASC+DSC LOS -> HZ(E-W) + UP(vertical)" | tee -a "$LOG"
asc_desc2horz_vert.py "$OUT/ASC_vel_geo.h5" "$OUT/DSC_vel_geo.h5" \
  -g "$OUT/ASC_geom_geo.h5" "$OUT/DSC_geom_geo.h5" \
  --az -90 -o "$OUT/hz.h5" "$OUT/up.h5" >>"$LOG" 2>&1

echo "[decomp] export GeoTIFF" | tee -a "$LOG"
save_gdal.py "$OUT/up.h5" -o "$OUT/Usoi_vertical_mm-yr.tif"     >>"$LOG" 2>&1 || true
save_gdal.py "$OUT/hz.h5" -o "$OUT/Usoi_horizontalEW_mm-yr.tif" >>"$LOG" 2>&1 || true
echo "[decomp] DONE -> $OUT" | tee -a "$LOG"
ls -la "$OUT"
