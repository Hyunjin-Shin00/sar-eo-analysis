#!/bin/bash
# lightglue 설치 스크립트

echo "🔧 LightGlue 설치 중..."

# 가상환경 활성화 확인
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  가상환경이 활성화되지 않았습니다."
    if [ -d "venv" ]; then
        echo "가상환경 활성화 중..."
        source venv/bin/activate
    else
        echo "❌ venv 디렉토리를 찾을 수 없습니다."
        exit 1
    fi
fi

# LightGlue GitHub에서 설치
echo "📦 GitHub에서 LightGlue 설치 중..."
pip install git+https://github.com/cvg/LightGlue.git

echo "✅ LightGlue 설치 완료!"

