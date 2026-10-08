"""
==============================================================================
RPC 생성 및 정사보정 파이프라인 (JSON GCP 기반)
==============================================================================

EXPERIMENT_SETS 설정 후 기존 파이프라인(STEP 1-14)이 생성한
step14_final_gcps_original_target.json 을 읽어
STEP 15 (RPC 생성) → STEP 16 (정사보정) → GCP Chip 추출 까지 실행합니다.

[사용법]
  python Weight_.py                         # CURRENT_SET 사용
  python Weight_.py --set t1               # 특정 셋 지정
  python Weight_.py --weight 5000          # GCP 가중치 직접 지정
"""

# Standard library (PROJ 설정 전 가장 먼저)
import os
import sys
import json
from datetime import datetime

# ==============================================================================
# PROJ_DATA 설정 — shell PROJ_LIB 제거 후 conda env 경로 강제 설정
# 원인: shell PROJ_LIB=/mnt/hdd/miniconda3/share/proj (base conda, VERSION.MINOR=2)가
#       env의 pyproj/GDAL(VERSION.MINOR>=6)와 버전 충돌.
# 수정: (1) pyproj import 전에 env var pop (import 중 caching 방지)
#       (2) sys.prefix/share/proj로 경로 직접 결정 (env var 의존 없음)
#       (3) osr.SetPROJSearchPaths()로 GDAL PROJ context에도 반영 (rasterio 포함)
# ==============================================================================
os.environ.pop('PROJ_LIB', None)   # pyproj import 전에 제거 — caching 방지
os.environ.pop('PROJ_DATA', None)
_conda_proj = os.path.join(sys.prefix, 'share', 'proj')
if os.path.exists(os.path.join(_conda_proj, 'proj.db')):
    os.environ['PROJ_DATA'] = _conda_proj
    os.environ['PROJ_LIB'] = _conda_proj
    try:
        import pyproj.datadir as _ppd
        if hasattr(_ppd, 'set_data_dir'):
            _ppd.set_data_dir(_conda_proj)
        del _ppd
    except Exception:
        pass
del _conda_proj
# ==============================================================================

# 나머지 stdlib imports
import warnings
import logging
import platform

# 모듈 경로: geometric_correction 패키지를 찾기 위해 스크립트 디렉토리 추가
cwd = os.path.dirname(os.path.abspath(__file__))
if cwd not in sys.path:
    sys.path.append(cwd)

# Geospatial (PROJ 설정 후 import)
import rasterio
from rasterio.control import GroundControlPoint
from osgeo import gdal, osr

try:
    gdal.UseExceptions()
except Exception:
    pass

# GDAL PROJ context에 올바른 경로 전달 (rasterio는 GDAL 경유로 PROJ 사용)
try:
    _proj_data = os.environ.get('PROJ_DATA', '')
    if _proj_data and hasattr(osr, 'SetPROJSearchPaths'):
        osr.SetPROJSearchPaths([_proj_data])
except Exception:
    pass

# Visualization
import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
matplotlib.use('Agg')

# sklearn
try:
    from sklearn.linear_model import Ridge
except ImportError:
    print("="*80)
    print("❌ 'scikit-learn' 라이브러리가 필요합니다.")
    print("   pip install scikit-learn 또는 conda install scikit-learn을 실행하세요.")
    print("="*80)
    raise
# ------------------------------------------------------------------------------

from geometric_correction.pipeline.precision_correction import (
    Setting_Weight,
    step15_rpcfit_generate,
    step16_orthorectification,
    extract_gcp_chips_from_final_image,
)


