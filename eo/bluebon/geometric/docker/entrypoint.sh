#!/bin/bash
# BlueBON 기하보정 파이프라인 진입점

set -e

# conda 환경 활성화
source /opt/conda/etc/profile.d/conda.sh
conda activate geocorrect

# Flash SDPA 비활성화 (triton 컴파일 오류 방지)
export TORCH_BACKENDS_CUDA_ENABLE_FLASH_SDP=0

# PROJ 경로 설정 (GDAL/pyproj 버전 충돌 방지)
export PROJ_DATA=/opt/conda/envs/geocorrect/share/proj
export PROJ_LIB=/opt/conda/envs/geocorrect/share/proj

# PYTHONPATH 설정
export PYTHONPATH=/app/Code:/app/Code/03.geometric_correction:$PYTHONPATH

# --help 또는 인자 없이 실행 시 도움말 출력
if [ "$1" = "--help" ] || [ $# -eq 0 ]; then
    python /app/Code/Full_processing_v2.py --help
    exit 0
fi

echo "========================================"
echo " BlueBON 기하보정 파이프라인 시작"
echo "========================================"
echo "인자: $@"
echo ""

exec python /app/Code/Full_processing_v2.py "$@"
