#!/usr/bin/env bash
# PS-InSAR 세션 환경 (일반화본). ISCE2 + StaMPS Python 포팅(psi_python) 경로는 설치 환경에 맞게 지정.
# 사용: source env_seoul.sh
source "${PSI_ENV:-<PSI_PACKAGE_ROOT>/env.sh}"     # ISCE2 / psi_python PATH·PYTHONPATH 설정
export PATH="${TOOLS_PREFIX:-$CONDA_PREFIX}/bin:$PATH"   # tcsh / gawk (StaMPS 셸 스크립트용)
export PSI_ROOT=${DATA_ROOT}/CLAB/regions/seoul/workspace/stamps_seoul
export SLC_DIR=$PSI_ROOT/slc_input
export ORBIT_DIR=${DATA_ROOT}/CLAB/regions/seoul/workspace/orbits
export DEM_FILE=${DATA_ROOT}/CLAB/regions/seoul/workspace/DEM/GLO30_Seoul.wgs84.dem
export AOI_BBOX='37.35 37.69 126.57 127.22'
