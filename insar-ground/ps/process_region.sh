#!/usr/bin/env bash
# 일반화 지역 처리: PS(차감전/후/raw + 클릭맵2) + SBAS(차감전/후 + 클릭맵2) → CLAB/{REGION}/{PS,SBAS}
# usage: process_region.sh REGION "TITLE" S N W E STACK MASTER SINKLAT SINKLON
#   SINKLAT SINKLON = "none" "none" 이면 싱크홀 마커 없음
set -u
REGION=$1; TITLE=$2; S=$3; N=$4; W=$5; E=$6; STACK=$7; MASTER=$8; SINKLAT=$9; SINKLON=${10}
BBOX="$S $N $W $E"
SEOUL=${DATA_ROOT}/CLAB/regions/seoul/workspace/stamps_seoul
source "$SEOUL/env_seoul.sh" 2>/dev/null
export PROJ_DATA=$(python3 -c "import pyproj;print(pyproj.datadir.get_data_dir())" 2>/dev/null); export PROJ_LIB=$PROJ_DATA
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export NWORKERS=8 MAXTASKSPERCHILD=50 CHUNKSIZE=50
PY=${CONDA_PREFIX}/bin/python
BIN=${DATA_ROOT}/CLAB/analysis/insar_bin
WPRE="import sys; sys.path.insert(0,'$SEOUL'); import mp_patch; "
PROC=$STACK/stamps_dev3; INSAR=$PROC/INSAR_$MASTER
# 2026-07-19 재정리: region → regions/<group>/{psinsar,sbas,reports}/[<aoi>]
case "$REGION" in
  Busan_Mandeok_Centum) GRP=busan; AOI=mandeok_centum;;
  Busan_Sasang_Hadan)   GRP=busan; AOI=sasang_hadan;;
  Seoul_Seodaemun)      GRP=seoul; AOI=seodaemun;;
  Seoul_Gangdong)       GRP=seoul; AOI=gangdong;;
  Incheon_Songdo)       GRP=incheon; AOI=songdo;;
  Incheon_Songdo_DSC)   GRP=incheon; AOI=songdo_dsc;;
  Incheon_Songdo_baseline) GRP=incheon; AOI=songdo_baseline;;
  Gyeonggi_Gwangmyeong) GRP=gyeonggi; AOI="";;
  Yangyang)             GRP=yangyang; AOI="";;
  *) GRP="$REGION"; AOI="";;
esac
RB=${DATA_ROOT}/CLAB/regions/$GRP
if [ -n "$AOI" ]; then PSD=$RB/psinsar/$AOI; SBD=$RB/sbas/$AOI; REP=$RB/reports/$AOI
else PSD=$RB/psinsar; SBD=$RB/sbas; REP=$RB/reports; fi
LOG=$REP/logs
mkdir -p "$PSD" "$SBD" "$LOG"
ST=$REP/status.txt
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$ST"; }
die(){ say "FAILED: $*"; exit 1; }
if [ "$SINKLAT" = "none" ]; then POIARG="--no_poi"; else POIARG="--poi $SINKLAT $SINKLON --poi_label 싱크홀_발생지점"; fi

say "===== $REGION ($TITLE) 시작  bbox=$BBOX  stack=$STACK master=$MASTER sink=$SINKLAT,$SINKLON ====="

# ---------------- PS ----------------
cd "$STACK" || die "cd stack"
[ -d "$PROC" ] && { say "clean 기존 stamps_dev3"; rm -rf "$PROC"; }
say "[PS] run_prep_psi crop"
run_prep_psi.py -b $BBOX -o "$STACK" > "$LOG/ps_crop.log" 2>&1 || die "run_prep_psi"
cd "$PROC" || die "cd PROC"
say "[PS] create_input_file (ref $MASTER)"
create_input_file.py --base_path "$PROC" --reference "$MASTER" --range_looks 1 --azimuth_looks 1 \
  --aspect_ratio 1 --lambda_val 0.05546576 --slc_suffix .full --geom_suffix .full --output input_file \
  > "$LOG/ps_inputfile.log" 2>&1 || die "create_input_file"
