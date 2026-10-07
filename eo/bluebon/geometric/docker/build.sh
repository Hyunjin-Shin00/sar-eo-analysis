#!/bin/bash
# ============================================================
# Docker 이미지 빌드 스크립트
# 실행 위치: 프로젝트 루트 (BlueBON_Geometric_Correction_V3/)
# ============================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_NAME="blubon-geocorrect"
IMAGE_TAG="latest"

echo "=============================================="
echo " BlueBON 기하보정 Docker 이미지 빌드"
echo "=============================================="
echo ""

# ── 1. 모델 가중치 복사 ──────────────────────────────────
echo "[1/3] 모델 가중치 복사 중..."

CACHE_DST="$PROJECT_ROOT/.cache/torch/hub/checkpoints"
CACHE_SRC="$HOME/.cache/torch/hub"

mkdir -p "$CACHE_DST"

# torch hub checkpoints
if [ -d "$CACHE_SRC/checkpoints" ]; then
    cp -v "$CACHE_SRC/checkpoints/"*.pth "$CACHE_DST/" 2>/dev/null || true
    cp -v "$CACHE_SRC/checkpoints/"*.pt  "$CACHE_DST/" 2>/dev/null || true
    echo "   ✅ torch hub checkpoints 복사 완료"
else
    echo "   ⚠️  $CACHE_SRC/checkpoints 없음 — 런타임에 자동 다운로드됩니다"
fi

# DINOv3 hub 코드
HUB_DINOV3=$(ls -d "$CACHE_SRC"/facebookresearch_dinov3_* 2>/dev/null | head -1)
if [ -n "$HUB_DINOV3" ]; then
    mkdir -p "$PROJECT_ROOT/.cache/torch/hub/"
    cp -r "$HUB_DINOV3" "$PROJECT_ROOT/.cache/torch/hub/"
    echo "   ✅ DINOv3 hub 코드 복사 완료"
fi

# ── 2. .dockerignore 확인 ────────────────────────────────
echo ""
echo "[2/3] .dockerignore 확인..."
if [ ! -f "$PROJECT_ROOT/.dockerignore" ]; then
    cat > "$PROJECT_ROOT/.dockerignore" << 'EOF'
# 데이터셋 (빌드에 포함하지 않음)
Dataset/

# 파이썬 캐시
**/__pycache__
**/*.pyc
**/*.pyo

# 불필요한 개발 파일
.git/
**/.DS_Store

# 기존 빌드 결과
docker/build.log
EOF
    echo "   ✅ .dockerignore 생성 완료"
fi

# ── 3. Docker 이미지 빌드 ────────────────────────────────
echo ""
echo "[3/3] Docker 이미지 빌드 중... (시간이 걸립니다)"
echo "      로그: $PROJECT_ROOT/docker/build.log"
echo ""

cd "$PROJECT_ROOT"
docker build \
    -f docker/Dockerfile \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    . \
    2>&1 | tee docker/build.log

echo ""
echo "=============================================="
echo " ✅ 빌드 완료: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "=============================================="
echo ""
echo "이미지 크기:"
docker images "${IMAGE_NAME}:${IMAGE_TAG}" --format "  {{.Repository}}:{{.Tag}}  {{.Size}}"
echo ""
echo "테스트 실행:"
echo "  docker run --gpus all ${IMAGE_NAME}:${IMAGE_TAG} --help"
