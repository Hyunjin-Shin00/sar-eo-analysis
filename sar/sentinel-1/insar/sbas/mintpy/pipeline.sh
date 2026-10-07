#!/usr/bin/env bash
# Master processing chain (run AFTER SLC downloads complete).
# DEM -> orbits -> [per track: topsStack setup + run + MintPy] -> ASC/DSC decomposition.
# Tracks run sequentially to stay memory-safe on the shared server.
set -u
BASE=${DATA_ROOT}
BIN=$BASE/SBAS/_bin
DEM=$BASE/SBAS/DEM/GLO30_Usoi.wgs84.dem
ST=$BASE/SBAS/pipeline_status.txt
PYREQ=python3
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$ST"; }

say "===== PIPELINE START ====="

# 1) DEM
if [ ! -f "$DEM" ]; then
  say "[1] build DEM"; bash "$BIN/build_dem.sh" >>"$ST" 2>&1 || { say "DEM FAIL"; exit 1; }
else say "[1] DEM present"; fi

# 2) orbits (both tracks in parallel; light, different server)
say "[2] fetch orbits (asc + dsc)"
"$PYREQ" "$BIN/fetch_orbits.py" --urls "$BASE/sentinel1/asc/urls.txt" --out "$BASE/SBAS/ASC/orbits" >"$BASE/SBAS/ASC/orbits.log" 2>&1 &
o1=$!
"$PYREQ" "$BIN/fetch_orbits.py" --urls "$BASE/sentinel1/dsc/urls.txt" --out "$BASE/SBAS/DSC/orbits" >"$BASE/SBAS/DSC/orbits.log" 2>&1 &
o2=$!
wait $o1; wait $o2
say "[2] orbits done (asc=$(ls $BASE/SBAS/ASC/orbits/*.EOF 2>/dev/null|wc -l) dsc=$(ls $BASE/SBAS/DSC/orbits/*.EOF 2>/dev/null|wc -l))"

# 3) per-track topsStack + MintPy (sequential)
for T in asc dsc; do
  say "[3-$T] setup_stack"; bash "$BIN/setup_stack.sh" "$T" >>"$ST" 2>&1 || { say "$T setup FAIL"; exit 1; }
  say "[3-$T] run_stack";   bash "$BIN/run_stack.sh"   "$T" 4 || { say "$T run_stack FAIL"; exit 1; }
  say "[3-$T] run_mintpy";  bash "$BIN/run_mintpy.sh"  "$T" >>"$ST" 2>&1 || { say "$T mintpy FAIL"; exit 1; }
  say "[3-$T] DONE"
done

# 4) decomposition
say "[4] decompose ASC+DSC -> vertical + horizontal"
bash "$BIN/decompose.sh" >>"$ST" 2>&1 || { say "decompose FAIL"; exit 1; }
say "===== PIPELINE COMPLETE ====="
