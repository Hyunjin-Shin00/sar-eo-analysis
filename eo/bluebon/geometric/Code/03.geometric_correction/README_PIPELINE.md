# 2단계 정밀 기하보정 파이프라인

위성영상 간 정밀 기하보정을 수행하는 통합 파이프라인입니다.

## 📋 개요

이 파이프라인은 **20개의 명확한 STEP**으로 구성되어 있으며, 2단계 접근법을 사용합니다:

### 🎯 1단계: 전처리 및 1차 기하보정 (STEP 1-10)
1. **STEP 1**: 입력 파일 검증 및 메타데이터 추출
2. **STEP 2**: 좌표계 통일 (REFERENCE 기준)
3. **STEP 3**: 해상도 정규화
4. **STEP 4**: TARGET 영역 기준 잘라내기 (버퍼 포함)
5. **STEP 5**: 저해상도 영상 생성 (빠른 매칭용)
6. **STEP 6**: AI 기반 특징점 매칭 (SuperPoint + LightGlue)
7. **STEP 7**: RANSAC 기반 아웃라이어 제거
8. **STEP 8**: 좌표 스케일링 (저해상도 → 원본)
9. **STEP 9**: GCP (Ground Control Points) 생성
10. **STEP 10**: TPS 기반 1차 기하보정

### 🎯 2단계: 정밀 기하보정 (STEP 11-20)
11. **STEP 11**: Stage 2 매칭 (1/8 해상도)
12. **STEP 12**: Stage 3 매칭 (1/4 해상도)
13. **STEP 13**: Stage 4 매칭 (1/2 해상도)
14. **STEP 14**: Stage 5 매칭 (원본 해상도)
15. **STEP 15**: 최종 GCP 생성
16. **STEP 16**: RPC 파라미터 계산
17. **STEP 17**: RPC 모델 검증
18. **STEP 18**: RPC 모델 저장
19. **STEP 19**: RPC 메타데이터 임베딩
20. **STEP 20**: RPC 기반 최종 워핑

## 🚀 설치

### 1. 시스템 요구사항
- Python 3.8 이상
- GDAL 3.0 이상 (시스템 레벨 설치 필요)
- CUDA 지원 GPU (선택사항, CPU로도 실행 가능)

### 2. GDAL 설치 (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install gdal-bin libgdal-dev
```

### 3. Python 패키지 설치
```bash
# 가상환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 또는
venv\Scripts\activate  # Windows

# 의존성 설치
pip install -r requirements_pipeline.txt

# GDAL Python 바인딩 (시스템 GDAL 버전 확인 후)
gdal-config --version  # 예: 3.4.1
pip install gdal==$(gdal-config --version)
```

## 📖 사용법

### 기본 사용

```python
# geometric_correction_pipeline_v1.py 파일의 main() 함수 내 경로 수정

REFERENCE_PATH = "/path/to/reference_image.tif"
TARGET_PATH = "/path/to/target_image.tif"
DEM_PATH = "/path/to/dem.tif"
OUTPUT_DIR = "/path/to/output"

# 실행
python geometric_correction_pipeline_v1.py
```

### 파라미터 조정

파일 상단의 전역 설정 변수를 수정하여 파이프라인을 조정할 수 있습니다:

```python
# 1차 매칭 설정
INITIAL_MATCHING_RESOLUTION = 8  # 1/8 해상도 (빠른 매칭)
INITIAL_MATCHING_METHOD = "superpoint"  # "superpoint" or "loftr"

# 다단계 정밀 매칭 설정
STAGE2_RESOLUTION = 8   # 1/8
STAGE3_RESOLUTION = 4   # 1/4
STAGE4_RESOLUTION = 2   # 1/2
STAGE5_RESOLUTION = 1   # 원본