# ==============================================================================
# 한글 폰트 설정
# ==============================================================================
def setup_korean_font():
    """한글 폰트 설정 (경고 메시지 제거)"""
    warnings.filterwarnings('ignore', category=UserWarning)

    font_list = fm.findSystemFonts(fontpaths=None, fontext='ttf')
    system_name = platform.system()
    if system_name == 'Windows':
        font_names = ['Malgun Gothic', 'Gulim', 'Batang', 'Dotum',
                      'NanumGothic', 'NanumBarunGothic']
    elif system_name == 'Darwin':
        font_names = ['AppleGothic', 'NanumGothic', 'NanumBarunGothic', 'Arial']
    else:
        font_names = ['NanumGothic', 'NanumBarunGothic',
                      'Noto Sans CJK KR', 'Noto Sans KR', 'DejaVu Sans']

    korean_fonts = []
    for font_path in font_list:
        for font_name in font_names:
            if (font_name.lower() in font_path.lower()
                    or font_name.lower().replace(' ', '') in font_path.lower()):
                korean_fonts.append((font_name, font_path))
                break

    font_set = False
    if korean_fonts:
        try:
            font_name, font_path = korean_fonts[0]
            font_prop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = font_prop.get_name()
            plt.rcParams['font.size'] = 10
            font_set = True
        except Exception:
            pass

    if not font_set:
        try:
            if system_name == 'Windows':
                plt.rcParams['font.family'] = 'Malgun Gothic'
            elif system_name == 'Darwin':
                plt.rcParams['font.family'] = 'AppleGothic'
            else:
                plt.rcParams['font.family'] = 'DejaVu Sans'
        except Exception:
            plt.rcParams['font.family'] = 'DejaVu Sans'

    plt.rcParams['axes.unicode_minus'] = False
    logging.getLogger('matplotlib').setLevel(logging.ERROR)


