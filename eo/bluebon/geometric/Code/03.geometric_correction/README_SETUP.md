# 🛠️ 가상환경 설정 가이드

기하보정 파이프라인을 위한 가상환경 설정 방법임.

## 📋 사전 요구사항

- Python 3.8 이상
- pip (Python 패키지 관리자)
- (선택) conda (GDAL 설치 시 권장)

## 🚀 빠른 시작

### 방법 1: Python 스크립트 사용 (권장 - 모든 플랫폼)

```bash
python setup_venv.py
```

### 방법 2: 플랫폼별 스크립트 사용

#### macOS / Linux
```bash
chmod +x setup_venv.sh
./setup_venv.sh
```

#### Windows
```batch
setup_venv.bat
```

### 방법 3: 수동 설정

```bash
# 1. 가상환경 생성
python -m venv venv

# 2. 가상환경 활성화
# macOS/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 3. pip 업그레이드
pip install --upgrade pip setuptools wheel

# 4. GDAL 설치 (시스템 레벨)
# macOS:
brew install gdal
# Ubuntu/Debian:
sudo apt-get update
sudo apt-get install gdal-bin libgdal-dev

# 5. 패키지 설치
pip install -r requirements.txt
```

## 📦 설치되는 주요 패키지

### 딥러닝/AI 매칭
- `torch` >= 2.0.0
- `torchvision` >= 0.15.0
- `lightglue` >= 0.1.0
- `kornia` >= 0.7.0

### 지리공간 데이터 처리
- `rasterio` >= 1.3.0
- `pyproj` >= 3.6.0
- `gdal` (시스템 레벨 설치 필요)

### 영상 처리
- `opencv-python` >= 4.8.0
- `numpy` >= 1.24.0
- `pillow` >= <INTERNAL_HOST>

### 기타
- `matplotlib` >= 3.7.0
- `pandas` >= 2.0.0
- `scikit-learn` >= 1.3.0

## ⚠️ GDAL 설치 주의사항

GDAL은 지리공간 데이터 처리를 위한 중요한 라이브러리임. 시스템 레벨에서 먼저 설치해야 함.

### macOS
```bash
brew install gdal
pip install gdal==$(gdal-config --version)
```

### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install gdal-bin libgdal-dev
pip install gdal==$(gdal-config --version)
```

### Windows
1. **OSGeo4W 설치**: https://trac.osgeo.org/osgeo4w/
2. 또는 **conda 사용** (권장):
   ```bash
   conda install -c conda-forge gdal
   ```

### Conda 사용 (모든 플랫폼 권장)
```bash
conda create -n geometric_correction python=3.9
conda activate geometric_correction
conda install -c conda-forge gdal
pip install -r requirements.txt
```

## 🔍 설치 확인

가상환경을 활성화한 후 다음 명령어로 설치 확인:

```bash
python -c "import torch; import cv2; import rasterio; import gdal; print('✅ 모든 패키지 설치 완료')"
```

## 📝 사용법

### GUI 앱 실행
```bash
# 가상환경 활성화
source venv/bin/activate  # macOS/Linux
# 또는
venv\Scripts\activate  # Windows

# GUI 앱 실행
python gui_app.py
```

### 파이프라인 직접 실행
```bash
python geometric_correction.py
```

## 🐛 문제 해결

### GDAL 설치 오류
- conda 사용 권장: `conda install -c conda-forge gdal`
- 또는 시스템 패키지 관리자 사용 (apt, brew, yum 등)

### CUDA/GPU 관련 오류
- CUDA가 필요한 경우 PyTorch CUDA 버전 설치
- CPU만 사용하는 경우 문제 없음

### 메모리 부족
- 대용량 이미지 처리 시 충분한 RAM 필요
- 필요시 이미지 크기 조정

## 📚 추가 정보

자세한 내용은 다음 파일을 참조하세요:
- `requirements.txt`: 전체 패키지 목록
- `README.md`: 프로젝트 개요
- `RUN_GUIDE.md`: 실행 가이드

