# GUI 앱을 독립 실행 파일로 만들기

GUI 앱을 PyInstaller를 사용하여 독립 실행 파일(executable)로 만들 수 있음.

## ⚠️ 주의사항

이 프로젝트는 다음과 같은 특수 라이브러리를 사용하므로 빌드가 복잡할 수 있습니다:

1. **GDAL**: 시스템 레벨 설치 필요 (별도 처리 필요)
2. **PyTorch**: 매우 큰 파일 크기 (수백 MB)
3. **AI 모델 가중치**: 추가 디렉토리 필요
4. **지리공간 라이브러리**: 여러 바이너리 의존성

### 예상 파일 크기
- **최소**: 500MB ~ 1GB (PyTorch 포함)
- **실제**: 1GB ~ 2GB (모든 의존성 포함)

## 빌드 방법

### 1. PyInstaller 설치

```bash
# 가상환경 활성화
source venv/bin/activate  # macOS/Linux
# 또는
venv\Scripts\activate  # Windows

# PyInstaller 설치
pip install pyinstaller
```

### 2. 빌드 실행

```bash
# macOS/Linux
pyinstaller build_app.spec

# Windows
pyinstaller build_app.spec
```

### 3. 실행 파일 위치

빌드가 완료되면 다음 위치에 실행 파일이 생성됩니다:

```
dist/
  └── GeometricCorrectionGUI  # macOS/Linux
  └── GeometricCorrectionGUI.exe  # Windows
```

## 제한사항 및 해결 방법

### 1. GDAL 문제

**문제**: GDAL은 시스템 레벨 라이브러리라 PyInstaller에 자동 포함되지 않음

**해결 방법**:
- macOS: GDAL을 번들에 포함시키거나, 사용자가 별도 설치 필요
- Windows: OSGeo4W를 번들에 포함
- 또는 Docker 컨테이너로 배포 고려

### 2. 모델 가중치 파일

**문제**: LoFTR, LightGlue 등의 모델 가중치는 런타임에 다운로드됨

**해결 방법**:
- 모델 파일을 미리 다운로드하여 `datas`에 추가
- 첫 실행 시 자동 다운로드 설정

### 3. 파일 크기

**문제**: 파일이 매우 큼

**해결 방법**:
- UPX 압축 사용 (build_app.spec에서 `upx=True`)
- 선택적 모듈 로딩
- 별도의 모델 파일 분리

## 대안 방법

### 방법 1: 포터블 앱 (추천)

가상환경 전체를 포터블 앱으로 만들기:

```bash
# venv 폴더 전체를 압축
# 사용자는 압축 해제 후 실행
cd venv/bin
./python gui_app.py  # macOS/Linux
```

**장점**:
- 빌드 과정이 단순함
- 모든 의존성 포함
- GDAL 등 시스템 라이브러리도 포함 가능

**단점**:
- 파일 크기가 큼 (2GB+)
- 플랫폼별로 별도 빌드 필요

### 방법 2: Docker 이미지 (추천)

Docker 컨테이너로 패키징:

```dockerfile
FROM python:3.9-slim

# GDAL 설치
RUN apt-get update && apt-get install -y \
    gdal-bin libgdal-dev python3-gdal

# 의존성 설치
COPY requirements.txt .
RUN pip install -r requirements.txt

# 앱 복사
COPY . /app
WORKDIR /app

# GUI 실행 (X11 forwarding 필요)
CMD ["python", "gui_app.py"]
```

**장점**:
- 모든 의존성 포함
- 플랫폼 독립적
- 재현 가능한 환경

**단점**:
- Docker 설치 필요
- GUI는 X11 forwarding 또는 VNC 필요

### 방법 3: 설치 스크립트 제공

자동 설치 스크립트 제공 (현재 방식):

```bash
# 사용자가 실행
./setup_venv.sh  # macOS/Linux
setup_venv.bat   # Windows
python gui_app.py
```

**장점**:
- 가장 안정적
- 업데이트 용이
- 플랫폼별 최적화 가능

**단점**:
- Python 설치 필요
- 초기 설정 시간 소요

## 실용적 권장사항

현재 프로젝트의 경우, **방법 1 (포터블 앱)** 또는 **방법 3 (설치 스크립트)**을 권장합니다:

1. **개발/테스트 환경**: 방법 3 (설치 스크립트) - 가장 안정적
2. **내부 사용자 배포**: 방법 1 (포터블 앱) - 간단한 실행
3. **대규모 배포**: 방법 2 (Docker) - 환경 일관성 보장

## 테스트

빌드 후 테스트:

```bash
# 빌드된 실행 파일 실행
./dist/GeometricCorrectionGUI  # macOS/Linux
dist\GeometricCorrectionGUI.exe  # Windows

# 또는 간단 테스트
python -c "import PyInstaller; print('PyInstaller 설치됨')"
```

## 추가 최적화

필요시 다음을 고려할 수 있습니다:

1. **아이콘 추가**: `icon='icon.ico'` (Windows) 또는 `icon='icon.icns'` (macOS)
2. **버전 정보**: `version_info` 추가
3. **코드 서명**: macOS 앱 스토어 배포 시 필요
4. **NSIS 설치 프로그램**: Windows용 설치 프로그램 생성

## 참고 자료

- [PyInstaller 문서](https://pyinstaller.org/)
- [PyInstaller Hook 예제](https://github.com/pyinstaller/pyinstaller/tree/develop/PyInstaller/hooks)
- [GDAL과 PyInstaller](https://gis.stackexchange.com/questions/337983/bundling-gdal-with-pyinstaller)

