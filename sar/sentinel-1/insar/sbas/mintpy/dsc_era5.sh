#!/usr/bin/env bash
# Re-do DSC atmospheric correction with ERA5 (PyAPS) instead of height_correlation, to remove
# the topo-correlated tropospheric residual (velocity~elevation -0.049 mm/yr/m). Inversion
# (timeseries.h5) is already done, so we only re-run correct_troposphere -> deramp ->
# correct_topography -> velocity -> geocode. ERA5 is downloaded per acquisition date via CDS.
set -u
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
unset PYTHONPATH || true
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
W=${DATA_ROOT}/SBAS/DSC; MP=$W/mintpy; BIN=${DATA_ROOT}/SBAS/_bin
LOG=$MP/mintpy_era5.log
mkdir -p ${DATA_ROOT}/SBAS/ERA5

cp -f "$BIN/smallbaseline_template.cfg" "$MP/Usoi_dsc.cfg"
sed -i '/mintpy\.reference\.yx/d' "$MP/Usoi_dsc.cfg"
sed -i 's#^mintpy\.troposphericDelay\.method .*#mintpy.troposphericDelay.method = pyaps#' "$MP/Usoi_dsc.cfg"
sed -i 's#^mintpy\.deramp .*#mintpy.deramp                   = linear#' "$MP/Usoi_dsc.cfg"
cat >> "$MP/Usoi_dsc.cfg" <<EOF
mintpy.troposphericDelay.weatherModel = ERA5
mintpy.troposphericDelay.weatherDir = ${DATA_ROOT}/SBAS/ERA5
mintpy.reference.lalo = 38.2821, 72.6066
EOF

# clear old (height_correlation) tropo products + geocoded outputs; keep timeseries.h5 + inputs
rm -f "$W/PROCESS_DONE"; rm -rf "$MP/geo"
rm -f "$MP"/timeseries_tropHgt*.h5 "$MP"/timeseries_ERA5*.h5 "$MP"/velocity.h5 "$MP"/inputs/ERA5.h5

cd "$MP"
echo "[dsc-era5] tropo=pyaps/ERA5  deramp=linear  ref=38.2821,72.6066  --start correct_troposphere" | tee "$LOG"
grep -E 'troposphericDelay|deramp|reference.(lalo|maskFile)' Usoi_dsc.cfg | tee -a "$LOG"
smallbaselineApp.py Usoi_dsc.cfg --work-dir . --start correct_troposphere 2>&1 | tee -a "$LOG"
if [ -f "$MP/geo/geo_velocity.h5" ]; then
  touch "$W/PROCESS_DONE"; echo "[dsc-era5] DONE geo/geo_velocity.h5" | tee -a "$LOG"
else
  echo "[dsc-era5] FAILED (see $LOG)" | tee -a "$LOG"; exit 2
fi
