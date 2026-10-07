#!/bin/bash
# ============================================================
# BlueBON 기하보정 실행 스크립트
# 사용법: ./run.sh [옵션]
# ============================================================

IMAGE_NAME="blubon-geocorrect:latest"

# ── 사용법 출력 ──────────────────────────────────────────
usage() {
    echo "사용법: $0 --input <tiff경로> --lat <위도> --lon <경도> [옵션]"
    echo ""
    echo "필수 인자:"
    echo "  --input <경로>    입력 TIFF 파일 경로 (호스트 절대경로)"
    echo "  --lat <float>     중심 위도"
    echo "  --lon <float>     중심 경도"
    echo ""
    echo "선택 인자:"
    echo "  --res <float>     목표 해상도 (기본: 4.8m)"
    echo "  --segment <1-3>   영상 분할 수 (기본: 3)"
    echo "  --intermediate    중간 결과물 저장"
    echo "  --key <경로>      Google Earth Engine 인증키 경로 (기본: ./auth/ee-service-account-key.json)"
    echo "  --gpu <id>        GPU 번호 (기본: all)"
    echo ""
    echo "예시:"
    echo "  $0 --input /data/bb_l1a_20260220_025632_8band.tiff \\"
    echo "     --lat 37.1794 --lon 126.9726 --intermediate"
    exit 1
}

# ── 인자 파싱 ────────────────────────────────────────────
INPUT=""
LAT=""
LON=""
KEY="./Code/auth/ee-service-account-key.json"
GPU="all"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input)   INPUT="$2";  shift 2 ;;
        --lat)     LAT="$2";    shift 2 ;;
        --lon)     LON="$2";    shift 2 ;;
        --key)     KEY="$2";    shift 2 ;;
        --gpu)     GPU="$2";    shift 2 ;;
        --help|-h) usage ;;
        *)         EXTRA_ARGS+=("$1"); shift ;;
    esac
done

if [ -z "$INPUT" ] || [ -z "$LAT" ] || [ -z "$LON" ]; then
    usage
fi

# ── 입력 파일 확인 ────────────────────────────────────────
if [ ! -f "$INPUT" ]; then
    echo "❌ 입력 파일 없음: $INPUT"
    exit 1
fi

INPUT_ABS=$(realpath "$INPUT")
INPUT_DIR=$(dirname "$INPUT_ABS")
INPUT_FILE=$(basename "$INPUT_ABS")
KEY_ABS=$(realpath "$KEY" 2>/dev/null || echo "$KEY")

echo "=============================================="
echo " BlueBON 기하보정 실행"
echo "=============================================="
echo "  입력: $INPUT_ABS"
echo "  위도: $LAT, 경도: $LON"
echo "  GPU:  $GPU"
echo ""

# ── Docker 실행 ──────────────────────────────────────────
docker run --rm \
    --gpus "$GPU" \
    -v "$INPUT_DIR:/data" \
    -v "$KEY_ABS:/app/Code/auth/ee-service-account-key.json:ro" \
    "$IMAGE_NAME" \
    --input "/data/$INPUT_FILE" \
    --lat "$LAT" \
    --lon "$LON" \
    "${EXTRA_ARGS[@]}"

echo ""
echo "✅ 완료. 결과 파일은 입력 파일과 같은 디렉토리에 저장됩니다:"
echo "   $INPUT_DIR"
