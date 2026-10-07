#!/bin/bash
echo "BlueBON 서버 종료 중..."
pkill -f "uvicorn main:app" 2>/dev/null && echo "  ✓ 백엔드 종료"
pkill -f "vite" 2>/dev/null && echo "  ✓ 프론트엔드 종료"
echo "완료"
