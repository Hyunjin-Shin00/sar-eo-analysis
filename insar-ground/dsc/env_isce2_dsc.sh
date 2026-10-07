#!/usr/bin/env bash
# DSC 코레지용 ISCE2 topsStack 환경.
# 기존 env_seoul.sh 가 참조하던 ${PSI_ENV:-<PSI_PACKAGE_ROOT>/env.sh} 는 비어 있어(통합 재구성 이후)
# 여기서 isce2 conda 환경으로 직접 구성한다.
# 사용: source ${WORK_ROOT}/CLAB_DSC/env_isce2_dsc.sh

export PYTHONPATH=""                       # pyproj/GDAL 경로 오염 방지 (기존 이슈)
# isce2 환경에는 shapely 가 없어 stackSentinel 의 bbox 폴리곤 생성이 죽는다.
# isce2_snaphu 환경만 isce + shapely + snaphu 를 모두 갖추고 있다.
P=${CONDA_PREFIX}
SP=$P/lib/python3.10/site-packages
export ISCE_HOME=$SP/isce
export PATH=$P/share/isce2/topsStack:$ISCE_HOME/applications:$ISCE_HOME/bin:$P/bin:$PATH
export PYTHONPATH=$P/share/isce2:$SP

# 스레드 폭주·fork 데드락 방지 (예전 OOM/데드락 이력)
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

export DSC_ROOT=${WORK_ROOT}/CLAB_DSC
export ORBIT_DIR=$DSC_ROOT/orbits

# run_12 merge 의 gdal.Translate 는 2.9 GB 씬을 쓰면서 블록 캐시를 무제한으로 잡는다.
# 이것이 t134 코레지 OOM 5회의 실체 - 캐시를 512 MB 로 묶어 상한을 예측 가능하게 만든다.
export GDAL_CACHEMAX=512
export GDAL_NUM_THREADS=1
export GDAL_SWATH_SIZE=268435456

# GDAL/PROJ 데이터 경로 (isce2_snaphu 의 share/proj 가 비어 있어 pyproj 쪽을 지정)
export PROJ_DATA=$(python -c "import pyproj;print(pyproj.datadir.get_data_dir())")
export PROJ_LIB=$PROJ_DATA
