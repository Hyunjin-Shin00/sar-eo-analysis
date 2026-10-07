#!/bin/bash
# 가상환경 설정 스크립트 (Linux/macOS)

set -e  # 오류 발생 시 즉시 종료

echo "=========================================="
echo "기하보정 파이프라인 가상환경 설정"
echo "=========================================="

# Python 버전 확인
echo ""
echo "📌 Python 버전 확인 중..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "   Python 버전: $python_version"

# Python 3.8 이상인지 확인
required_version="3.8"
if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
    echo "❌ Python 3.8 이상이 필요합니다. 현재 버전: $python_version"
    exit 1
fi

# 가상환경 생성
VENV_NAME="venv"
if [ -d "$VENV_NAME" ]; then
    echo ""
    echo "⚠️  가상환경 '$VENV_NAME'가 이미 존재합니다."
    read -p "   삭제하고 다시 만들까요? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "   기존 가상환경 삭제 중..."
        rm -rf "$VENV_NAME"
    else
        echo "   기존 가상환경을 사용합니다."
        source "$VENV_NAME/bin/activate"
        pip install --upgrade pip
        pip install -r requirements.txt
        echo ""
        echo "✅ 가상환경 설정 완료!"
        echo ""
        echo "가상환경 활성화:"
        echo "   source $VENV_NAME/bin/activate"
        exit 0
    fi
fi

echo ""
echo "📦 가상환경 생성 중..."
python3 -m venv "$VENV_NAME"

# 가상환경 활성화
echo "🔌 가상환경 활성화 중..."
source "$VENV_NAME/bin/activate"

# pip 업그레이드
echo ""
echo "⬆️  pip 업그레이드 중..."
pip install --upgrade pip setuptools wheel

# GDAL 확인
echo ""
echo "🔍 GDAL 설치 확인 중..."
if command -v gdal-config &> /dev/null; then
    gdal_version=$(gdal-config --version)
    echo "   ✅ GDAL이 설치되어 있습니다 (버전: $gdal_version)"
    echo "   GDAL Python 바인딩 설치 중..."
    pip install gdal==$gdal_version
else
    echo "   ⚠️  GDAL이 시스템에 설치되어 있지 않습니다."
    echo ""
    echo "   macOS에서 GDAL 설치:"
    echo "      brew install gdal"
    echo ""
    echo "   Ubuntu/Debian에서 GDAL 설치:"
    echo "      sudo apt-get update"
    echo "      sudo apt-get install gdal-bin libgdal-dev"
    echo ""
    echo "   또는 conda 사용:"
    echo "      conda install -c conda-forge gdal"
    echo ""
    read -p "   계속 진행하시겠습니까? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   설치가 취소되었습니다."
        deactivate
        exit 1
    fi
fi

# requirements.txt 설치
echo ""
echo "📥 패키지 설치 중..."
echo "   이 과정은 몇 분이 소요될 수 있습니다..."
pip install -r requirements.txt

echo ""
echo "=========================================="
echo "✅ 가상환경 설정 완료!"
echo "=========================================="
echo ""
echo "가상환경 활성화:"
echo "   source $VENV_NAME/bin/activate"
echo ""
echo "GUI 앱 실행:"
echo "   python gui_app.py"
echo ""
echo "파이프라인 직접 실행:"
echo "   python geometric_correction.py"
echo ""
echo "가상환경 비활성화:"
echo "   deactivate"
echo ""

