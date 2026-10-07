#!/bin/bash
# =============================================================================
# geo_romav2 Conda 환경 생성 스크립트 (Linux CUDA 버전)
# =============================================================================
# 목적: 리눅스 환경에서 NVIDIA GPU(CUDA)를 사용하여 RoMaV2를 구동하도록 독립 환경 생성
# 사용법: bash setup_geo_romav2_linux.sh
# =============================================================================

set -e  # 오류 발생 시 즉시 중단

# 경로 설정 (스크립트 위치 기준 자동 설정)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROMAV2_DIR="$SCRIPT_DIR/../../RoMaV2"
ENV_NAME="geo_romav2"
PYTHON_VER="3.11"

echo "============================================================"
echo "  geo_romav2 Conda 환경 설치 시작 (Linux/CUDA)"
echo "============================================================"
echo "  환경 이름 : $ENV_NAME"
echo "  Python    : $PYTHON_VER"
echo "  RoMaV2    : $ROMAV2_DIR"
echo ""

# 기존 환경이 있으면 삭제 여부 확인
if conda env list | grep -q "^${ENV_NAME}"; then
    echo "⚠️  기존 ${ENV_NAME} 환경이 발견되었습니다."
    read -p "   삭제 후 재생성할까요? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo "   기존 환경 삭제 중..."
        conda env remove -n "$ENV_NAME" -y
    else
        echo "   설치를 취소합니다."
        exit 0
    fi
fi

# 1. conda 환경 생성
echo ""
echo "[1/6] conda 환경 생성 중 (Python $PYTHON_VER)..."
conda create -n "$ENV_NAME" python="$PYTHON_VER" -y

# 2. PyTorch 설치 (Linux CUDA 자동 감지)
echo ""
echo "[2/6] PyTorch 설치 중 (Linux CUDA)..."
conda run -n "$ENV_NAME" pip install --upgrade pip
conda run -n "$ENV_NAME" pip install torch torchvision torchaudio

# 3. RoMaV2 의존성 설치
echo ""
echo "[3/6] RoMaV2 의존성 설치 중..."
conda run -n "$ENV_NAME" pip install \
    einops>=0.8.1 \
    rich>=14.2.0 \
    tqdm>=4.67.1 \
    pillow>=10.0.0

# 4. 기하보정 파이프라인 의존성 설치
echo ""
echo "[4/6] 기하보정 파이프라인 의존성 설치 중..."
conda run -n "$ENV_NAME" pip install \
    kornia>=0.8.2 \
    opencv-python>=4.12.0 \
    numpy>=1.26.0 \
    pandas \
    openpyxl \
    scikit-learn \
    matplotlib \
    rasterio \
    pyproj \
    affine \
    scipy \
    rpcfit

# LightGlue 설치 (PyPI 미등록 → GitHub에서 설치)
conda run -n "$ENV_NAME" pip install git+https://github.com/cvg/LightGlue.git

# GDAL 설치 (conda-forge 채널 사용)
conda install -n "$ENV_NAME" -c conda-forge gdal -y

# 5. RoMaV2 pyproject.toml 호환성 패치
#    Python 3.7+ 에서는 dataclasses가 내장 모듈이므로 PyPI 패키지 불필요
echo ""
echo "[5/6] RoMaV2 pyproject.toml 패치 중 (dataclasses 의존성 제거)..."
PYPROJECT="$ROMAV2_DIR/pyproject.toml"
if grep -q '"dataclasses>=' "$PYPROJECT" 2>/dev/null; then
    sed -i '/"dataclasses>=/d' "$PYPROJECT"
    echo "   ✅ dataclasses 의존성 제거 완료"
else
    echo "   ℹ️  패치 불필요 (이미 제거됨)"
fi

# 6. RoMaV2 editable 설치
echo ""
echo "[6/6] RoMaV2 editable 모드로 설치 중..."
if [ -d "$ROMAV2_DIR" ]; then
    conda run -n "$ENV_NAME" pip install -e "$ROMAV2_DIR"
    echo "   ✅ RoMaV2 설치 완료"
else
    echo "   ❌ RoMaV2 디렉토리를 찾을 수 없습니다: $ROMAV2_DIR"
    exit 1
fi

# 설치 확인
echo ""
echo "============================================================"
echo "  설치 확인"
echo "============================================================"
conda run -n "$ENV_NAME" python -c "
import sys
print(f'Python: {sys.version}')
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
import romav2
print(f'RoMaV2: OK ({romav2.__file__})')
import lightglue
print(f'LightGlue: OK')
import rpcfit
print(f'rpcfit: OK')
from osgeo import gdal
print(f'GDAL: OK ({gdal.__version__})')
" && echo "" && echo "✅ geo_romav2 환경 설치 완료!" \
  && echo "" \
  && echo "사용법:" \
  && echo "  conda activate geo_romav2" \
  || echo "❌ 설치 확인 실패 - 위 오류를 확인하세요"
