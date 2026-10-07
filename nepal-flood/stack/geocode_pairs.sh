#!/usr/bin/env bash
# 간섭쌍별 결맞음/간섭도를 지오코딩. usage: geocode_pairs.sh <TRACK>
set -eu
TRK=$1
source ~/miniconda3/etc/profile.d/conda.sh
conda activate isce2_snaphu
export OMP_NUM_THREADS=1 PROJ_DATA=$CONDA_PREFIX/share/proj PROJ_LIB=$CONDA_PREFIX/share/proj
BASE=${DATA_ROOT}
WORK=$BASE/work/stack_${TRK}
DEM=$BASE/DEM/nepal_flood.wgs84.dem
case "$TRK" in
  ASC_085) BBOX="27.85 28.40 85.08 85.58" ;;
  DSC_019) BBOX="27.85 28.40 85.08 85.58" ;;
  DSC_121) BBOX="28.10 28.36 85.43 85.62" ;;
esac
# 룩수는 반드시 실제 처리에 쓰인 값과 같아야 한다. 하드코딩하면 기하 매핑이
# 어긋나 장면 일부만 지오코딩된다. config에서 직접 읽어온다.
CFG=$(ls "$WORK"/configs/config_merge_igram_* 2>/dev/null | head -1)
RL=$(awk -F': *' '/^range_looks/{print $2}' "$CFG")
AL=$(awk -F': *' '/^azimuth_looks/{print $2}' "$CFG")
[ -n "$RL" ] && [ -n "$AL" ] || { echo "룩수를 config에서 못 읽음: $CFG"; exit 1; }
echo "[$TRK] looks: range=$RL azimuth=$AL (config에서 판독)"
cd "$WORK"
for d in merged/interferograms/*/; do
  PAIR=$(basename "$d")
  # 쌍 이름은 <이른날짜>_<늦은날짜>이며 둘 중 하나가 스택의 reference다.
  # geocodeIsce.py -s 에는 reference가 아닌 쪽(secondarys/ 에 존재하는 날짜)을 줘야 한다.
  D1=${PAIR%_*}; D2=${PAIR#*_}; SEC=""
  for c in "$D1" "$D2"; do [ -d "$WORK/secondarys/$c" ] && SEC=$c; done
  [ -n "$SEC" ] || { echo "  secondary 날짜 못 찾음: $PAIR"; continue; }
  for F in filt_fine.cor filt_fine.int; do
    [ -f "$d/$F" ] || { echo "  없음: $d$F"; continue; }
    [ -f "$d/${F}.geo" ] && { echo "  이미 지오코딩됨: $PAIR/$F"; continue; }
    echo "=== geocode $PAIR / $F ==="
    geocodeIsce.py -f "$d/$F" -d "$DEM" -m "$WORK/reference" \
      -s "$WORK/secondarys/$SEC" -r $RL -a $AL -b "$BBOX"
  done
done
echo "GEOCODE_DONE $TRK"; ls -la merged/interferograms/*/*.geo 2>/dev/null
