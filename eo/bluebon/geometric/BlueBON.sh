#!/bin/bash
# BlueBON Geometric Correction Web App 실행 스크립트

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/Code/web_app/backend"
FRONTEND_DIR="$PROJECT_DIR/Code/web_app/frontend"
CONDA_PYTHON="/mnt/hdd/miniconda3/envs/geo_unified/bin/python"
LOG_DIR="/tmp/bluebon_logs"

mkdir -p "$LOG_DIR"

echo "=========================================="
echo "  BlueBON Geometric Correction Web App"
echo "=========================================="

# ── 이전 프로세스 정리 ──────────────────────────────────────
echo "[1/3] 기존 프로세스 정리 중..."
pkill -f "uvicorn main:app" 2>/dev/null
pkill -f "vite" 2>/dev/null
sleep 1

# ── 백엔드 시작 ─────────────────────────────────────────────
echo "[2/3] 백엔드 시작 (port 8000)..."
cd "$BACKEND_DIR"
"$CONDA_PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8000 \
    > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

# 백엔드 준비 대기
for i in $(seq 1 15); do
    if curl -s http://localhost:8000/api/sheet/data > /dev/null 2>&1; then
        echo "    ✓ 백엔드 준비됨 (PID: $BACKEND_PID)"
        break
    fi
    sleep 0.5
done

# ── 프론트엔드 시작 ─────────────────────────────────────────
echo "[3/3] 프론트엔드 시작 (port 5173)..."
cd "$FRONTEND_DIR"
npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
sleep 2

echo ""
echo "=========================================="
echo "  실행 완료!"
echo "  브라우저: http://localhost:5173"
echo ""
echo "  백엔드 로그:   $LOG_DIR/backend.log"
echo "  프론트엔드 로그: $LOG_DIR/frontend.log"
echo ""
echo "  종료하려면: ./stop.sh  또는  Ctrl+C"
echo "=========================================="

# Ctrl+C 시 두 프로세스 모두 종료
cleanup() {
    echo ""
    echo "종료 중..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# 브라우저 자동 열기
sleep 1
xdg-open "http://localhost:5173" 2>/dev/null &

# 로그 실시간 출력
tail -f "$LOG_DIR/backend.log" &
wait $BACKEND_PID
