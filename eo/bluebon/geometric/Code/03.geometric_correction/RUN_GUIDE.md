# 🚀 실행 가이드 (Quick Start Guide)

## 📌 단계별 실행 방법

### STEP 0: 환경 테스트 (필수!)

파이프라인을 실행하기 전에 환경이 올바르게 설정되었는지 확인하세요:

```bash
cd /path/to/geometric_correction
python quick_test.py
```

**예상 결과:**
```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    기하보정 파이프라인 환경 테스트                           ║
╚══════════════════════════════════════════════════════════════════════════════╝

================================================================================
1. 패키지 임포트 테스트
================================================================================
✅ PyTorch             - OK
✅ OpenCV              - OK
✅ NumPy               - OK
✅ Rasterio            - OK
✅ LightGlue           - OK

✅ 모든 패키지가 정상적으로 임포트되었습니다.
...
🎉 모든 테스트를 통과했습니다!
```

### STEP 1: 경로 설정

`geometric_correction.py` 파일을 열고 **main() 함수 내부**의 경로를 수정하세요:

```python
def main():
    # ========================================================================
    # 설정: 입력 파일 경로 및 출력 디렉토리
    # ========================================================================
    REFERENCE_PATH = "/your/path/to/reference_image.tif"
    TARGET_PATH = "/your/path/to/target_image.tif"
    DEM_PATH = "/your/path/to/dem.tif"
    OUTPUT_DIR = "/your/path/to/output"
```

**현재 기본 설정 (BlueBON Jamsil):**
```python
REFERENCE_PATH = "/media/<USER>/X10 Pro/02. Dataset/02. Geometric Correction/Input/BlueBON(Jamsil)/ReferenceImage/Sentinel_Jamsil_BlueBON.tif"
TARGET_PATH = "/media/<USER>/X10 Pro/02. Dataset/02. Geometric Correction/Input/BlueBON(Jamsil)/QueryImage/BlueBON_Jamsil(bottom)_rgb_resampling.tif"
DEM_PATH = "/media/<USER>/X10 Pro/02. Dataset/02. Geometric Correction/Input/BlueBON(Jamsil)/DEM/DEM_Merged.tif"
OUTPUT_DIR = "/media/<USER>/X10 Pro/02. Dataset/02. Geometric Correction/Output_Pipeline"
```

### STEP 2: 파이프라인 실행

```bash
python geometric_correction.py
```

**실행 화면 예시:**
```
================================================================================
모듈화된 기하보정 파이프라인 시작
================================================================================
시작 시간: 2025-01-15 14:30:00

================================================================================
STEP 1: 입력 파일 검증 및 메타데이터 추출
================================================================================
📂 Reference Image: /path/to/reference.tif
   ✅ CRS: EPSG:32652
   ✅ Size: 10980 x 10980
   ✅ Resolution: 10.00 x 10.00 m
...
```

### STEP 3: 결과 확인

파이프라인이 완료되면 `OUTPUT_DIR`에 다음과 같은 구조로 결과가 저장됩니다:

```
OUTPUT_DIR/
├── step02_unified_crs/
├── step03_cropped/
├── step04_normalized/
├── step05_lowres/
├── step06_ai_matching/
│   └── initial_matches.png        ← 초기 매칭 시각화
├── step07_ransac_filtered/
│   └── ransac_comparison.png      ← RANSAC 전/후 비교
├── step08_scaled_points/
├── step09_gcps/
│   └── initial_gcps.json
├── step10_initial_corrected/
│   └── target_initial_corrected.tif ← 1차 보정 결과
├── step11_recropped/
├── step12_patches/
├── step13_multistage/
├── step14_final_gcps/
│   └── final_gcps.json
├── step15_rpc_model/
│   └── rpc_model.json
├── step16_final_corrected/
│   └── target_final_corrected.tif ← ⭐ 최종 결과!
└── step17_accuracy_report/
    └── accuracy_report.json       ← 정확도 보고서
```

**중요 파일:**
- `step16_final_corrected/target_final_corrected.tif` : 최종 보정된 영상
- `step17_accuracy_report/accuracy_report.json` : 정확도 보고서
- `step15_rpc_model/rpc_model.json` : 생성된 RPC 모델

## 🎛️ 파라미터 조정

### 빠른 테스트 (정확도 낮음, 속도 빠름)

파일 상단의 설정을 다음과 같이 변경:

```python
INITIAL_MATCHING_RESOLUTION = 16  # 4 → 16
BUFFER_FACTOR = 1.5               # 기본값 유지
```

### 고정밀 모드 (정확도 높음, 속도 느림)

