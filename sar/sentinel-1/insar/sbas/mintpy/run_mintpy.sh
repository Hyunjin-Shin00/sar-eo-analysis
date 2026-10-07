#!/usr/bin/env bash
# Run MintPy smallbaselineApp SBAS for one track, with a PER-TRACK reference pixel.
# The auto maxCoherence reference is unreliable per-ifg on this decorrelated scene and
# zeroes temporalCoherence, so we: (1) load_data + modify_network to build & prune the
# stack, (2) compute a reference pixel reliable across most kept ifgs, (3) run the rest.
# Recipe (in smallbaseline_template.cfg): subset off, network tempBaseMax=24 + coherence
# based, unwrapError=no (no common region exists), minTempCoh=0.3, reference.maskFile=no.
# usage: run_mintpy.sh <asc|dsc>
set -u
TRACK=$1
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
unset PYTHONPATH || true
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2

BASE=${DATA_ROOT}
BIN=$BASE/SBAS/_bin
W=$BASE/SBAS/${TRACK^^}
MP=$W/mintpy
mkdir -p "$MP"
CFG=$MP/Usoi_${TRACK}.cfg
LOG=$MP/mintpy_run.log
cp -f "$BIN/smallbaseline_template.cfg" "$CFG"
# reference.yx is per-track -> strip any hardcoded value from the copy, compute below
sed -i '/^[[:space:]]*mintpy\.reference\.yx/d' "$CFG"

cd "$MP"
echo "[$TRACK] MintPy phase1: load_data + modify_network" | tee "$LOG"
smallbaselineApp.py "$CFG" --work-dir . --dostep load_data      2>&1 | tee -a "$LOG"
smallbaselineApp.py "$CFG" --work-dir . --dostep modify_network 2>&1 | tee -a "$LOG"

echo "[$TRACK] computing per-track reference pixel from pruned stack" | tee -a "$LOG"
REF=$(python3 "$BIN/best_ref_pixel.py" "$MP/inputs/ifgramStack.h5" 2>>"$LOG")
RY=${REF% *}; RX=${REF#* }
if [ -z "${RY:-}" ] || [ -z "${RX:-}" ]; then echo "[$TRACK] ERROR: no reference pixel" | tee -a "$LOG"; exit 3; fi
echo "[$TRACK] reference.yx = $RY, $RX" | tee -a "$LOG"
echo "mintpy.reference.yx = $RY, $RX" >> "$CFG"

echo "[$TRACK] MintPy phase2: reference_point -> geocode" | tee -a "$LOG"
smallbaselineApp.py "$CFG" --work-dir . --start reference_point 2>&1 | tee -a "$LOG"

if [ -f "$MP/geo/geo_velocity.h5" ]; then
  echo "[$TRACK] DONE: geo/geo_velocity.h5 present" | tee -a "$LOG"
  ls -la "$MP/geo/" | grep -iE 'velocity|temporalCoh' | tee -a "$LOG"
else
  echo "[$TRACK] WARNING: geo/geo_velocity.h5 missing (see $LOG)" | tee -a "$LOG"; exit 4
fi
