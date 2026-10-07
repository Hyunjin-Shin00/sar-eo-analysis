#!/bin/bash
# stackSentinel.py가 생성한 run 파일들을 순서대로 실행
# run_stackSentinel.sh 실행 후 이 스크립트를 실행할 것

set -e

BASE=<DATA_ROOT>/16_PSInSAR
OUT_DIR=$BASE/ISCE2_processing
RUN_DIR=$OUT_DIR/run_files

CONDA_BASE=$(conda info --base)
source $CONDA_BASE/etc/profile.d/conda.sh
conda activate isce2_snaphu

export PYTHONPATH=$CONDA_PREFIX/share/isce2:$PYTHONPATH
export PATH=$CONDA_PREFIX/share/isce2/topsStack:$PATH

cd $OUT_DIR

echo "===== run 파일 목록 ====="
ls $RUN_DIR/ | sort

echo ""
echo "===== 순차 실행 시작 ====="

for run_file in $(ls $RUN_DIR/ | sort); do
    echo ""
    echo ">>> 실행: $run_file"
    bash $RUN_DIR/$run_file 2>&1 | tee $OUT_DIR/${run_file}.log
    echo "<<< 완료: $run_file"
done

echo ""
echo "===== 전체 ISCE2 처리 완료 ====="
echo "다음 단계: StaMPS 전처리"
echo "  cd $BASE/StaMPS_Python"
echo "  isce2stamps"
echo "  mt_prep_isce 0.4"