# ==============================================================================
# 메인 파이프라인
# ==============================================================================
def main(gcp_weight: int = None, current_set: str = "t1"):
    """
    EXPERIMENT_SETS → JSON GCP 읽기 → RPC 생성 → 정사보정 → GCP Chip 추출

    Parameters
    ----------
    gcp_weight : int, optional
        Real GCP 복제 횟수. None이면 EXPERIMENT_SETS 또는 Setting_Weight 자동 계산.
    current_set : str
        EXPERIMENT_SETS 키 이름 (기본값: "t1").
    """
    # ========================================================================
    # 실험 셋 설정
    # ========================================================================
    EXPERIMENT_SETS = {
        "t1": {
            "name": "bb_l1a_20260208_190833_8band Center",
            "dem":          '<WORK_ROOT>/Desktop/KHJ_Geometric/BlueBON_Geometric_Correction_260317_Linux/Dataset/bb_l1a_20251227_073223_8band/Center/01_Download_open_data/Copernicus_DEM_center.tif',
            "geoid":        '<WORK_ROOT>/Desktop/KHJ_Geometric/BlueBON_Geometric_Correction_260317_Linux/Dataset/bb_l1a_20251227_073223_8band/Center/01_Download_open_data/Geoid_center.tif',
            "reference":    '<WORK_ROOT>/Desktop/KHJ_Geometric/BlueBON_Geometric_Correction_260317_Linux/Dataset/bb_l1a_20251227_073223_8band/Center/01_Download_open_data/S2_mosaic_2025-12-23.tif',
            "output":       '<WORK_ROOT>/Desktop/KHJ_Geometric/BlueBON_Geometric_Correction_260317_Linux/Dataset/bb_l1a_20251227_073223_8band/Center/output_GCP',
            "target":       '<WORK_ROOT>/Desktop/KHJ_Geometric/BlueBON_Geometric_Correction_260317_Linux/Dataset/bb_l1a_20251227_073223_8band/Center/00_Divided_image/merged_center.tif',
            "target_center_lat":  24.89618, 
            "target_center_lon":  54.94587,
            "target_resolution": 4.8,
            "target_bands": [4,3,2],
            "normalized_paths":
            '<WORK_ROOT>/Desktop/KHJ_Geometric/BlueBON_Geometric_Correction_260317_Linux/Dataset/bb_l1a_20251227_073223_8band/Center/step11_recropped/step04_normalized/reference_normalized.tif',
            "gcp_weight": 90000,  # 직접 지정 시 주석 해제
        },
    }

    CURRENT_SET = current_set

    # ========================================================================
    # 경로 로드
    # ========================================================================
    if CURRENT_SET not in EXPERIMENT_SETS:
        raise ValueError(f"실험 셋 '{CURRENT_SET}'을 찾을 수 없습니다. "
                         f"사용 가능한 셋: {list(EXPERIMENT_SETS.keys())}")

    current_exp = EXPERIMENT_SETS[CURRENT_SET]
    DEM_PATH = current_exp["dem"]
    GEOID_PATH = current_exp.get("geoid", None)
    TARGET_PATH = current_exp["target"]
    OUTPUT_DIR = current_exp["output"]
    TARGET_BANDS = current_exp.get("target_bands", None)
    NORMALIZED_PATHS = current_exp.get("normalized_paths", None)

    print("\n" + "=" * 80)
    print(f"RPC 생성 및 정사보정 파이프라인 시작")
    print("=" * 80)
    print(f"📌 실험 셋: {current_exp['name']} ({CURRENT_SET})")
    print(f"📁 TARGET : {TARGET_PATH}")
    print(f"📁 OUTPUT : {OUTPUT_DIR}")
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ========================================================================
    # normalized_paths2 구성 (step15 CRS 감지용)
    # ========================================================================
    normalized_paths2 = {}
    if NORMALIZED_PATHS:
        normalized_paths2['reference'] = NORMALIZED_PATHS
        ref_dir = os.path.dirname(NORMALIZED_PATHS)
        normalized_paths2['target'] = os.path.join(ref_dir,
                                                   'target_normalized.tif')

    # ========================================================================
    # JSON GCP 파일 경로
    # ========================================================================

    vis_dir_1=os.path.dirname(OUTPUT_DIR) #<WORK_ROOT>/Downloads/bb_l1a_20260208_190833_8band/Center/ 
    vis_dir=os.path.join(vis_dir_1, '05_SuperPoint_result', 'step14_visualizations') #<WORK_ROOT>/Downloads/bb_l1a_20260208_190833_8band/Center/05_SuperPoint_result/step14_visualizations/

    orig_gcp_json = os.path.join(vis_dir,
                                 'step14_final_gcps_original_target.json')

    if not os.path.exists(orig_gcp_json):
        raise FileNotFoundError(
            f"GCP JSON 파일이 없습니다: {orig_gcp_json}\n"
            f"먼저 geometric_correction.py (STEP 1-14)를 실행하세요.")

    # ========================================================================
    # JSON 읽기 → GCP 리스트 구성
    # ========================================================================
    original_training_gcps = []
    original_training_gcps_real_only = []

    try:
        with open(orig_gcp_json, 'r', encoding='utf-8') as f:
            conv = json.load(f)

        gcps = conv.get('gcps', [])
        real_count = sum(1 for g in gcps if g.get('is_real') is True)
        pseudo_count = sum(1 for g in gcps if g.get('is_real') is False)

        # GCP weight 결정 우선순위: CLI --weight > EXPERIMENT_SETS gcp_weight > Setting_Weight
        if gcp_weight is not None:
            GCP_WEIGHT = gcp_weight
        elif 'gcp_weight' in current_exp:
            GCP_WEIGHT = current_exp['gcp_weight']
        else:
            GCP_WEIGHT = Setting_Weight(real_count)

        print(f"\n📊 GCP 분류: Real {real_count}개, Pseudo {pseudo_count}개")
        print(f"   GCP_WEIGHT: {GCP_WEIGHT}  (Real GCP 복제 횟수)")

        for it in gcps:
            c0 = it.get('col_original', None)
            r0 = it.get('row_original', None)
            inside = it.get('inside_original', False)
            is_real = it.get('is_real', True)

            if c0 is None or r0 is None or not inside:
                continue

            g = GroundControlPoint(row=float(r0),
                                   col=float(c0),
                                   x=float(it['x']),
                                   y=float(it['y']),
                                   z=float(it['z']))

            if is_real:
                original_training_gcps_real_only.append(g)
                for _ in range(GCP_WEIGHT):
                    original_training_gcps.append(g)
            else:
                original_training_gcps.append(g)

        if len(original_training_gcps) < 10:
            print(f"   ⚠️ 학습 GCP 수 부족: {len(original_training_gcps)}개")

        print(
            f"   총 학습 GCP: {len(original_training_gcps)}개 "
            f"(Real {len(original_training_gcps_real_only)}개 × {GCP_WEIGHT} + "
            f"Pseudo {pseudo_count}개)")

    except Exception as e:
        print(f"   ❌ JSON 로드 실패: {e}")
        import traceback
        traceback.print_exc()
        raise

    # ========================================================================
    # STEP 15: RPC 모델 생성
    # ========================================================================
    print("\n" + "=" * 80)
    print("STEP 15: RPC 모델 생성")
    print("=" * 80)

    try:
        rpc_params, rpc_gdal_for_rpcm, rpc_obj = step15_rpcfit_generate(
            original_training_gcps, normalized_paths2, TARGET_PATH, OUTPUT_DIR)

        # ====================================================================
        # STEP 16: 정사보정
        # ====================================================================
        print("\n" + "=" * 80)
        print("STEP 16: 정사보정")
        print("=" * 80)

        step16_orthorectification(
            TARGET_PATH,
            OUTPUT_DIR,
            rpc_params,
            DEM_PATH,
            GEOID_PATH,
            rpc_gdal_for_rpcm=rpc_gdal_for_rpcm,
        )

        print("\n✅ STEP 15/16 완료: RPC 기반 정밀 기하보정이 성공적으로 완료되었습니다.")

        # ====================================================================
        # GCP Chip 추출 (Real GCP만 사용)
        # ====================================================================
        base_name = os.path.splitext(os.path.basename(TARGET_PATH))[0]
        final_results_dir = os.path.join(OUTPUT_DIR, '07_Final_results')

        # 최종 보정 영상 경로 탐색 (우선순위 순)
        final_image_path = os.path.join(final_results_dir, f'{base_name}.tiff')
        if not os.path.exists(final_image_path):
            final_image_path = os.path.join(final_results_dir,
                                            f'{base_name}_final_rpcm.tif')
        if not os.path.exists(final_image_path):
            step16_dir = os.path.join(OUTPUT_DIR, 'step16_final_corrected')
            final_image_path = os.path.join(
                step16_dir, f'{base_name}_final_rpc_corrected.tif')

        if os.path.exists(final_image_path):
            print(f"\n🔍 최종 보정 영상: {final_image_path}")
            print(
                f"   Real GCP {len(original_training_gcps_real_only)}개에서 chip 추출 시작..."
            )
            extract_gcp_chips_from_final_image(
                final_image_path=final_image_path,
                gcps=original_training_gcps_real_only,
                output_dir=OUTPUT_DIR,
                dem_path=DEM_PATH,
                geoid_path=GEOID_PATH,
                chip_size=513,
            )
        else:
            print(f"\n   ⚠️ 최종 보정 영상을 찾을 수 없어 chip 추출을 건너뜁니다.")
            print(f"   확인한 경로:")
            print(
                f"     - {os.path.join(final_results_dir, f'{base_name}.tiff')}"
            )
            print(
                f"     - {os.path.join(final_results_dir, f'{base_name}_final_rpcm.tif')}"
            )

    except Exception as e:
        print(f"\n⚠️ STEP 15/16 실행 실패: {e}")
        import traceback
        traceback.print_exc()
        raise

    print(f"\n종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ==============================================================================
if __name__ == "__main__":
    setup_korean_font()

    import argparse
    parser = argparse.ArgumentParser(
        description="RPC 생성 및 정사보정 파이프라인 (JSON GCP 기반)"
    )
    parser.add_argument(
        "--weight", type=int,
        help="GCP 가중치 (Real GCP 복제 횟수, 기본값: Setting_Weight 자동 계산)"
    )
    parser.add_argument(
        "--set", default="t1",
        help="EXPERIMENT_SETS 키 이름 (기본값: t1)"
    )
    args = parser.parse_args()

    main(gcp_weight=args.weight, current_set=args.set)