say "[PS] make_single_reference_stack_isce"
make_single_reference_stack_isce > "$LOG/ps_makesm.log" 2>&1 || die "make SM"
[ -d "$INSAR" ] || die "no INSAR ($INSAR)"
cd "$INSAR" || die "cd INSAR"
say "[PS] mt_prep_isce 0.4 1 1"
mt_prep_isce 0.4 1 1 > "$LOG/ps_mtprep.log" 2>&1 || die "mt_prep"
"$PY" -c "from psi_python.setparm import setparm; setparm('unwrap_grid_size',100); setparm('unwrap_gold_n_win',16)" > "$LOG/ps_setparm.log" 2>&1 || die "setparm unwrap"
say "[PS] stamps(1,7) + mp_patch"
"$PY" -c "${WPRE}from psi_python.stamps import stamps; stamps(1,7)" > "$LOG/ps_stamps17.log" 2>&1 || die "stamps(1,7)"
"$PY" -c "from psi_python.ps_scn_filt import ps_scn_filt; ps_scn_filt()" > "$LOG/ps_scnfilt.log" 2>&1 || die "scn_filt"
say "[PS] ps_output ref0 (전역평균, coh0.4)"
ps_output.py -c 0.4 -o "$PSD/output_ref0.shp" > "$LOG/ps_out_ref0.log" 2>&1 || die "ps_output ref0"
"$PY" "$BIN/ps_output_raw.py" -c 0.4 -o "$PSD/output_raw.shp" > "$LOG/ps_out_raw.log" 2>&1 || say "WARN raw 실패"
say "[PS] select_reference (안정영역 자동)"
"$PY" "$BIN/select_reference.py" --shp "$PSD/output_ref0.shp" --radius 150 --min_ps 15 \
  --out "$PSD/ref_pick.json" --png "$PSD/velocity_map.png" > "$LOG/ps_selref.log" 2>&1 || say "WARN select_reference 실패"
if grep -q '"ok": true' "$PSD/ref_pick.json" 2>/dev/null; then
  RLON=$("$PY" -c "import json;print(json.load(open('$PSD/ref_pick.json'))['ref_lon'])")
  RLAT=$("$PY" -c "import json;print(json.load(open('$PSD/ref_pick.json'))['ref_lat'])")
  RRAD=$("$PY" -c "import json;print(json.load(open('$PSD/ref_pick.json'))['ref_radius_m'])")
  say "[PS] setparm ref_centre_lonlat=[$RLON,$RLAT] ref_radius=$RRAD → stamps(7,7)"
  "$PY" -c "from psi_python.setparm import setparm
try: setparm('ref_centre_lonlat',[$RLON,$RLAT])
except Exception: setparm('ref_centre_lonlat',[$RLON,$RLAT],1)
try: setparm('ref_radius',$RRAD)
except Exception: setparm('ref_radius',$RRAD,1)" > "$LOG/ps_setref.log" 2>&1 || die "setparm ref"
  "$PY" -c "${WPRE}from psi_python.stamps import stamps; stamps(7,7)" > "$LOG/ps_stamps77.log" 2>&1 || die "stamps(7,7)"
  "$PY" -c "from psi_python.ps_scn_filt import ps_scn_filt; ps_scn_filt()" > "$LOG/ps_scnfilt2.log" 2>&1 || die "scn_filt2"
  ps_output.py -c 0.4 -o "$PSD/output_final.shp" > "$LOG/ps_out_final.log" 2>&1 || die "ps_output final"
else
  say "WARN: 기준영역 미선정 → output_final = ref0 복사"
  for x in shp dbf shx prj cpg; do cp -a "$PSD/output_ref0.$x" "$PSD/output_final.$x" 2>/dev/null; done
fi
NPS=$("$PY" -c "import geopandas as gpd;print(len(gpd.read_file('$PSD/output_final.shp')))" 2>/dev/null)
say "[PS] 완료 PS=$NPS → 클릭맵 2종"
"$PY" "$BIN/make_clickmap_big.py" --shp "$PSD/output_final.shp" --ref "$PSD/ref_pick.json" $POIARG \
  --out "$PSD/${REGION}_PS_clickmap.html" --title "$TITLE PS (기준점 차감 후)" > "$LOG/ps_click1.log" 2>&1 || say "WARN click PS after"
"$PY" "$BIN/make_clickmap_big.py" --shp "$PSD/output_ref0.shp" --ref "$PSD/ref_pick.json" $POIARG \
  --out "$PSD/${REGION}_PS_clickmap_beforeref.html" --title "$TITLE PS (기준점 차감 전)" > "$LOG/ps_click2.log" 2>&1 || say "WARN click PS before"

# ---------------- SBAS ----------------
say "[SBAS] run_sbas"
"$PY" "$BIN/run_sbas_autoscale.py" --merged "$STACK/merged" --bbox $BBOX --out "$SBD" --region "$REGION" > "$LOG/sbas.log" 2>&1 || die "run_sbas"
if [ -f "$SBD/${REGION}_sbas_ps_v.shp" ]; then
  say "[SBAS] 클릭맵(표준 1종)"
  "$PY" "$BIN/make_clickmap_big.py" --shp "$SBD/${REGION}_sbas_ps_v.shp" --ref "$SBD/${REGION}_sbas_ref_for_clickmap.json" $POIARG \
    --out "$SBD/${REGION}_SBAS_clickmap.html" --title "$TITLE SBAS (기준점 차감 후, 표준)" > "$LOG/sbas_click1.log" 2>&1 || say "WARN click SBAS after"
fi
say "===== $REGION 전체 완료 (PS=$NPS) ====="
