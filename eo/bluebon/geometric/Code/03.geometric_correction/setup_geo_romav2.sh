#!/bin/bash
# =============================================================================
# geo_romav2 Conda 환경 생성 스크립트
# =============================================================================
# 목적: geo_correctionv2 환경과 충돌 없이 RoMaV2를 포함하는 독립 환경 생성
# 사용법: bash setup_geo_romav2.sh
# =============================================================================

set -e  # 오류 발생 시 즉시 중단

ROMAV2_DIR="/Users/telepix/Desktop/BlueBON_gui/RoMaV2"
ENV_NAME="geo_romav2"
PYTHON_VER="3.11"

echo "============================================================"
echo "  geo_romav2 Conda 환경 설치 시작"
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
echo "[1/5] conda 환경 생성 중 (Python $PYTHON_VER)..."
conda create -n "$ENV_NAME" python="$PYTHON_VER" -y

# 2. PyTorch 설치 (macOS MPS 지원)
echo ""
echo "[2/5] PyTorch 설치 중 (macOS MPS 지원)..."
conda run -n "$ENV_NAME" pip install --upgrade pip
conda run -n "$ENV_NAME" pip install torch==2.8.0 torchvision==0.23.0 torchaudio

# 3. RoMaV2 의존성 설치
echo ""
echo "[3/5] RoMaV2 의존성 설치 중..."
conda run -n "$ENV_NAME" pip install \
    einops>=0.8.1 \
    rich>=14.2.0 \
    tqdm>=4.67.1 \
    pillow>=10.0.0

# 4. 기존 파이프라인 의존성 설치 (geo_correctionv2와 동일)
echo ""
echo "[4/5] 기하보정 파이프라인 의존성 설치 중..."
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
    scipy

# lightglue 설치
conda run -n "$ENV_NAME" pip install lightglue

# GDAL 설치 (conda-forge 채널 사용)
conda install -n "$ENV_NAME" -c conda-forge gdal -y

# 5. RoMaV2 editable 설치
echo ""
echo "[5/5] RoMaV2 editable 모드로 설치 중..."
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
print(f'MPS: {torch.backends.mps.is_available()}')
print(f'CUDA: {torch.cuda.is_available()}')
import romav2
print(f'RoMaV2: OK (from {romav2.__file__})')
" && echo "" && echo "✅ geo_romav2 환경 설치 완료!" \
  && echo "" \
  && echo "사용법:" \
  && echo "  conda activate geo_romav2" \
  && echo "  python batch_processing.py" \
  || echo "❌ 설치 확인 실패 - 위 오류를 확인하세요"
