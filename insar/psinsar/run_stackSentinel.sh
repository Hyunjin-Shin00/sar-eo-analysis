#!/bin/bash
# stackSentinel.py 실행 스크립트 (PSInSAR / StaMPS 전처리)
# ISCE2 2.6.4, conda env: isce2_snaphu

set -e

# ── 경로 설정 ──────────────────────────────────────────────────
BASE=<DATA_ROOT>/16_PSInSAR
SLC_DIR=$BASE/sentinel-1
ORBIT_DIR=$BASE/orbit
AUX_DIR=$BASE/aux
DEM=$BASE/DEM/output_hh_WGS84.dem
OUT_DIR=$BASE/ISCE2_processing

STACK_SCRIPT=$CONDA_PREFIX/share/isce2/topsStack/stackSentinel.py

# ── 환경 설정 ──────────────────────────────────────────────────
CONDA_BASE=$(conda info --base)
source $CONDA_BASE/etc/profile.d/conda.sh
conda activate isce2_snaphu

export PYTHONPATH=$CONDA_PREFIX/share/isce2:$PYTHONPATH
export PATH=$CONDA_PREFIX/share/isce2/topsStack:$PATH

# ── stackSentinel.py 실행 ──────────────────────────────────────
mkdir -p $OUT_DIR
cd $OUT_DIR

python $STACK_SCRIPT \
    -s $SLC_DIR \
    -o $ORBIT_DIR \
    -a $AUX_DIR \
    -d $DEM \
    -W slc \
    -b "25.31 27.39 117.24 120.07" \
    -m 20240213 \
    -n "1 2 3" \
    -C NESD \
    -z 1 \
    -r 4 \
    --num_proc 8 \
    2>&1 | tee stackSentinel.log

echo ""
echo "===== stackSentinel.py 완료 ====="
echo "생성된 run 파일 목록:"
ls $OUT_DIR/run_files/