# 영역 추출 버퍼
BUFFER_FACTOR = 1.5  # 1.5 = 50% 버퍼
```

## 📂 출력 구조

```
OUTPUT_DIR/
├── 01_unified_crs/           # 좌표계 통일된 파일
├── 02_normalized_resolution/ # 해상도 정규화된 파일
├── 03_cropped/               # 잘라낸 영역
├── 04_lowres_matching/       # 저해상도 매칭 결과
├── 05_gcps/                  # 초기 GCP
├── 06_tps_corrected/         # TPS 1차 보정 결과
├── 07_multistage_matching/   # 다단계 매칭 결과
├── 08_final_gcps/            # 최종 GCP
├── 09_rpc_model/             # RPC 모델
├── 10_final_corrected/       # 최종 보정 영상
└── pipeline_report.txt       # 실행 보고서
```

## 🔧 주요 기능

### 1. 좌표계 및 해상도 자동 통일
- REFERENCE 이미지를 기준으로 모든 데이터의 좌표계를 자동 변환
- 해상도를 일치시켜 정확한 매칭 수행

### 2. 지능형 영역 추출
- TARGET 영상 범위를 기준으로 REFERENCE 영상을 자동 잘라냄
- 버퍼를 추가하여 경계 효과 최소화

### 3. 계층적 매칭 전략
- **1차 매칭**: 저해상도(1/8)로 빠르게 대략적인 변환 추정
- **2차 매칭**: 다단계(1/8 → 1/4 → 1/2 → 원본)로 점진적 정밀화

### 4. AI 기반 특징점 매칭
- SuperPoint: 강건한 특징점 추출
- LightGlue: 고속 고정밀 매칭
- RANSAC: 아웃라이어 자동 제거

### 5. TPS + RPC 이중 보정
- **TPS (Thin Plate Spline)**: 유연한 비선형 변환 (1차 보정)
- **RPC (Rational Polynomial Coefficients)**: 정밀한 기하 모델 (최종 보정)

### 6. DEM 기반 고도 보정
- DEM을 활용하여 3D GCP 생성
- 지형 효과를 고려한 정밀 보정

## 📊 성능

### 처리 시간 (예상)
- **STEP 1-5** (전처리): 2-5분
- **STEP 6-10** (1차 보정): 5-10분
- **STEP 11-14** (다단계 매칭): 10-20분
- **STEP 15-20** (RPC 보정): 5-10분
- **총 소요 시간**: 약 20-45분 (영상 크기에 따라 다름)

### GPU vs CPU
- **GPU (CUDA)**: 약 3-5배 빠름 (특히 AI 매칭 부분)
- **CPU**: 느리지만 모든 기능 사용 가능

## ⚠️ 주의사항

### 1. 입력 데이터 요구사항
- **REFERENCE**: 반드시 좌표계 정보(CRS) 포함
- **TARGET**: 좌표계 정보가 없어도 됨 (추정 가능)
- **DEM**: REFERENCE와 동일한 영역을 커버해야 함

### 2. 메모리 요구사항
- 대용량 영상(>10,000 x 10,000)의 경우 16GB 이상 RAM 권장
- GPU 메모리 부족 시 `INITIAL_MATCHING_RESOLUTION` 값 증가 (예: 16)

### 3. 좌표계 호환성
- REFERENCE와 TARGET의 좌표계가 크게 다를 경우 자동 변환
- 투영 좌표계 권장 (위경도 좌표계는 거리 계산이 부정확할 수 있음)

## 🐛 문제 해결

### GDAL 명령어를 찾을 수 없음
```bash
# GDAL이 PATH에 있는지 확인
which gdalwarp
which gdal_translate

# 없다면 GDAL 재설치
sudo apt-get install --reinstall gdal-bin
```

### GPU 메모리 부족
```python
# 파일 내 해상도 설정 변경
INITIAL_MATCHING_RESOLUTION = 16  # 8 → 16으로 증가
```

### 매칭점이 너무 적음
```python
# SuperPoint의 keypoint 수 증가
extractor = SuperPoint(max_num_keypoints=4096)  # 2048 → 4096
```

## 📝 추가 기능 (기존 프로젝트 대비)

이 파이프라인은 기존 프로젝트들을 통합하면서 다음 기능들을 추가했습니다:

✅ **20개 STEP으로 명확하게 구조화**
✅ **자동 좌표계 통일 및 해상도 정규화**
✅ **버퍼를 포함한 지능형 영역 추출**
✅ **TPS + RPC 이중 보정 전략**
✅ **DEM 기반 3D GCP 생성**
✅ **다단계 계층적 매칭 (1/8 → 원본)**
✅ **자동 시각화 및 보고서 생성**
✅ **단계별 중간 결과 저장**
✅ **에러 핸들링 및 로깅**
✅ **RANSAC 기반 자동 품질 관리**

## 📚 참고 자료

- [GDAL Documentation](https://gdal.org/)
- [LightGlue Paper](https://arxiv.org/abs/2306.13643)
- [SuperPoint Paper](https://arxiv.org/abs/1712.07629)
- [RPC Model Specification](https://www.ogc.org/standards/rpc)

## 📧 문의

문제가 발생하거나 개선 사항이 있으면 이슈를 등록해주세요.

---

**버전**: 1.0  
**최종 업데이트**: 2025-10-13  
**라이선스**: MIT

