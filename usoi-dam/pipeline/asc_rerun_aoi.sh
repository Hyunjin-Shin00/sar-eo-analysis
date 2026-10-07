#!/usr/bin/env bash
# Re-run ASC MintPy with the reference point moved INTO the AOI. Diagnosis: ASC spatial
# coherence in the AOI is good (~0.56, 93% >0.3) and it's not shadow/layover (90.8% visible),
# but the SBAS reference sat in a southern coherent patch in a different unwrap region, so the
# AOI's per-ifg integer-offset mismatch drove its temporal coherence ~0 and it got masked out.
# Referencing inside the AOI makes the AOI region self-consistent -> recovers AOI velocity.
# Keeps the (expensive) ifgramStack; re-runs reference_point -> velocity -> geocode.
set -u
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
unset PYTHONPATH || true
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
W=${DATA_ROOT}/SBAS/ASC; MP=$W/mintpy; BIN=${DATA_ROOT}/SBAS/_bin
LOG=$MP/mintpy_run.log
REF_LALO="38.28233, 72.61924"

# delete the old ASC result products (keep the built inputs: ifgramStack + geometry)
rm -f "$W/PROCESS_DONE"
rm -rf "$MP/geo"
rm -f "$MP"/timeseries*.h5 "$MP"/velocity.h5 "$MP"/temporalCoherence.h5 "$MP"/numInvIfgram.h5 "$MP"/numTriNonzeroIntAmbiguity.h5

cp -f "$BIN/smallbaseline_template.cfg" "$MP/Usoi_asc.cfg"
sed -i '/mintpy\.reference\.yx/d' "$MP/Usoi_asc.cfg"
echo "mintpy.reference.lalo = $REF_LALO" >> "$MP/Usoi_asc.cfg"

cd "$MP"
echo "[asc-rerun] reference.lalo = $REF_LALO ; --start reference_point" | tee "$LOG"
smallbaselineApp.py Usoi_asc.cfg --work-dir . --start reference_point 2>&1 | tee -a "$LOG"
if [ -f "$MP/geo/geo_velocity.h5" ]; then
  touch "$W/PROCESS_DONE"; echo "[asc-rerun] DONE geo/geo_velocity.h5" | tee -a "$LOG"
else
  echo "[asc-rerun] FAILED (no geo_velocity.h5)" | tee -a "$LOG"; exit 2
fi
