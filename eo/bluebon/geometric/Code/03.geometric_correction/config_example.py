
"""
설정 파일 예제
실제 사용시 이 파일을 복사하여 config.py로 저장하고 경로를 수정하세요.
"""

# ==============================================================================
# 입력 파일 경로
# ==============================================================================

# REFERENCE 위성영상 (기준 영상 - 반드시 좌표계 정보 포함)
REFERENCE_PATH = "/path/to/your/reference_image.tif"

# TARGET 위성영상 (보정 대상 영상)
TARGET_PATH = "/path/to/your/target_image.tif"

# DEM (Digital Elevation Model)
DEM_PATH = "/path/to/your/dem.tif"

# 출력 디렉토리
OUTPUT_DIR = "/path/to/output"

# ==============================================================================
# 매칭 설정
# ==============================================================================

# 1차 매칭 해상도 (숫자가 클수록 빠르지만 정확도 감소)
# 권장: 8 (대부분의 경우), 16 (매우 큰 영상), 4 (고정밀 필요)
INITIAL_MATCHING_RESOLUTION = 8

# AI 매칭 방법 선택
# 옵션: "superpoint" (현재 구현됨), "loftr" (향후 추가 예정)
INITIAL_MATCHING_METHOD = "superpoint"

# 초기 기하보정 방법
# 옵션: "AFFINE", "TPS"
INITIAL_CORRECTION_METHOD = "AFFINE"

# 저해상도 스케일 (다운샘플링 비율)
LOWRES_SCALE = 0.25

# 매칭 임계값 (0.0 ~ 1.0)
MATCHING_THRESHOLD = 0.7

# ==============================================================================
# 다단계 매칭 설정
# ==============================================================================

# 각 Stage의 해상도 설정
STAGE2_RESOLUTION = 8   # Stage 2: 1/8 해상도
STAGE3_RESOLUTION = 4   # Stage 3: 1/4 해상도
STAGE4_RESOLUTION = 2   # Stage 4: 1/2 해상도
STAGE5_RESOLUTION = 1   # Stage 5: 원본 해상도

# ==============================================================================
# 영역 추출 설정
# ==============================================================================

# TARGET 영역 주변 버퍼 배율
# 1.0 = 버퍼 없음, 1.5 = 50% 버퍼, 2.0 = 100% 버퍼
BUFFER_FACTOR = 1.5

# ==============================================================================
# GPU/CPU 설정
# ==============================================================================

# GPU 사용 강제 (False: 자동 감지, True: GPU 강제)
FORCE_GPU = False

# GPU 메모리 제한 (MB, None: 제한 없음)
GPU_MEMORY_LIMIT = None

# ==============================================================================
# 고급 설정
# ==============================================================================

# RPC 생성을 위한 최소 GCP 개수
MIN_GCPS_FOR_RPC = 20

# RANSAC 파라미터
RANSAC_THRESHOLD = 5.0      # 픽셀 단위
RANSAC_MAX_ITERS = 5000     # 최대 반복 횟수
RANSAC_CONFIDENCE = 0.99    # 신뢰도 (0-1)

# SuperPoint 설정
SUPERPOINT_MAX_KEYPOINTS = 2048  # 추출할 최대 keypoint 수

# 중간 결과 저장 여부
SAVE_INTERMEDIATE_RESULTS = True

# 시각화 설정
ENABLE_VISUALIZATION = True  # 매칭 결과 시각화 활성화/비활성화

# GRID 필터링 설정
ENABLE_GRID_FILTERING = False  # GRID 기반 균등 분포 필터링 활성화/비활성화

# 로그 상세도 설정
# True: 상세 디버그 로그 출력, False: 요약 로그만 출력
VERBOSE = False

# 시각화 생성 여부
GENERATE_VISUALIZATIONS = True

# ==============================================================================
# 데이터셋 별 설정 예제
# ==============================================================================

# 예제 1: BlueBON Jamsil 데이터셋
BLUEBON_JAMSIL = {
    'reference': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/Input/BlueBON(Jamsil)/ReferenceImage/Sentinel_Jamsil_BlueBON.tif",
    'target': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/Input/BlueBON(Jamsil)/QueryImage/BlueBON_Jamsil(bottom)_rgb_resampling.tif",
    'dem': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/Input/BlueBON(Jamsil)/DEM/DEM_Merged.tif",
    'output': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/Output_Pipeline",
}

# 예제 2: RapidEye France 데이터셋
RAPIDEYE_FRANCE = {
    'reference': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/Input/Sentinel_France_RapidEye.tif",
    'target': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/Input/RapidEye-TrueColor_RGB_100km_shift.tif",
    'dem': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/DEM/SRTM/RapidEye_France/Merged.tif",
    'output': "/media/steve/X10 Pro/02. Dataset/02. Geometric Correction/Output_RapidEye",
}

# 사용할 데이터셋 선택
CURRENT_DATASET = BLUEBON_JAMSIL

# 선택한 데이터셋으로 경로 설정
REFERENCE_PATH = CURRENT_DATASET['reference']
TARGET_PATH = CURRENT_DATASET['target']
DEM_PATH = CURRENT_DATASET['dem']
OUTPUT_DIR = CURRENT_DATASET['output']

