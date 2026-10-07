#!/usr/bin/env bash
# Build ISCE-ready COP30 DEM for Usoi Dam AOI.
# COP30 vertical datum = EGM2008 geoid -> convert to WGS84 ellipsoid (InSAR needs ellipsoidal height).
set -eu
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export PROJ_NETWORK=ON
export PROJ_DATA=$(python3 -c "import pyproj;print(pyproj.datadir.get_data_dir())" 2>/dev/null); export PROJ_LIB=$PROJ_DATA

DEMDIR=${DATA_ROOT}/SBAS/DEM
cd "$DEMDIR"
IN=cop30_N38E072.tif
OUT=GLO30_Usoi.wgs84
[ -f "$IN" ] || { echo "ERROR: $IN missing"; exit 1; }

echo "[DEM] geoid(EGM2008)->ellipsoid(WGS84)"
gdalwarp -overwrite \
  -s_srs "+proj=longlat +datum=WGS84 +no_defs +geoidgrids=us_nga_egm08_25.tif" \
  -t_srs "+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs" \
  -r bilinear -of GTiff "$IN" "${OUT}.tif"

echo "[DEM] -> ISCE format"
gdal_translate -of ISCE "${OUT}.tif" "${OUT}.dem"
gdal2isce_xml.py -i "${OUT}.dem"

echo "[DEM] mean-height sanity (should be high, Pamir ~3000-4000m ellipsoidal):"
gdalinfo -stats "${OUT}.dem" 2>/dev/null | grep -iE 'STATISTICS_MEAN|Size is' | head
echo "[DEM] done: $DEMDIR/${OUT}.dem"
ls -la "$DEMDIR/${OUT}.dem"*