```python
INITIAL_MATCHING_RESOLUTION = 2   # 4 → 2
BUFFER_FACTOR = 2.0               # 1.5 → 2.0 (더 큰 버퍼)
```

### GPU 메모리 부족 시

```python
INITIAL_MATCHING_RESOLUTION = 8   # 해상도 낮춤
# 또는 CPU 모드로 전환
device = 'cpu'  # 'cuda' → 'cpu'
```

## 🔧 문제 해결

### 1. 메모리 부족 오류

```
RuntimeError: CUDA out of memory
```

**해결책:**
```python
# 해상도를 낮춥니다
INITIAL_MATCHING_RESOLUTION = 16  # 또는 32
```

### 2. GDAL 명령어 오류

```
FileNotFoundError: gdalwarp
```

**해결책:**
```bash
sudo apt-get install gdal-bin libgdal-dev
export PATH="/usr/bin:$PATH"
```

### 3. 매칭점이 너무 적음

```
⚠️ RPC 생성을 위해 최소 20개의 GCP 필요 (현재: 15개)
```

**해결책:**
```python
# SuperPoint의 keypoint 수를 증가
# geometric_correction.py 파일에서 수정
extractor = SuperPoint(max_num_keypoints=4096)  # 2048 → 4096
```

### 4. 좌표계 변환 오류

```
RuntimeError: TARGET 좌표계 변환 실패
```

**해결책:**
- TARGET 이미지가 좌표계 정보를 가지고 있는지 확인
- `gdalinfo target.tif`로 확인
- 좌표계가 없다면 사전에 추가 필요

### 5. 모듈 임포트 오류

```
ModuleNotFoundError: No module named 'geometric_correction'
```

**해결책:**
```bash
# 현재 디렉토리를 Python 경로에 추가
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
# 또는
python -m geometric_correction
```

## 📊 예상 실행 시간

| 영상 크기 | GPU (CUDA) | CPU |
|----------|------------|-----|
| 5K x 5K  | 15-20분 | 40-60분 |
| 10K x 10K | 25-35분 | 60-90분 |
| 20K x 20K | 40-60분 | 2-3시간 |

*시간은 시스템 사양에 따라 다를 수 있음.*

## 📸 결과 비교

### 보정 전 (TARGET 원본)
- ❌ 좌표계 정보 부정확 또는 없음
- ❌ REFERENCE와 위치 불일치

### 1차 보정 (TPS) - `step10_initial_corrected/`
- ✅ 대략적인 위치 보정
- ⚠️ 국지적 왜곡 존재 가능

### 최종 보정 (RPC) - `step16_final_corrected/`
- ✅ 고정밀 위치 보정
- ✅ 국지적 왜곡 최소화
- ✅ REFERENCE와 정확히 정렬

## 🎯 다음 단계

보정이 완료되면:

1. **QGIS로 결과 확인**
   ```bash
   qgis step16_final_corrected/target_final_corrected.tif
   ```

2. **품질 평가**
   - Reference와 Final 결과를 겹쳐서 확인
   - GCP 파일(`step14_final_gcps/final_gcps.json`)을 QGIS에 로드하여 매칭점 확인
   - 정확도 보고서(`step17_accuracy_report/accuracy_report.json`) 확인

3. **추가 처리**
   - 필요시 보정된 영상을 다른 분석에 사용
   - RPC 모델을 저장하여 동일 센서의 다른 영상에 적용

## 🔍 모듈별 상세 기능

### 📁 preprocessing.py
- 입력 파일 검증 및 메타데이터 추출
- 좌표계 통일 및 해상도 정규화
- 영역 크롭핑 및 저해상도 영상 생성

### 📁 initial_matching.py  
- AI 기반 특징점 매칭 (SuperPoint + LightGlue)
- RANSAC 아웃라이어 제거
- GCP 생성 및 초기 기하보정

### 📁 hierarchical_matching.py
- 다단계 계층적 매칭 (LoFTR 기반)
- 패치 기반 정밀 매칭
- 시각화 및 결과 저장

### 📁 precision_correction.py
- 최종 GCP 생성 및 품질 관리
- RPC/RFM 모델 생성
- 정밀 기하보정 및 정확도 검증

## 📞 지원

문제가 발생하면:
1. `quick_test.py`를 먼저 실행하여 환경 확인
2. 각 단계별 중간 결과물 확인
3. 로그 메시지에서 구체적인 오류 확인

---

**작성일**: 2025-01-15  
**버전**: 2.0 (모듈화)  
**업데이트**: 모듈화된 구조 반영

