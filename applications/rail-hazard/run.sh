#!/usr/bin/env bash
# 분석 env 실행 래퍼. CONDA_PREFIX 의 python 을 직접 호출하므로 PROJ/GDAL 데이터 경로를 명시한다.
# PYTHONPATH는 ISCE2 경로 오염을 피하기 위해 비운다.
E=${CONDA_PREFIX:?activate the analysis env}
exec env -u PYTHONPATH \
  PROJ_DATA="$E/share/proj" PROJ_LIB="$E/share/proj" \
  GDAL_DATA="$E/share/gdal" \
  "$E/bin/python" "$@"
