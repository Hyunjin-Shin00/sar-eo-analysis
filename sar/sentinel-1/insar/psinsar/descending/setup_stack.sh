#!/bin/bash
# DSC path32 topsStack 코레지 설정.
#
# -W slc 로 코레지된 SLC 스택만 만들고, 간섭도는 ASC 때 검증된 sbas_lib_s1.py 를
# 그대로 써서 따로 만든다(멀티룩 8rg x 2az, 전체해상도 파일을 쓰지 않는 스트리밍).
# 2026-06-13 은 정밀궤도가 발행되지 않아 SLC 에서 제외했다.
set -eu
D=<DATA_ROOT>/S1_DSC
DEM=<DATA_ROOT>/CSK_PSInSAR/DEM/GLO30_SeoulCSG.wgs84.dem
REF=20260308                     # 전체 기간 중앙
BBOX='37.42 37.71 126.76 127.19' # 서울 행정경계 bbox
source <DATA_ROOT>/CSK_PSInSAR/code/psi_env.sh
ST=$CONDA_PREFIX/share/isce2/topsStack

mkdir -p "$D/stack" "$D/aux_cal"
cd "$D/stack"
date +'SETUP START %F %H:%M:%S'
python "$ST/stackSentinel.py" \
  -s "$D/SLC" -d "$DEM" -o "$D/orbits" -a "$D/aux_cal" \
  -b "$BBOX" -c 1 -n '1 2 3' -p vv -W slc -m "$REF" \
  -C geometry -O 4 -e 0.85
echo "EXIT=$?"
echo "--- run_files ---"; ls run_files/ 2>/dev/null
date +'SETUP END %F %H:%M:%S'
