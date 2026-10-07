"""
==============================================================================
2단계 정밀 기하보정 파이프라인 (Two-Stage Precision Geometric Correction Pipeline)
==============================================================================

이 스크립트는 위성영상 간 정밀 기하보정을 수행하는 통합 파이프라인입니다.

【파이프라인 개요】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
단계 1: 전처리 및 1차 기하보정 (STEP 1-10)
  - 좌표계 통일, 해상도 정규화, 영역 추출
  - AI 기반 빠른 매칭 (저해상도)
  - AFFINE 변환 기반 1차 기하보정
  
단계 2: 정밀 기하보정 (STEP 11-20)
  - 다단계 매칭 (LoFTR 기반)
  - RPC/RFM 모델 생성 (UTM->경위도 변환 및 Ridge 회귀 안정화 적용)
  - 최종 정밀 기하보정 수행 (gdalwarp -rpc -et 1.0 사용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[수정 이력]
- 2025-10-27: 
  - PROJ_LIB 환경 변수 자동 설정 코드 추가 (Conda 환경 충돌 해결)
  - RPCGenerator: UTM -> 경위도 좌표 변환 로직 추가 (핵심 버그 수정)
  - RPCGenerator: np.linalg.lstsq를 sklearn.linear_model.Ridge로 교체 (NaN 오류 해결)
  - step15: GCP 생성 시 UTM 좌표계 유지, ref_crs 반환
  - step16: ref_crs를 RPCGenerator로 전달
  - step19: gdalwarp -rpc에 -et 1.0 옵션 추가, 임시 파일 좌표계 제거
  - main: 2단계 함수 호출 로직 수정
"""

# Standard library imports
import os
import sys
import json
import math
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Optional, Any, Dict

# ==============================================================================
# PROJ_DATA 설정 — shell PROJ_LIB 제거 후 conda env 경로 강제 설정
# 원인: shell PROJ_LIB=/mnt/hdd/miniconda3/share/proj (base conda, VERSION.MINOR=2)가
#       env의 pyproj/GDAL(VERSION.MINOR>=6)와 버전 충돌.
# 수정: (1) pyproj import 전에 env var pop (import 중 caching 방지)
#       (2) sys.prefix/share/proj로 경로 직접 결정 (env var 의존 없음)
#       (3) osr.SetPROJSearchPaths()로 GDAL PROJ context에도 반영 (rasterio 포함)
# 반드시 geospatial 라이브러리(rasterio, gdal, torch 등) import 전에 실행해야 함.
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

# Third-party imports
import cv2
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torchvision.utils import save_image

# Geospatial libraries
import rasterio
import rasterio.warp
from rasterio.enums import Resampling
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps
from affine import Affine
from pyproj import CRS, Transformer
from osgeo import gdal, osr

# GDAL 경고 제거: 예외 처리 설정
try:
    gdal.UseExceptions()  # GDAL 4.0에서 기본값이 될 예정이므로 명시적으로 설정
except:
    pass  # GDAL이 설치되지 않았거나 설정이 불가능한 경우 무시

# GDAL PROJ context에 올바른 경로 전달 (rasterio는 GDAL 경유로 PROJ 사용)
try:
    _proj_data = os.environ.get('PROJ_DATA', '')
    if _proj_data and hasattr(osr, 'SetPROJSearchPaths'):
        osr.SetPROJSearchPaths([_proj_data])
except Exception:
    pass

# AI/ML libraries
from lightglue import LightGlue, SuperPoint
from lightglue.utils import rbd, load_image
from kornia.feature import LoFTR

# Visualization libraries
import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.patches as patches
matplotlib.use('Agg')  # GUI 없이 사용

# Excel handling
from openpyxl.styles import PatternFill

# 수치적 안정성을 위해 scikit-learn의 Ridge 회귀를 사용합니다.
try:
    from sklearn.linear_model import Ridge
except ImportError:
    print("="*80)
    print("❌ 'scikit-learn' 라이브러리가 필요합니다.")
    print("   pip install scikit-learn 또는 conda install scikit-learn을 실행하세요.")
    print("="*80)
    raise

# ------------------------------------------------------------------------------
# 모듈 경로 문제 해결: 현재 스크립트의 디렉토리를 sys.path에 추가
# (geometric_correction 패키지를 찾기 위함)
cwd = os.path.dirname(os.path.abspath(__file__))
if cwd not in sys.path:
    sys.path.append(cwd)
# ------------------------------------------------------------------------------

from geometric_correction.pipeline.preprocessing import run_step11_5_pipeline
from geometric_correction.pipeline.precision_correction import (
    step14_plus_project_gcps_to_original_target,
    Setting_Weight,
    fit_3d_polynomial_seed,
    generate_pseudo_grid_3d_from_seed,
    seed_to_rpc_init,
    stratified_split_gcps_4quad,
    fit_rpc_residual_translation,
    absorb_translation_into_rpc,
    step15_rpcfit_generate,
    step15_2_holdout_eval_and_bias,
    step15_3_residual_diagnostics,
    _make_seed_like_from_rpc,
    _compute_rpc_diff_rmse,
    save_recursive_convergence_plot,
    step16_orthorectification,
    step15_1_rpcfit_evaluate,
    step15_1_rpcfit_evaluate_with_cv,
    step16b_rpcm_correct,
    extract_gcp_chips_from_final_image,
    match_gcp_chips_with_target,
)

# ==============================================================================
# PROJ_LIB 환경 변수 설정 (PROJ 라이브러리 버전 충돌 해결)
# ==============================================================================
def find_proj_lib():
    """PROJ 라이브러리 경로 찾기 (여러 위치 확인)"""
    # 이미 설정되어 있으면 그대로 사용
    if 'PROJ_LIB' in os.environ and os.path.exists(os.path.join(os.environ['PROJ_LIB'], 'proj.db')):
        return os.environ['PROJ_LIB']

    # 확인할 경로 목록 (우선순위 순서)
    check_paths = []

    # 1. Conda 환경 확인
    conda_prefix = os.environ.get('CONDA_PREFIX')
    if conda_prefix:
        check_paths.append(os.path.join(conda_prefix, 'share', 'proj'))

    # 2. 현재 Python 환경
    check_paths.append(os.path.join(sys.prefix, 'share', 'proj'))

    # 3. Homebrew (macOS)
    check_paths.extend([
        '/opt/homebrew/share/proj',
        '/usr/local/share/proj',
    ])

    # 4. 시스템 경로
    check_paths.extend([
        '/usr/share/proj',
        '/opt/share/proj',
    ])

    # proj.db 파일 찾기
    for proj_path in check_paths:
        if proj_path and os.path.exists(proj_path):
            proj_db_path = os.path.join(proj_path, 'proj.db')
            if os.path.exists(proj_db_path):
                return proj_path

    return None

try:
    proj_path = find_proj_lib()

    if proj_path:
        # proj.db 파일이 존재하면 해당 경로를 PROJ_LIB로 설정
        os.environ['PROJ_LIB'] = proj_path
        # 경고 메시지 제거 (조용히 설정)
        # print(f"✅ PROJ_LIB set to: {proj_path}")
    else:
        # proj.db를 찾지 못한 경우 조용히 넘어감 (대부분의 경우 pyproj가 자동으로 찾음)
        # print("⚠️ PROJ_LIB not set automatically (pyproj will use default)")
        pass
except Exception as e:
    # 조용히 넘어감 (오류가 있어도 프로그램 실행에 영향 없음)
    pass
# ------------------------------------------------------------------------------

# Local imports
from geometric_correction.utils.io import load_image_gdal
from geometric_correction.models.rpc import RPCModel, RPCGenerator
from geometric_correction.utils.visualization import (
    setup_korean_font, apply_clahe_preprocessing, grid_based_filtering,
    visualize_gcp_grid_distribution, visualize_matches, visualize_ransac_comparison,
    visualize_before_after_correction, visualize_initial_correction_matches,
    visualize_patch_matching
)
from geometric_correction.pipeline.preprocessing import (
    validate_inputs, unify_crs, crop_to_target_extent,crop_to_target_extent2,
    normalize_resolution, prepare_lowres_images
)
from geometric_correction.pipeline.initial_matching import (
    ai_feature_matching, ransac_filtering, scale_to_fullres,
    create_gcps, initial_correction
)
from geometric_correction.pipeline.hierarchical_matching import (
    pyramid_matching_quarter, multistage_matching
)
from geometric_correction.pipeline.precision_correction import (
    create_final_gcps,
    generate_rpc,
    final_correction,
    accuracy_validation,
    apply_rpc_model_directly
)
from geometric_correction.PrcsnMatching.Matching_performance_v3 import PrcsnMatching
from geometric_correction.PrcsnMatching.Initial_matching_v3 import pyramid_matching_quarter_JW

# matplotlib 한글 폰트 설정
def setup_korean_font():
    """한글 폰트 설정 (경고 메시지 제거)"""
    import warnings
    import platform
    # matplotlib의 모든 UserWarning 무시 (한글 폰트 경고 포함)
    warnings.filterwarnings('ignore', category=UserWarning)

    # 시스템에서 사용 가능한 한글 폰트 찾기
    font_list = fm.findSystemFonts(fontpaths=None, fontext='ttf')
    korean_fonts = []

    # OS별 한글 폰트 우선순위
    system_name = platform.system()
    if system_name == 'Windows':
        font_names = ['Malgun Gothic', 'Gulim', 'Batang', 'Dotum', 'NanumGothic', 'NanumBarunGothic']
    elif system_name == 'Darwin':  # macOS
        font_names = ['AppleGothic', 'NanumGothic', 'NanumBarunGothic', 'Arial']
    else:  # Linux/Ubuntu
        font_names = ['NanumGothic', 'NanumBarunGothic', 'Noto Sans CJK KR', 'Noto Sans KR', 'DejaVu Sans']

    for font_path in font_list:
        for font_name in font_names:
            if font_name.lower() in font_path.lower() or font_name.lower().replace(' ', '') in font_path.lower():
                korean_fonts.append((font_name, font_path))
                break

    # 한글 폰트 설정
    font_set = False
    if korean_fonts:
        try:
            # 첫 번째로 찾은 한글 폰트 사용
            font_name, font_path = korean_fonts[0]
            font_prop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = font_prop.get_name()
            plt.rcParams['font.size'] = 10
            font_set = True
        except Exception as e:
            pass

    # 폰트를 찾지 못했거나 설정 실패 시
    if not font_set:
        try:
            # 시스템 기본 폰트로 설정 시도
            if system_name == 'Windows':
                plt.rcParams['font.family'] = 'Malgun Gothic'
            elif system_name == 'Darwin':
                plt.rcParams['font.family'] = 'AppleGothic'
            else:
                plt.rcParams['font.family'] = 'DejaVu Sans'
        except Exception:
            plt.rcParams['font.family'] = 'DejaVu Sans'

    # 마이너스 기호 깨짐 방지
    plt.rcParams['axes.unicode_minus'] = False

    # matplotlib 로깅 레벨 설정 (경고 숨김)
    import logging
    logging.getLogger('matplotlib').setLevel(logging.ERROR)


def step11_5_depth_anything_processing(OUTPUT_DIR, OUTPUT_DIR2, TARGET_PATH, INITIAL_CORRECTION_METHOD):
    """STEP 11-5: 초기 기하보정 영상에 대해 DepthAnything V2 Large로 깊이 추정"""
    try:
        print("\n" + "="*80)
        print("STEP 11-5: DepthAnything V2 Large로 깊이 추정")
        print("="*80)
        init_tif = os.path.join(OUTPUT_DIR, "03_Initial_correction",
                                f"target_initial_{INITIAL_CORRECTION_METHOD.upper()}_corrected.tif")
        init_tif_alt = os.path.join(OUTPUT_DIR, "03_Initial_correction",
                                    f"target_initial_{INITIAL_CORRECTION_METHOD.lower()}_corrected.tif")
        init_path = init_tif if os.path.exists(init_tif) else (init_tif_alt if os.path.exists(init_tif_alt) else None)
        if init_path is None:
            print("   ⚠️ 초기 기하보정 영상이 없어 STEP 11-5 건너뜀")
        else:
            from geometric_correction.pipeline.preprocessing import (
                step11_5_estimate_depth_anything,
                step11_6_crop_dem_with_initial_mask,
                step11_7_scale_depth_by_dem,
            )
            # 11-5-1: 초기 기하보정 영상에 대해 추정
            _ = step11_5_estimate_depth_anything(init_path, OUTPUT_DIR2)
            # 11-5-2: 원본 TARGET 영상에 대해서도 추정
            if os.path.exists(TARGET_PATH):
                print("   🔁 원본 TARGET 영상에도 DepthAnything 적용")
                _ = step11_5_estimate_depth_anything(TARGET_PATH, os.path.join(OUTPUT_DIR2, "raw_target"))
            # STEP 11-6: 마스크로 DEM crop
            print("\n" + "="*80)
            print("STEP 11-6: 마스크로 DEM crop")
            print("="*80)
            dem_cropped_path2 = os.path.join(OUTPUT_DIR2, "step03_cropped", "dem_cropped.tif")
            init_mask_png = init_path.replace('.tif', '_mask.png')
            dem_masked_path = None
            if os.path.exists(dem_cropped_path2) and os.path.exists(init_mask_png):
                dem_masked_path = step11_6_crop_dem_with_initial_mask(init_path, init_mask_png, dem_cropped_path2, OUTPUT_DIR2)
            else:
                print("   ⚠️ DEM 또는 마스크가 없어 STEP 11-6 건너뜀")

            # STEP 11-7: DEM min/max로 11-5 depth 스케일링
            print("\n" + "="*80)
            print("STEP 11-7: DEM min/max 기반 Depth 스케일링")
            print("="*80)
            depth11_5_tif = os.path.join(OUTPUT_DIR2, "step11_5_depth", "target_depth_map.tif")
            if dem_masked_path and os.path.exists(depth11_5_tif):
                _ = step11_7_scale_depth_by_dem(depth11_5_tif, dem_masked_path)
            else:
                print("   ⚠️ 11-5 결과 또는 dem_masked 없음, STEP 11-7 건너뜀")
    except Exception as e:
        print(f"   ⚠️ STEP 11-5 실패: {e}")


def step14_plus_project_gcps_to_original_target(OUTPUT_DIR, TARGET_PATH, training_gcps, normalized_paths2, check_points=None, real_gcps=None, target_bands=None):
    """STEP 14+: 최종 GCP를 원본 TARGET 픽셀 좌표계로 역투영 및 시각화 저장
    - training_gcps와 check_points를 모두 동일 스타일로 시각화
    - 각 시각화에서 GRID별 점 개수 표기
    - real_gcps: 실제 GCP 리스트 (Pseudo GCP와 구분하기 위해, 선택적)
    - target_bands: Target 이미지의 RGB 밴드 인덱스 (예: [6,4,2] for PlanetScope)
    """
    try:
        print("\n" + "="*80)
        print("STEP 14+: 최종 GCP 원본 TARGET 좌표계로 역투영 및 시각화")
        print("="*80)

        # 1) 원본 TARGET(STEP 1 입력) 지오정보 로드
        original_target_path = TARGET_PATH  # STEP 1에서 사용된 입력 경로
        with rasterio.open(original_target_path) as src_orig:
            orig_transform = src_orig.transform
            orig_crs = src_orig.crs
            orig_width, orig_height = src_orig.width, src_orig.height
            has_geo = (orig_transform != rasterio.Affine.identity()) and (orig_crs is not None)

        # 2) 최종 GCP의 지리좌표(x,y,z) → 원본 TARGET 픽셀(c0,r0) 계산
        gcps_converted = []
        gcps_out_of_bounds = []  # 범위 밖 GCP도 저장 (시각화용)
        # Fallback: 원본에 좌표가 없으면 STEP09 초기 GCP의 (geo→pixel_original) 회귀모델을 적합해 사용
        geo_to_pix_reg = None
        if not has_geo:
            try:
                init_gcp_json = os.path.join(OUTPUT_DIR, '02_Initial_matching', 'initial_gcps.json')
                with open(init_gcp_json, 'r', encoding='utf-8') as f:
                    init_g = json.load(f)
                pairs = []
                for it in init_g.get('gcps', []):
                    gx = float(it['geo_coords']['x'])
                    gy = float(it['geo_coords']['y'])
                    pc = float(it['target_pixel']['col'])
                    pr = float(it['target_pixel']['row'])
                    pairs.append((gx, gy, pc, pr))
                if len(pairs) >= 10:
                    X = np.array([[p[0], p[1]] for p in pairs], dtype=np.float64)
                    y_col = np.array([p[2] for p in pairs], dtype=np.float64)
                    y_row = np.array([p[3] for p in pairs], dtype=np.float64)
                    from sklearn.preprocessing import PolynomialFeatures
                    from sklearn.linear_model import Ridge
                    from sklearn.pipeline import make_pipeline
                    poly_degree = 3
                    model_col = make_pipeline(PolynomialFeatures(poly_degree, include_bias=True), Ridge(alpha=1e-3))
                    model_row = make_pipeline(PolynomialFeatures(poly_degree, include_bias=True), Ridge(alpha=1e-3))
                    model_col.fit(X, y_col)
                    model_row.fit(X, y_row)
                    geo_to_pix_reg = (model_col, model_row)
                    print(f"   ✅ Fallback 회귀모델 적합(geo→pixel original): N={len(pairs)}, degree={poly_degree}")
                else:
                    print("   ⚠️ 초기 GCP 부족으로 Fallback 회귀모델 생략")
            except Exception as re:
                print(f"   ⚠️ Fallback 회귀모델 준비 실패: {re}")

        # 실제 GCP와 Pseudo GCP 구분 (real_gcps로 비교)
        real_gcp_set = set()
        if real_gcps is not None:
            for rg in real_gcps:
                try:
                    # 좌표 기반으로 비교 (소수점 6자리까지)
                    key = (round(float(rg.x), 6), round(float(rg.y), 6),
                           round(float(rg.row), 2), round(float(rg.col), 2))
                    real_gcp_set.add(key)
                except (TypeError, ValueError):
                    pass

        print(f"   📊 입력 Training GCPs: {len(training_gcps)}개")
        # 시각화 대상: Training + CheckPoints (동일 스타일)
        all_gcps_for_vis = list(training_gcps) + (list(check_points) if check_points else [])

        removed_oob = 0
        kept = 0
        for g in all_gcps_for_vis:
            # 실제 GCP인지 Pseudo GCP인지 확인
            is_real_gcp = False
            try:
                gcp_key = (round(float(g.x), 6), round(float(g.y), 6),
                          round(float(g.row), 2), round(float(g.col), 2))
                if real_gcp_set and gcp_key in real_gcp_set:
                    is_real_gcp = True
            except (TypeError, ValueError):
                # 좌표 변환 실패 시 기본값 (real_gcps가 없으면 모두 real로 간주)
                is_real_gcp = (real_gcps is None or len(real_gcp_set) == 0)

            # JSON에는 raw(corner-based) 픽셀 좌표를 그대로 저장한다.
            # matplotlib imshow용 -0.5 시프트는 시각화 시점에만 적용한다.
            item = {
                'row_corrected': float(g.row),
                'col_corrected': float(g.col),
                'x': float(g.x),
                'y': float(g.y),
                'z': float(g.z),
                'is_real': is_real_gcp
            }
            if has_geo:
                # 역변환: (x,y) → (col,row)
                inv = ~orig_transform
                c0, r0 = inv * (g.x, g.y)
                item['col_original'] = float(c0)
                item['row_original'] = float(r0)
                # 화면 내 여부 플래그
                item['inside_original'] = bool(0 <= r0 < orig_height and 0 <= c0 < orig_width)
            else:
                # 좌표정보 없음: 회귀모델로 예측
                if geo_to_pix_reg is not None:
                    mc, mr = geo_to_pix_reg
                    pred_c = float(mc.predict(np.array([[g.x, g.y]], dtype=np.float64))[0])
                    pred_r = float(mr.predict(np.array([[g.x, g.y]], dtype=np.float64))[0])
                    item['col_original'] = pred_c
                    item['row_original'] = pred_r
                    item['inside_original'] = bool(0 <= pred_r < orig_height and 0 <= pred_c < orig_width)
                else:
                    item['col_original'] = None
                    item['row_original'] = None
                    item['inside_original'] = False

            if item['col_original'] is None or item['row_original'] is None or (not item['inside_original']):
                removed_oob += 1
                gcps_out_of_bounds.append(item)  # 범위 밖도 저장
                continue
            kept += 1
            gcps_converted.append(item)

        # 3) JSON 저장
        vis_dir = os.path.join(OUTPUT_DIR, '05_SuperPoint_result', 'step14_visualizations')
        os.makedirs(vis_dir, exist_ok=True)
        out_json = os.path.join(vis_dir, 'step14_final_gcps_original_target.json')
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump({
                'original_target': original_target_path,
                'normalized_target_for_step11': normalized_paths2['target'],
                'count': len(gcps_converted),
                'count_out_of_bounds': len(gcps_out_of_bounds),
                'gcps': gcps_converted,
                'gcps_out_of_bounds': gcps_out_of_bounds
            }, f, indent=2, ensure_ascii=False)
        print(f"   💾 원본 TARGET 좌표계 GCP 저장: {out_json}")
        print(f"   ✅ 원본 범위 내 GCP: {kept}개 (전체: {len(all_gcps_for_vis)}개)")
        if removed_oob > 0:
            print(f"   ⚠️ 원본 범위 밖 GCP: {removed_oob}개")

        # 4) 시각화: 원본 TARGET / 초기보정 TARGET / REFERENCE 각각에 포인트 표시
        vis_dir = os.path.join(OUTPUT_DIR, '05_SuperPoint_result', 'step14_visualizations')
        os.makedirs(vis_dir, exist_ok=True)

        def _read_rgb(path, reverse_bands=False):
            with rasterio.open(path) as src:
                n_bands = src.count
                arr = src.read()
            if n_bands == 1:
                ch = arr[0].astype(np.float32)
                lo, hi = np.percentile(ch, 2), np.percentile(ch, 98)
                ch = np.clip((ch - lo) / (hi - lo + 1e-6) * 255, 0, 255).astype(np.uint8)
                return np.stack([ch, ch, ch], axis=-1)
            # Natural color: 8-band → 4,3,2 | 4-band → 3,2,1 | else → 1,2,3
            if n_bands >= 8:
                band_idx = [3, 2, 1]  # 0-based indices for bands 4,3,2
            elif n_bands >= 4:
                band_idx = [2, 1, 0]  # 0-based indices for bands 3,2,1
            else:
                band_idx = list(range(min(n_bands, 3)))
            channels = []
            for bi in band_idx:
                ch = arr[bi].astype(np.float32)
                lo, hi = np.percentile(ch, 2), np.percentile(ch, 98)
                ch = np.clip((ch - lo) / (hi - lo + 1e-6) * 255, 0, 255).astype(np.uint8)
                channels.append(ch)
            return np.stack(channels, axis=-1)

        # Grid 그리기 및 셀 카운트 유틸
        def _draw_grid_and_counts(ax, img_w, img_h, pts_xy, grid_size=10, color='yellow'):
            try:
                cell_w = img_w / grid_size
                cell_h = img_h / grid_size
                # 카운트 초기화
                counts = np.zeros((grid_size, grid_size), dtype=int)
                for (cx, cy) in pts_xy:
                    gx = int(min(grid_size - 1, max(0, cx // cell_w)))
                    gy = int(min(grid_size - 1, max(0, cy // cell_h)))
                    counts[gy, gx] += 1
                # 그리드 라인 및 수치
                for i in range(1, grid_size):
                    ax.axvline(i * cell_w, color=color, linewidth=0.5, alpha=0.6)
                    ax.axhline(i * cell_h, color=color, linewidth=0.5, alpha=0.6)
                # 각 셀 중앙에 개수 표기
                for gy in range(grid_size):
                    for gx in range(grid_size):
                        cx = (gx + 0.5) * cell_w
                        cy = (gy + 0.5) * cell_h
                        txt = str(int(counts[gy, gx]))
                        # 가독성을 위해 테두리 효과
                        ax.text(cx, cy, txt, color='white', fontsize=8, ha='center', va='center',
                                bbox=dict(boxstyle='round,pad=0.15', facecolor='black', alpha=0.35, edgecolor='none'))
            except Exception:
                pass

        def _filter_points_on_image(img: np.ndarray, coords: list[tuple[float, float]]):
            h, w = img.shape[0], img.shape[1]
            filtered = []
            for cx, cy in coords:
                if cx is None or cy is None:
                    continue
                xi = int(round(cx))
                yi = int(round(cy))
                if not (0 <= xi < w and 0 <= yi < h):
                    continue
                pix = img[yi, xi]
                if pix.ndim >= 1:
                    nonzero = np.any(pix > 0)
                else:
                    nonzero = pix > 0
                if nonzero:
                    filtered.append((cx, cy))
            return filtered

        # 원본 TARGET 시각화 (지오정보 또는 회귀 예측이 있는 경우)
        if has_geo or geo_to_pix_reg is not None:
            try:
                # 한글 폰트 설정
                setup_korean_font()
                img_orig = _read_rgb(original_target_path)
                fig, ax = plt.subplots(figsize=(8, 8))
                ax.imshow(img_orig)
                coords_real = []
                coords_pseudo = []
                # matplotlib imshow는 픽셀 중심이 (0,0), rasterio는 corner-based이므로
                # 시각화 시점에만 -0.5 시프트를 적용한다. (JSON에는 raw 값이 저장됨)
                for it in gcps_converted:
                    if it['col_original'] is not None and it['row_original'] is not None and it['inside_original']:
                        vis_c = it['col_original'] - 0.5
                        vis_r = it['row_original'] - 0.5
                        if it.get('is_real', True):
                            coords_real.append((vis_c, vis_r))
                        else:
                            coords_pseudo.append((vis_c, vis_r))
                # _filter_points_on_image 필터 제거: inside_original 체크로 이미 범위 내 점만 포함됨

                # GRID 그리기 (10x10)
                grid_size_vis = 10
                cell_w = img_orig.shape[1] / grid_size_vis
                cell_h = img_orig.shape[0] / grid_size_vis
                for i in range(1, grid_size_vis):
                    ax.axvline(i * cell_w, color='yellow', linewidth=0.5, alpha=0.6)
                    ax.axhline(i * cell_h, color='yellow', linewidth=0.5, alpha=0.6)

                # Real GCP: 빨간색 원
                if coords_real:
                    xs_real, ys_real = zip(*coords_real)
                    ax.scatter(xs_real, ys_real, s=10, c='r', marker='o', linewidths=0.0, label=f'Real GCPs ({len(coords_real)})')
                # Pseudo GCP: 노란색 삼각형
                if coords_pseudo:
                    xs_pseudo, ys_pseudo = zip(*coords_pseudo)
                    ax.scatter(xs_pseudo, ys_pseudo, s=10, c='yellow', marker='^', linewidths=0.0, label=f'Pseudo GCPs ({len(coords_pseudo)})')
                ax.legend(loc='best')
                ax.set_title('Original TARGET with GCPs (Training + CheckPoints)')
                out_png = os.path.join(vis_dir, 'gcp_on_original_target.png')
                plt.savefig(out_png, dpi=200, bbox_inches='tight')
                plt.close(fig)
                print(f"   🖼️ 시각화 저장: {out_png} (표시: Real {len(coords_real)}개, Pseudo {len(coords_pseudo)}개)")
            except Exception as ve:
                print(f"   ⚠️ 원본 TARGET 시각화 실패: {ve}")

        # 초기 기하보정(또는 STEP11 타깃) 위에 보정 c,r 표시
        try:
            # 한글 폰트 설정
            setup_korean_font()
            corrected_target_path = normalized_paths2['target']
            img_corr = _read_rgb(corrected_target_path)
            fig, ax = plt.subplots(figsize=(8, 8))
            ax.imshow(img_corr)
            coords_real = []
            coords_pseudo = []
            # matplotlib imshow는 픽셀 중심이 (0,0), rasterio는 corner-based이므로
            # 시각화 시점에만 -0.5 시프트를 적용한다. (JSON에는 raw 값이 저장됨)
            for it in gcps_converted:
                vis_c = it['col_corrected'] - 0.5
                vis_r = it['row_corrected'] - 0.5
                if it.get('is_real', True):
                    coords_real.append((vis_c, vis_r))
                else:
                    coords_pseudo.append((vis_c, vis_r))
            for it in gcps_out_of_bounds:
                vis_c = it['col_corrected'] - 0.5
                vis_r = it['row_corrected'] - 0.5
                if it.get('is_real', True):
                    coords_real.append((vis_c, vis_r))
                else:
                    coords_pseudo.append((vis_c, vis_r))
            coords_real = _filter_points_on_image(img_corr, coords_real)
            coords_pseudo = _filter_points_on_image(img_corr, coords_pseudo)

            # GRID 그리기 (10x10)
            grid_size_vis = 10
            cell_w = img_corr.shape[1] / grid_size_vis
            cell_h = img_corr.shape[0] / grid_size_vis
            for i in range(1, grid_size_vis):
                ax.axvline(i * cell_w, color='yellow', linewidth=0.5, alpha=0.6)
                ax.axhline(i * cell_h, color='yellow', linewidth=0.5, alpha=0.6)

            # Real GCP: 빨간색 원
            if coords_real:
                xs_real, ys_real = zip(*coords_real)
                ax.scatter(xs_real, ys_real, s=10, c='r', marker='o', linewidths=0.0, label=f'Real GCPs ({len(coords_real)})')
            # Pseudo GCP: 노란색 삼각형
            if coords_pseudo:
                xs_pseudo, ys_pseudo = zip(*coords_pseudo)
                ax.scatter(xs_pseudo, ys_pseudo, s=10, c='yellow', marker='^', linewidths=0.0, label=f'Pseudo GCPs ({len(coords_pseudo)})')
            ax.legend(loc='best')
            ax.set_title('Corrected TARGET (STEP11 target) with GCPs (Training + CheckPoints)')
            out_png = os.path.join(vis_dir, 'gcp_on_corrected_target.png')
            plt.savefig(out_png, dpi=200, bbox_inches='tight')
            plt.close(fig)
            print(f"   🖼️ 시각화 저장: {out_png} (표시: Real {len(coords_real)}개, Pseudo {len(coords_pseudo)}개)")
        except Exception as ve:
            print(f"   ⚠️ 보정 TARGET 시각화 실패: {ve}")

        # REFERENCE 위에 ref 픽셀로 투영 표시 (지리→ref transform)
        try:
            # 한글 폰트 설정
            setup_korean_font()
            ref_path = normalized_paths2['reference']
            with rasterio.open(ref_path) as src_ref:
                ref_transform = src_ref.transform
                ref_width, ref_height = src_ref.width, src_ref.height
            img_ref = _read_rgb(ref_path, reverse_bands=True)  # Reference: BGR 순서 (3,2,1)
            fig, ax = plt.subplots(figsize=(8, 8))
            ax.imshow(img_ref)
            xs_real, ys_real = [], []
            xs_pseudo, ys_pseudo = [], []
            inv_ref = ~ref_transform
            # gcps_converted와 gcps_out_of_bounds 모두 포함 (REFERENCE는 원본 TARGET과 다른 영역일 수 있음)
            all_gcps_for_ref = list(gcps_converted) + list(gcps_out_of_bounds)
            for it in all_gcps_for_ref:
                c_ref, r_ref = inv_ref * (it['x'], it['y'])
                # 시각화 보정 (-0.5)
                c_ref -= 0.5
                r_ref -= 0.5
                if 0 <= r_ref < ref_height and 0 <= c_ref < ref_width:
                    if it.get('is_real', True):
                        xs_real.append(c_ref)
                        ys_real.append(r_ref)
                    else:
                        xs_pseudo.append(c_ref)
                        ys_pseudo.append(r_ref)

            # GRID 그리기 (10x10)
            grid_size_vis = 10
            cell_w = img_ref.shape[1] / grid_size_vis
            cell_h = img_ref.shape[0] / grid_size_vis
            for i in range(1, grid_size_vis):
                ax.axvline(i * cell_w, color='yellow', linewidth=0.5, alpha=0.6)
                ax.axhline(i * cell_h, color='yellow', linewidth=0.5, alpha=0.6)

            # Real GCP: 빨간색 원
            if xs_real:
                ax.scatter(xs_real, ys_real, s=10, c='r', marker='o', linewidths=0.0, label=f'Real GCPs ({len(xs_real)})')
            # Pseudo GCP: 노란색 삼각형
            if xs_pseudo:
                ax.scatter(xs_pseudo, ys_pseudo, s=10, c='yellow', marker='^', linewidths=0.0, label=f'Pseudo GCPs ({len(xs_pseudo)})')
            ax.legend(loc='best')
            ax.set_title('REFERENCE with GCPs (from geo, Training + CheckPoints)')
            out_png = os.path.join(vis_dir, 'gcp_on_reference.png')
            plt.savefig(out_png, dpi=200, bbox_inches='tight')
            plt.close(fig)
            print(f"   🖼️ 시각화 저장: {out_png} (표시: Real {len(xs_real)}개, Pseudo {len(xs_pseudo)}개)")
        except Exception as ve:
            print(f"   ⚠️ REFERENCE 시각화 실패: {ve}")

        # 5) 패치 저장: 각 GCP에 대해 reference/원본 target에서 49x49 패치 추출(+표시)
        try:
            patch_dir = os.path.join(vis_dir, 'step14_patches')
            ref_patch_dir = os.path.join(patch_dir, 'reference')
            ori_patch_dir = os.path.join(patch_dir, 'original_target')
            os.makedirs(ref_patch_dir, exist_ok=True)
            os.makedirs(ori_patch_dir, exist_ok=True)

            # 이미지 로드 (uint8 RGB)
            img_ref = _read_rgb(ref_path, reverse_bands=True)  # Reference: BGR 순서 (3,2,1)
            img_ori = _read_rgb(original_target_path)
            h_ref, w_ref = img_ref.shape[0], img_ref.shape[1]
            h_ori, w_ori = img_ori.shape[0], img_ori.shape[1]

            def _enhance_contrast_rgb(img_rgb: np.ndarray) -> np.ndarray:
                # LAB 공간에서 L 채널 CLAHE 적용 (지역 대비 향상)
                try:
                    lab = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2LAB)
                    l, a, b = cv2.split(lab)
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    l2 = clahe.apply(l)
                    lab2 = cv2.merge((l2, a, b))
                    rgb2 = cv2.cvtColor(lab2, cv2.COLOR_LAB2RGB)
                    return rgb2
                except Exception:
                    return img_rgb

            def save_patch(img, cx, cy, half=24, out_path='patch.png'):
                x0 = int(round(cx)) - half
                y0 = int(round(cy)) - half
                x1 = x0 + 2*half + 1
                y1 = y0 + 2*half + 1
                # 경계 체크
                x0_cl = max(0, x0); y0_cl = max(0, y0)
                x1_cl = min(img.shape[1], x1); y1_cl = min(img.shape[0], y1)
                patch = np.zeros((2*half+1, 2*half+1, 3), dtype=np.uint8)
                sx = x0_cl - x0; sy = y0_cl - y0
                ex = sx + (x1_cl - x0_cl); ey = sy + (y1_cl - y0_cl)
                if x0_cl < x1_cl and y0_cl < y1_cl:
                    patch[sy:ey, sx:ex] = img[y0_cl:y1_cl, x0_cl:x1_cl]
                # 대비 향상
                patch = _enhance_contrast_rgb(patch)
                # 가운데 십자 표시
                c = half
                cv2.drawMarker(patch, (c, c), (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=15, thickness=1)
                cv2.imwrite(out_path, patch)

            # ref 패치용 픽셀 좌표 (지리→ref)
            inv_ref = ~ref_transform
            for idx, it in enumerate(gcps_converted):
                # reference
                try:
                    cx_ref, cy_ref = inv_ref * (it['x'], it['y'])
                    if 0 <= cy_ref < h_ref and 0 <= cx_ref < w_ref:
                        save_patch(img_ref, cx_ref, cy_ref, half=24, out_path=os.path.join(ref_patch_dir, f"ref_patch_{idx:04d}.png"))
                except Exception:
                    pass
                # original target (지오 또는 회귀 예측)
                try:
                    cx_ori = it.get('col_original', None)
                    cy_ori = it.get('row_original', None)
                    if cx_ori is not None and cy_ori is not None and 0 <= cy_ori < h_ori and 0 <= cx_ori < w_ori:
                        save_patch(img_ori, cx_ori, cy_ori, half=24, out_path=os.path.join(ori_patch_dir, f"ori_patch_{idx:04d}.png"))
                except Exception:
                    pass

            print(f"   💾 패치 저장: {patch_dir}")
        except Exception as pe:
            print(f"   ⚠️ 패치 저장 실패: {pe}")

    except Exception as e:
        print(f"   ⚠️ STEP 14+ 처리 실패: {e}")


def main(
    dem_path: str = None,
    geoid_path: str = None,
    reference_path: str = None,
    target_path: str = None,
    output_dir: str = None,
    target_center_lat: float = None,
    target_center_lon: float = None,
    target_resolution: float = None,
    gcp_chips_dir: str = None,
    gcp_chip_resolution: float = None,
    target_bands: list = None,  # PlanetScope의 경우 [6, 4, 2] (R, G, B)
    output_name_base: str = None  # 출력 파일 기본 이름 (확장자 제외)
):
    """
    전체 2단계 기하보정 파이프라인을 실행합니다.
    
    Parameters:
    -----------
    dem_path : str
        DEM 파일 경로
    reference_path : str
        Reference 이미지 경로
    target_path : str
        Target 이미지 경로
    output_dir : str
        출력 디렉토리 경로
    target_center_lat : float
        Target 중심 위도
    target_center_lon : float
        Target 중심 경도
    target_resolution : float
        Target 해상도 (meter)
    """
    # ========================================================================
    # 실험 셋 설정 (기존 호환성을 위해 유지)
    # ========================================================================
    EXPERIMENT_SETS = {
                "t1": {
            "name": "1",
            "dem":          '/mnt/hdd/BB/bb_l1a_20260530_071042_8band/Bottom/01_Download_open_data/Copernicus_DEM_bottom.tif',
            "geoid":        '/mnt/hdd/BB/bb_l1a_20260530_071042_8band/Bottom/01_Download_open_data/Geoid_bottom.tif',
            "reference":    '/mnt/hdd/BB/bb_l1a_20260530_071042_8band/Bottom/01_Download_open_data/S2_mosaic_2026-05-31.tif',
            "output":       '/mnt/hdd/BB/bb_l1a_20260530_071042_8band/Bottom/output',
            "target":       '/mnt/hdd/BB/bb_l1a_20260530_071042_8band/Bottom/00_Divided_image/merged_bottom.tif',
            "target_center_lat":  22.34831895, 
            "target_center_lon":  59.81940891,
            "target_resolution": 4.8,
            "target_bands": [4,3,2],
            "gcp_chips_dir":    '',
            "gcp_chip_resolution": 4.8,  # GCP chip 해상도 (m/px)
        },
    }

    CURRENT_SET = "t1"  # ← 실험 셋 이름을 여기서 변경
    # ========================================================================
    # 경로 로드 (파라미터가 제공된 경우 사용, 아니면 EXPERIMENT_SETS 사용)
    # ========================================================================
    global TARGET_CENTER_LAT, TARGET_CENTER_LON, TARGET_RESOLUTION

    # GCP chips 디렉토리 초기화 (두 경로 모두에서 사용 가능하도록)
    GCP_CHIPS_DIR = None
    GCP_CHIP_RESOLUTION = None  # GCP chip 해상도 (기본값: None, 사용자가 입력하지 않으면 1.2m 사용)

    # Target 밴드 설정 (PlanetScope의 경우 [6, 4, 2], 기본값: None = [1, 2, 3])
    TARGET_BANDS = target_bands  # PlanetScope: [6, 4, 2] (R, G, B)

    if all([
            dem_path, reference_path, target_path, output_dir,
            target_center_lat is not None, target_center_lon is not None,
            target_resolution is not None
    ]):
        # 파라미터로 직접 제공된 경우
        DEM_PATH = dem_path
        GEOID_PATH = geoid_path
        REFERENCE_PATH = reference_path
        TARGET_PATH = target_path
        OUTPUT_DIR = output_dir
        TARGET_CENTER_LAT = float(target_center_lat)
        TARGET_CENTER_LON = float(target_center_lon)
        TARGET_RESOLUTION = float(target_resolution)
        # 파라미터로 제공된 경우 gcp_chips_dir도 설정
        if gcp_chips_dir:
            GCP_CHIPS_DIR = gcp_chips_dir
            # GCP chip 해상도 (기본값: 1.2m)
            GCP_CHIP_RESOLUTION = float(
                gcp_chip_resolution
            ) if gcp_chip_resolution is not None else 1.2
        current_exp = {"name": "사용자 설정"}
    else:
        # 기존 방식: EXPERIMENT_SETS 사용
        if CURRENT_SET not in EXPERIMENT_SETS:
            raise ValueError(
                f"실험 셋 '{CURRENT_SET}'을 찾을 수 없습니다. 사용 가능한 셋: {list(EXPERIMENT_SETS.keys())}"
            )

        current_exp = EXPERIMENT_SETS[CURRENT_SET]
        DEM_PATH = current_exp["dem"]
        GEOID_PATH = current_exp.get("geoid", None)
        REFERENCE_PATH = current_exp["reference"]
        TARGET_PATH = current_exp["target"]
        OUTPUT_DIR = current_exp["output"]
        # Target 밴드 설정 (EXPERIMENT_SETS의 target_bands 적용; 없으면 None=band1)
        TARGET_BANDS = current_exp.get("target_bands", None)

        # TARGET 중심 좌표 및 해상도 설정 (글로벌 변수 업데이트)
        TARGET_CENTER_LAT = current_exp["target_center_lat"]
        TARGET_CENTER_LON = current_exp["target_center_lon"]
        TARGET_RESOLUTION = current_exp["target_resolution"]

        # GCP chips 디렉토리 (선택적)
        GCP_CHIPS_DIR = current_exp.get("gcp_chips_dir", None)
        if GCP_CHIPS_DIR is not None:
            GCP_CHIP_RESOLUTION = float(current_exp.get("gcp_chip_resolution", 1.2))

    # preprocessing 모듈에 TARGET 정보 전달
    from geometric_correction.pipeline.preprocessing import set_target_info
    set_target_info(TARGET_CENTER_LAT, TARGET_CENTER_LON, TARGET_RESOLUTION)

    # 파이프라인 설정 변수들 (config_example.py에서 가져옴)
    from config_example import BUFFER_FACTOR, INITIAL_MATCHING_RESOLUTION, INITIAL_CORRECTION_METHOD, LOWRES_SCALE, MATCHING_THRESHOLD

    print("\n" + "=" * 80)
    print("2단계 정밀 기하보정 파이프라인 시작")
    print("=" * 80)
    print(f"📌 실험 셋: {current_exp['name']} ({CURRENT_SET})")
    print(f"📍 TARGET 중심: ({TARGET_CENTER_LAT}, {TARGET_CENTER_LON})")
    print(f"📏 TARGET 해상도: {TARGET_RESOLUTION}m")
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 출력 디렉토리 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 로그 파일 설정 (출력 디렉토리에 저장)
    log_filename = f"pipeline_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    log_filepath = os.path.join(OUTPUT_DIR, log_filename)

    # 로그를 파일과 콘솔에 동시에 출력하는 클래스
    class TeeOutput:
        """출력을 여러 스트림에 동시에 쓰는 클래스"""

        def __init__(self, *files):
            self.files = files

        def write(self, obj):
            for f in self.files:
                f.write(obj)
                f.flush()

        def flush(self):
            for f in self.files:
                f.flush()

    # 로그 파일 열기
    log_file = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    try:
        log_file = open(log_filepath, 'w', encoding='utf-8')
        # stdout과 stderr를 로그 파일과 콘솔에 동시에 출력
        sys.stdout = TeeOutput(sys.stdout, log_file)
        sys.stderr = TeeOutput(sys.stderr, log_file)

        print(f"\n💾 로그 파일 저장 위치: {log_filepath}\n")
    except Exception as log_err:
        # 로그 파일 생성 실패 시 경고만 출력하고 계속 진행
        print(f"⚠️ 로그 파일 생성 실패: {log_err}")
        log_file = None

    # base_name 설정 (출력 파일명용)
    if output_name_base:
        base_name = output_name_base
    else:
        base_name = os.path.splitext(os.path.basename(TARGET_PATH))[0]

    try:
        # ====================================================================
        # 【1단계】 전처리 및 1차 기하보정 (STEP 1-10)
        # ====================================================================
        print("\n" + "=" * 80)
        print("【1단계 시작】 원본 이미지 기반 전처리 및 1차 기하보정")
        print("=" * 80)

        # STEP 1: 입력 파일 검증
        metadata = validate_inputs(REFERENCE_PATH, TARGET_PATH, DEM_PATH,
                                   GEOID_PATH, OUTPUT_DIR)

        # STEP 2-5: 전처리 결과를 01_preprocessing 폴더에 저장
        preprocessing_dir = os.path.join(OUTPUT_DIR, '01_preprocessing')
        os.makedirs(preprocessing_dir, exist_ok=True)

        # STEP 2: 좌표계 통일
        unified_paths = unify_crs(metadata, preprocessing_dir,
                                  'step02_unified_crs', CURRENT_SET)
        # STEP 3: TARGET 영역 기준 잘라내기
        cropped_paths = crop_to_target_extent(unified_paths, metadata,
                                              preprocessing_dir, BUFFER_FACTOR,
                                              'step03_cropped')
        # STEP 4: 해상도 정규화
        normalized_paths = normalize_resolution(cropped_paths, metadata,
                                                preprocessing_dir,
                                                'step04_normalized',
                                                CURRENT_SET)
        # STEP 5: 저해상도 영상 생성
        lowres_paths = prepare_lowres_images(normalized_paths,
                                             preprocessing_dir,
                                             INITIAL_MATCHING_RESOLUTION,
                                             'step05_lowres')
        # STEP 6: AI 특징점 매칭
        mkpts0, mkpts1 = ai_feature_matching(lowres_paths,
                                             OUTPUT_DIR,
                                             target_bands=TARGET_BANDS)
        # STEP 7: RANSAC 필터링
        mkpts0_filtered, mkpts1_filtered, inlier_mask = ransac_filtering(
            mkpts0, mkpts1, lowres_paths, OUTPUT_DIR)
        # STEP 8: 원본 해상도로 스케일링
        mkpts0_fullres, mkpts1_fullres = scale_to_fullres(
            mkpts0_filtered, mkpts1_filtered, lowres_paths, normalized_paths,
            OUTPUT_DIR)
        # STEP 9: GCP 생성
        initial_gcps = create_gcps(mkpts0_fullres, mkpts1_fullres,
                                   normalized_paths, OUTPUT_DIR)
        # STEP 10: 1차 기하보정
        tar_corrected_path = initial_correction(
            initial_gcps,
            normalized_paths,
            OUTPUT_DIR,
            method=INITIAL_CORRECTION_METHOD,
            output_filename=
            base_name  # Pass the base name with extension if it has one
        )

        # ====================================================================
        # 【2단계】 정밀 기하보정 (STEP 11-20)
        # ====================================================================
        print("\n\n" + "=" * 80)
        print("【2단계 시작】 1차 보정된 이미지 기반 정밀 기하보정")
        print("=" * 80)

        # GCP chips가 제공된 경우 플래그 설정 (STEP 11-13에서 사용)
        use_gcp_chips = (GCP_CHIPS_DIR is not None
                         and os.path.exists(GCP_CHIPS_DIR))
        if use_gcp_chips:
            print("\n" + "=" * 80)
            print("GCP Chips 모드: GCP Chip 기반 계층적 매칭 수행")
            print("=" * 80)
            print(f"📁 GCP Chips 디렉토리: {GCP_CHIPS_DIR}")

        # STEP 11: 1차 보정된 이미지 재전처리
        print("\n" + "=" * 80)
        print("STEP 11: 1차 보정된 이미지 재전처리")
        print("=" * 80)
        TARGET_PATH2 = tar_corrected_path  # Step 10의 결과를 직접 사용
        OUTPUT_DIR2 = os.path.join(OUTPUT_DIR, r"step11_recropped")
        os.makedirs(OUTPUT_DIR2, exist_ok=True)

        # STEP 11-1: 입력 파일 검증 및 메타데이터 추출
        print("\n" + "=" * 80)
        print("STEP 11-1: 입력 파일 검증 및 메타데이터 추출")
        print("=" * 80)
        metadata2 = validate_inputs(REFERENCE_PATH, TARGET_PATH2, DEM_PATH,
                                    GEOID_PATH, OUTPUT_DIR)

        # STEP 11-2: 좌표계 통일 (REFERENCE 기준)
        print("\n" + "=" * 80)
        print("STEP 11-2: 좌표계 통일 (REFERENCE 기준)")
        print("=" * 80)
        unified_paths2 = unify_crs(metadata2, OUTPUT_DIR2,
                                   'step02_unified_crs', CURRENT_SET)

        # STEP 11-3: TARGET 영역 기준 잘라내기 (버퍼: 20%)
        print("\n" + "=" * 80)
        print(
            f"STEP 11-3: TARGET 영역 기준 잘라내기 (버퍼: {int((BUFFER_FACTOR-1)*100)}%)"
        )
        print("=" * 80)
        cropped_paths2 = crop_to_target_extent2(unified_paths2, OUTPUT_DIR2,
                                                BUFFER_FACTOR)

        # STEP 11-4: 해상도 정규화 (crop된 영상만 처리)
        print("\n" + "=" * 80)
        print("STEP 11-4: 해상도 정규화 (crop된 영상만 처리)")
        print("=" * 80)
        normalized_paths2 = normalize_resolution(cropped_paths2, metadata2,
                                                 OUTPUT_DIR2,
                                                 'step04_normalized',
                                                 CURRENT_SET)

        print("\n✅ STEP 11 완료: 재전처리가 완료되었습니다.\n")

        # ============================================================================================
        # STEP 11-5 ~ 11-7: DepthAnything 기반 깊이 추정 (현재 뒷 단계에서 사용되지 않음)
        # ============================================================================================
        # NOTE: Step 11-5~11-7에서 생성되는 depth_map, dem_masked 등은
        #       Step 12 이후 단계에서 사용되지 않으므로 주석 처리했습니다.
        #       필요시 아래 주석을 해제하여 사용할 수 있습니다.
        # ============================================================================================
        # STEP 11-5: 초기 기하보정 영상에 대해 DepthAnything V2 Large로 깊이 추정
        # run_step11_5_pipeline(OUTPUT_DIR, OUTPUT_DIR2, TARGET_PATH, INITIAL_CORRECTION_METHOD)
        # ============================================================================================

        ###########################################################################################
        # STEP 12: 계층적 패치 매칭
        print("\n" + "=" * 80)
        print("STEP 12: 계층적 패치 매칭 (1/4 해상도)")
        print("=" * 80)

        MATCH_METHOD = "ROMAV2"  # 정밀 매칭 알고리즘 설정: SIFT, LOFTR, SATLOFTR, LIGHTGLUE, ROMAV2

        # GCP chip이 있으면 GCP chip 기반으로, 없으면 SuperPoint 기반으로 매칭
        pyramid_matching_quarter_JW(
            OUTPUT_DIR,
            radius=200,
            max_show=100,
            gcp_chips_dir=GCP_CHIPS_DIR if use_gcp_chips else None,
            gcp_chip_resolution=GCP_CHIP_RESOLUTION if use_gcp_chips else None,
            target_bands=TARGET_BANDS,
            match_method=MATCH_METHOD)  # STEP 13: LoFTR 기반 정밀 매칭

        matching_results = PrcsnMatching(OUTPUT_DIR,
                                         MATCH_METHOD,
                                         target_resolution=TARGET_RESOLUTION)
        ###########################################################################################

        # STEP 14: 최종 GCP 생성 (RANSAC 필터링 및 그리드 세분화)
        # GCP chip 모드: 파일명의 고도(HAE)를 DEM 대신 직접 사용
        z_lookup = None
        if use_gcp_chips:
            import pandas as _pd
            _csv = os.path.join(OUTPUT_DIR, '04_patches', 'features_NMS.csv')
            if os.path.exists(_csv):
                _df = _pd.read_csv(_csv)
                if 'geo_z' in _df.columns and _df['geo_z'].notna().any():
                    z_lookup = {
                        (round(float(r.geo_x), 5), round(float(r.geo_y), 5)): float(r.geo_z)
                        for _, r in _df.iterrows()
                        if _pd.notna(r.get('geo_z')) and _pd.notna(r.get('geo_x'))
                    }
                    print(f"   ✅ GCP chip z_lookup 로드: {len(z_lookup)}개 고도값 사용")

        training_gcps, check_points, grid_info = create_final_gcps(
            matching_results, normalized_paths2, OUTPUT_DIR, z_lookup=z_lookup)

        # STEP 14.5: Pseudo GCP 생성 및 번들 조정 (RANSAC 필터링된 깨끗한 GCP 기반)
        from geometric_correction.pipeline.precision_correction import create_enhanced_gcps_with_bundle_adjustment
        final_training_gcps = create_enhanced_gcps_with_bundle_adjustment(
            training_gcps, grid_info, normalized_paths2, OUTPUT_DIR)

        # STEP 14+: 최종 GCP를 원본 TARGET 픽셀 좌표계로 역투영 및 시각화 저장
        # 실제 GCP와 pseudo GCP를 구분하기 위해 원본 training_gcps도 전달
        step14_plus_project_gcps_to_original_target(OUTPUT_DIR,
                                                    TARGET_PATH,
                                                    final_training_gcps,
                                                    normalized_paths2,
                                                    check_points,
                                                    real_gcps=training_gcps,
                                                    target_bands=TARGET_BANDS)
        #   # STEP 15: RPC 모델 생성
        # RPC 모델의 기준이 될 이미지(tar_corrected_path_for_rpc)는
        # 2단계 전처리가 완료된 'normalized_paths2['target']' 이어야 합니다.
        tar_corrected_path_for_rpc = normalized_paths2['target']

        # STEP 15 이전: 부트스트랩 워크플로우 (메타데이터 없는 위성용)
        #   Two-fit Architecture:
        #     [P] Production pass — Real GCP 전체로 fit → 정사보정에 사용
        #     [V] Validation pass — 80% train으로 fit → 20% holdout에 진짜 평가
        #     [S] Bias 동기화 — Validation 결정을 Production에 적용
        vis_dir = os.path.join(OUTPUT_DIR, '05_SuperPoint_result',
                               'step14_visualizations')
        orig_gcp_json = os.path.join(vis_dir,
                                     'step14_final_gcps_original_target.json')
        original_training_gcps = []
        original_training_gcps_real_only = []  # 전체 Real GCP
        train_real_gcps = []                    # validation pass의 train (80%)
        holdout_real_gcps = []                  # validation pass의 holdout (20%, training 미포함)
        seed_rpc_init = None                    # production seed
        bootstrap_ok = False

        try:
            with open(orig_gcp_json, 'r', encoding='utf-8') as f:
                conv = json.load(f)

            # Real GCP만 추출 (Pseudo는 폐기 — 부트스트랩에서 새로 만듦)
            for it in conv.get('gcps', []):
                c0 = it.get('col_original', None)
                r0 = it.get('row_original', None)
                inside = it.get('inside_original', False)
                is_real = it.get('is_real', True)
                if c0 is None or r0 is None or not inside or not is_real:
                    continue
                original_training_gcps_real_only.append(
                    GroundControlPoint(row=float(r0), col=float(c0),
                                       x=float(it['x']), y=float(it['y']),
                                       z=float(it['z']))
                )

            print(f"\n" + "=" * 80)
            print("STEP 14.9: 부트스트랩 (Production + Validation Two-fit)")
            print("=" * 80)
            print(f"   📊 추출된 Real GCP: {len(original_training_gcps_real_only)}개")

            if len(original_training_gcps_real_only) < 8:
                print(f"   ⚠️ Real GCP 부족 → fallback (기존 training_gcps 사용)")
                original_training_gcps = training_gcps
                original_training_gcps_real_only = training_gcps
                train_real_gcps = list(training_gcps)
                holdout_real_gcps = []
            else:
                # ==== [P] Production pass — 전체 Real GCP 사용 ====
                print(f"\n   ━━━ [P] Production pass (전체 {len(original_training_gcps_real_only)}개 Real GCP) ━━━")
                seed_model = fit_3d_polynomial_seed(
                    original_training_gcps_real_only, degree='auto')
                print(f"   🌱 Production seed: 차수={seed_model['degree']}, "
                      f"train RMSE={seed_model['rmse'][2]:.2f}px "
                      f"(n={seed_model['n_train']})")

                pseudo_gcps_prod = generate_pseudo_grid_3d_from_seed(
                    seed_model, TARGET_PATH,
                    original_training_gcps_real_only,
                    grid_n=15, n_layers=5,
                    normalized_paths=normalized_paths2,
                    use_land_mask=True,
                    use_real_hull=True,
                    hull_margin_ratio=0.05,
                    land_z_threshold=-1.0,
                )
                print(f"   🌐 Production Pseudo grid: {len(pseudo_gcps_prod)}개 (15×15×5, hull 커버)")

                original_training_gcps = list(original_training_gcps_real_only) + pseudo_gcps_prod

                seed_rpc_init = seed_to_rpc_init(
                    seed_model, original_training_gcps_real_only,
                    normalized_paths2)

                # ==== [V] Validation split — 진짜 holdout 분리 ====
                train_real_gcps, holdout_real_gcps = stratified_split_gcps_4quad(
                    original_training_gcps_real_only,
                    holdout_ratio=0.20, seed=42,
                )
                print(f"\n   ━━━ [V] Validation split: train {len(train_real_gcps)}개 / holdout {len(holdout_real_gcps)}개 ━━━")
                bootstrap_ok = True

        except Exception as e:
            print(
                f"   ⚠️ 부트스트랩 실패: {e} (fallback: 기존 training_gcps 사용)")
            import traceback; traceback.print_exc()
            original_training_gcps = training_gcps
            original_training_gcps_real_only = training_gcps
            train_real_gcps = list(training_gcps)
            holdout_real_gcps = []

        print(
            f"\n   📊 STEP 15 입력 GCP: 전체 {len(original_training_gcps)}개 "
            f"(Real: {len(original_training_gcps_real_only)}개, "
            f"Pseudo: {len(original_training_gcps) - len(original_training_gcps_real_only)}개, "
            f"validation holdout 별도: {len(holdout_real_gcps)}개)"
        )

        # 새 모듈 함수 호출로 STEP 15/15-1/15-2/16-b 실행
        step15_16_success = False
        try:
            # ==== [P] Production RPC fit v0 — 정사보정에 사용 ====
            print("\n   ━━━ [P] Production RPC fit v0 (전체 Real + Pseudo) ━━━")
            rpc_params, rpc_gdal_for_rpcm, rpc_obj = step15_rpcfit_generate(
                original_training_gcps, normalized_paths2, TARGET_PATH,
                OUTPUT_DIR, init=seed_rpc_init)

            # 08_Evaluation 디렉터리 구조 정의
            EVAL_DIR = os.path.join(OUTPUT_DIR, '08_Evaluation')
            PROD_EVAL_DIR = os.path.join(EVAL_DIR, 'production')
            VAL_EVAL_DIR = os.path.join(EVAL_DIR, 'validation')
            os.makedirs(PROD_EVAL_DIR, exist_ok=True)
            os.makedirs(VAL_EVAL_DIR, exist_ok=True)

            # ==== [P-iter] Production Recursive Pseudo Refinement ====
            #   RPC v0를 새 seed로 보고 Pseudo grid를 재평가 → RPC v1 → 반복
            #   seed 모델(degree<=3 polynomial)의 표현력 한계로 인한 Pseudo 노이즈 제거
            N_RECURSIVE = 2          # 보통 2~3회면 수렴
            EPSILON_PX = 0.05        # ΔRMSE 수렴 임계값 (px)
            prod_recur_history = []
            if bootstrap_ok:
                print(f"\n   ━━━ [P-iter] Recursive Pseudo Refinement (최대 {N_RECURSIVE}회, ε={EPSILON_PX}px) ━━━")
                for k in range(N_RECURSIVE):
                    try:
                        # 현재 RPC를 seed 인터페이스로 감싸기
                        rpc_as_seed = _make_seed_like_from_rpc(rpc_obj, normalized_paths2)
                        # Pseudo grid 재평가 (RPC 기반)
                        pseudo_refined = generate_pseudo_grid_3d_from_seed(
                            rpc_as_seed, TARGET_PATH,
                            original_training_gcps_real_only,
                            grid_n=15, n_layers=5,
                            normalized_paths=normalized_paths2,
                            use_land_mask=True, use_real_hull=True,
                            hull_margin_ratio=0.05, land_z_threshold=-1.0,
                        )
                        new_input = list(original_training_gcps_real_only) + pseudo_refined
                        # 직전 RPC를 init으로 사용
                        rp_new, rg_new, ro_new = step15_rpcfit_generate(
                            new_input, normalized_paths2, TARGET_PATH,
                            OUTPUT_DIR, init=rpc_obj,
                        )
                        # 수렴 측정 — 두 RPC가 Real GCP 위치에서 얼마나 다른가
                        delta = _compute_rpc_diff_rmse(
                            rpc_obj, ro_new,
                            original_training_gcps_real_only, normalized_paths2,
                        )
                        delta_record = {
                            'iter': k + 1,
                            'pseudo_count': len(pseudo_refined),
                            'delta_rmse_total': delta['rmse_total'],
                            'delta_rmse_col': delta['rmse_col'],
                            'delta_rmse_row': delta['rmse_row'],
                            'max_diff': delta['max_diff'],
                            'epsilon_px': EPSILON_PX,
                        }
                        prod_recur_history.append(delta_record)
                        print(f"   🔁 [P-iter] v{k+1}: Pseudo={len(pseudo_refined)}개, "
                              f"ΔRMSE_total={delta['rmse_total']:.4f}px "
                              f"(col {delta['rmse_col']:.4f}, row {delta['rmse_row']:.4f}, "
                              f"max {delta['max_diff']:.4f}px)")
                        # RPC 업데이트
                        rpc_params, rpc_gdal_for_rpcm, rpc_obj = rp_new, rg_new, ro_new
                        if delta['rmse_total'] < EPSILON_PX:
                            print(f"   ✅ [P-iter] 수렴 (ΔRMSE < {EPSILON_PX}px). 종료.")
                            break
                    except Exception as iter_e:
                        print(f"   ⚠️ [P-iter] iter {k+1} 실패: {iter_e} (직전 RPC 유지)")
                        import traceback; traceback.print_exc()
                        break

                # 수렴 궤적 저장 (JSON + PNG)
                try:
                    if prod_recur_history:
                        with open(os.path.join(PROD_EVAL_DIR, 'recursive_convergence.json'),
                                  'w', encoding='utf-8') as f:
                            json.dump(prod_recur_history, f, indent=2)
                        save_recursive_convergence_plot(
                            prod_recur_history, PROD_EVAL_DIR,
                            title_prefix="Production")
                        print(f"   💾 [P-iter] 수렴 로그: {PROD_EVAL_DIR}/recursive_convergence.{{json,png}}")
                except Exception as save_e:
                    print(f"   ⚠️ [P-iter] 수렴 로그 저장 실패: {save_e}")

            # ==== [V] Validation RPC fit — 진짜 holdout 평가용 ====
            #   08_Evaluation/validation/ 아래에 저장. holdout 데이터에 절대 노출 안 된 RPC를 만들어서 평가.
            _holdout_report = None

            if bootstrap_ok and len(holdout_real_gcps) >= 5 and len(train_real_gcps) >= 8:
                try:
                    print(f"\n   ━━━ [V] Validation RPC fit (train {len(train_real_gcps)}개 only) ━━━")
                    val_dir = VAL_EVAL_DIR
                    os.makedirs(val_dir, exist_ok=True)

                    val_seed = fit_3d_polynomial_seed(train_real_gcps, degree='auto')
                    val_pseudo = generate_pseudo_grid_3d_from_seed(
                        val_seed, TARGET_PATH, train_real_gcps,
                        grid_n=15, n_layers=5,
                        normalized_paths=normalized_paths2,
                        use_land_mask=True, use_real_hull=True,
                        hull_margin_ratio=0.05, land_z_threshold=-1.0,
                    )
                    val_input = list(train_real_gcps) + val_pseudo
                    val_seed_rpc = seed_to_rpc_init(val_seed, train_real_gcps, normalized_paths2)
                    val_rpc_params, val_rpc_gdal, val_rpc_obj = step15_rpcfit_generate(
                        val_input, normalized_paths2, TARGET_PATH, val_dir, init=val_seed_rpc)

                    # ==== [V-iter] Validation Recursive Pseudo Refinement ====
                    #   Production과 동일한 iteration 수로 안정화 → holdout 비교의 공정성 확보
                    val_recur_history = []
                    print(f"\n   ━━━ [V-iter] Validation Recursive Refinement (최대 {N_RECURSIVE}회, ε={EPSILON_PX}px) ━━━")
                    for k in range(N_RECURSIVE):
                        try:
                            v_rpc_as_seed = _make_seed_like_from_rpc(val_rpc_obj, normalized_paths2)
                            v_pseudo_refined = generate_pseudo_grid_3d_from_seed(
                                v_rpc_as_seed, TARGET_PATH, train_real_gcps,
                                grid_n=15, n_layers=5,
                                normalized_paths=normalized_paths2,
                                use_land_mask=True, use_real_hull=True,
                                hull_margin_ratio=0.05, land_z_threshold=-1.0,
                            )
                            v_new_input = list(train_real_gcps) + v_pseudo_refined
                            v_rp_new, v_rg_new, v_ro_new = step15_rpcfit_generate(
                                v_new_input, normalized_paths2, TARGET_PATH,
                                val_dir, init=val_rpc_obj,
                            )
                            v_delta = _compute_rpc_diff_rmse(
                                val_rpc_obj, v_ro_new,
                                train_real_gcps, normalized_paths2,
                            )
                            val_recur_history.append({
                                'iter': k + 1,
                                'pseudo_count': len(v_pseudo_refined),
                                'delta_rmse_total': v_delta['rmse_total'],
                                'delta_rmse_col': v_delta['rmse_col'],
                                'delta_rmse_row': v_delta['rmse_row'],
                                'max_diff': v_delta['max_diff'],
                                'epsilon_px': EPSILON_PX,
                            })
                            print(f"   🔁 [V-iter] v{k+1}: Pseudo={len(v_pseudo_refined)}개, "
                                  f"ΔRMSE_total={v_delta['rmse_total']:.4f}px "
                                  f"(col {v_delta['rmse_col']:.4f}, row {v_delta['rmse_row']:.4f}, "
                                  f"max {v_delta['max_diff']:.4f}px)")
                            val_rpc_params, val_rpc_gdal, val_rpc_obj = v_rp_new, v_rg_new, v_ro_new
                            if v_delta['rmse_total'] < EPSILON_PX:
                                print(f"   ✅ [V-iter] 수렴 (ΔRMSE < {EPSILON_PX}px). 종료.")
                                break
                        except Exception as v_iter_e:
                            print(f"   ⚠️ [V-iter] iter {k+1} 실패: {v_iter_e} (직전 RPC 유지)")
                            import traceback; traceback.print_exc()
                            break

                    # Validation 수렴 궤적 저장
                    try:
                        if val_recur_history:
                            with open(os.path.join(VAL_EVAL_DIR, 'recursive_convergence.json'),
                                      'w', encoding='utf-8') as f:
                                json.dump(val_recur_history, f, indent=2)
                            save_recursive_convergence_plot(
                                val_recur_history, VAL_EVAL_DIR,
                                title_prefix="Validation")
                            print(f"   💾 [V-iter] 수렴 로그: {VAL_EVAL_DIR}/recursive_convergence.{{json,png}}")
                    except Exception as v_save_e:
                        print(f"   ⚠️ [V-iter] 수렴 로그 저장 실패: {v_save_e}")

                    # 진짜 holdout RMSE 측정 (recursive 후 최종 RPC 기준)
                    val_rpc_params, val_rpc_gdal, val_rpc_obj, _holdout_report = \
                        step15_2_holdout_eval_and_bias(
                            val_rpc_params, val_rpc_gdal, val_rpc_obj,
                            real_gcps=None,
                            normalized_paths=normalized_paths2,
                            output_dir=val_dir,
                            train_gcps_override=train_real_gcps,
                            holdout_gcps_override=holdout_real_gcps,
                        )

                    # ==== [S] Bias 동기화 — validation 결정을 production에 적용 ====
                    if _holdout_report and _holdout_report.get('chosen') == 'rpc_plus_translation':
                        print("\n   ━━━ [S] Validation에서 bias 채택 → Production RPC에도 동기 적용 ━━━")
                        prod_bias = fit_rpc_residual_translation(
                            rpc_obj, original_training_gcps_real_only, normalized_paths2)
                        print(f"   📐 Production 잔차 평균: dc={prod_bias['dc']:+.3f}px, dr={prod_bias['dr']:+.3f}px")
                        rpc_params, rpc_gdal_for_rpcm, rpc_obj = absorb_translation_into_rpc(
                            rpc_params, rpc_gdal_for_rpcm, rpc_obj, prod_bias)
                        # Production RPC JSON 갱신
                        try:
                            rpc_out_dir = os.path.join(OUTPUT_DIR, 'step15_rpc')
                            os.makedirs(rpc_out_dir, exist_ok=True)
                            rpc_json_path = os.path.join(rpc_out_dir, 'rpc_model.json')
                            with open(rpc_json_path, 'w', encoding='utf-8') as f:
                                json.dump(rpc_params, f, indent=2)
                            print(f"   💾 Production RPC JSON 갱신: {rpc_json_path}")
                        except Exception as je:
                            print(f"   ⚠️ Production RPC JSON 갱신 실패: {je}")
                    else:
                        print("\n   ➡️ Validation에서 bias 미채택 → Production RPC도 단독 유지")

                    print(f"\n   🎯 진짜 holdout RMSE (validation 기준): "
                          f"{_holdout_report['holdout_rmse_rpc_only']['total_rmse']:.3f}px "
                          f"(col {_holdout_report['holdout_rmse_rpc_only']['col_rmse']:.3f}, "
                          f"row {_holdout_report['holdout_rmse_rpc_only']['row_rmse']:.3f})")

                    # STEP 15-3: 잔차 시각화 진단 (validation RPC + train/holdout 분리)
                    try:
                        step15_3_residual_diagnostics(
                            rpc_obj=val_rpc_obj,
                            train_gcps=train_real_gcps,
                            holdout_gcps=holdout_real_gcps,
                            normalized_paths=normalized_paths2,
                            target_path=TARGET_PATH,
                            output_dir=val_dir,
                            title_prefix="Validation RPC 잔차",
                        )
                    except Exception as diag_e:
                        print(f"   ⚠️ STEP 15-3 잔차 진단 실패: {diag_e}")
                        import traceback; traceback.print_exc()
                except Exception as val_e:
                    print(f"   ⚠️ Validation pass 실패 (production은 정상 사용): {val_e}")
                    import traceback; traceback.print_exc()
            else:
                print(f"\n   ⚠️ Validation pass 생략 (holdout {len(holdout_real_gcps)}개 < 5 또는 train 부족)")

            # STEP 15-3 (Production): 자체 fit 잔차도 진단 (참고용) → 08_Evaluation/production/
            try:
                step15_3_residual_diagnostics(
                    rpc_obj=rpc_obj,
                    train_gcps=original_training_gcps_real_only,
                    holdout_gcps=None,
                    normalized_paths=normalized_paths2,
                    target_path=TARGET_PATH,
                    output_dir=PROD_EVAL_DIR,
                    title_prefix="Production RPC 잔차 (self-fit)",
                )
            except Exception as diag_e:
                print(f"   ⚠️ Production 잔차 진단 실패: {diag_e}")
                import traceback; traceback.print_exc()

            # STEP 15-1: Production RPC 정확도 평가 (Self-fit + 5-fold CV, 전체 Real)
            #   - Production은 전체 데이터로 fit됐으므로 전체 Real로 self-fit + CV
            #   - 진짜 holdout 평가는 08_Evaluation/validation/ 폴더에 저장됨
            #   - 결과 → 08_Evaluation/production/step15_rpc_eval/
            try:
                step15_1_rpcfit_evaluate_with_cv(
                    real_gcps=original_training_gcps_real_only,
                    rpc_obj=rpc_obj,
                    normalized_paths2=normalized_paths2,
                    target_path=TARGET_PATH,
                    output_dir=PROD_EVAL_DIR,
                    k_folds=5,
                )
            except Exception as eval_e:
                print(f"   ⚠️ STEP 15-1 정확도 평가 실패 (파이프라인 계속): {eval_e}")
                import traceback; traceback.print_exc()

            print("   ℹ️ STEP 16 정사보정 수행")
            # step16b_rpcm_correct(
            #     rpc_params, rpc_gdal_for_rpcm, normalized_paths2, OUTPUT_DIR, TARGET_PATH, DEM_PATH, GEOID_PATH
            # )
            step16_orthorectification(
                TARGET_PATH,
                OUTPUT_DIR,
                rpc_params,
                DEM_PATH,
                GEOID_PATH,
                rpc_gdal_for_rpcm=rpc_gdal_for_rpcm,
            )
            step15_16_success = True
            print("\n✅ STEP 15/16 완료: RPC 기반 정밀 기하보정이 성공적으로 완료되었습니다.")

            # STEP 16 성공 시 최종 결과 확인 및 GCP chip 추출
            # 최종 보정 영상에서 GCP chip 추출
            base_name = os.path.splitext(os.path.basename(TARGET_PATH))[0]
            final_results_dir = os.path.join(OUTPUT_DIR, '07_Final_results')

            print(f"\n🔍 GCP 추출 경로 디버깅:")
            print(f"   - Target Base Name: {base_name}")
            print(f"   - Final Results Dir: {final_results_dir}")

            # 우선순위 1: merged_{location}.tif (사용자 확인 경로)
            final_image_path = os.path.join(final_results_dir,
                                            f'{base_name}.tiff')
            print(
                f"   - Check Path 1: {final_image_path} -> Exists: {os.path.exists(final_image_path)}"
            )

            if not os.path.exists(final_image_path):
                # 우선순위 2: _final_rpcm.tif (기존 로직)
                final_image_path = os.path.join(final_results_dir,
                                                f'{base_name}_final_rpcm.tif')

            if not os.path.exists(final_image_path):
                # 우선순위 3: step16_final_corrected 폴더 (구버전 호환)
                step16_dir = os.path.join(OUTPUT_DIR, 'step16_final_corrected')
                final_image_path = os.path.join(
                    step16_dir, f'{base_name}_final_rpc_corrected.tif')

            # 최종 영상이 존재하면 GCP chip 추출 (Real GCP만 사용)
            if os.path.exists(final_image_path):
                print(f"\n🔍 최종 보정 영상 발견: {final_image_path}")
                print(
                    f"   Real GCP ({len(original_training_gcps_real_only)}개)에서 chip 추출 시작..."
                )
                print(f"   ℹ️  Pseudo GCP는 chip 추출에서 제외됩니다.")
                extract_gcp_chips_from_final_image(
                    final_image_path=final_image_path,
                    gcps=original_training_gcps_real_only,
                    output_dir=OUTPUT_DIR,
                    dem_path=DEM_PATH,
                    geoid_path=GEOID_PATH,
                    chip_size=513)
            else:
                print(f"   ⚠️ 최종 보정 영상을 찾을 수 없습니다. GCP chip 추출을 건너뜁니다.")
                print(f"   확인한 경로:")
                print(
                    f"     - {os.path.join(final_results_dir, f'{base_name}_final_rpcm.tif')}"
                )
                print(
                    f"     - {os.path.join(OUTPUT_DIR, 'step16_final_corrected', f'{base_name}_final_rpc_corrected.tif')}"
                )
        except Exception as e:
            print(f"\n⚠️ STEP 15/16-b 실행 실패: {e}")
            print(f"   ℹ️ STEP 10의 초기 기하보정 결과를 최종 결과로 사용합니다.")

            # STEP 10 결과를 최종 결과로 복사
            import shutil
            step10_result_path = tar_corrected_path  # STEP 10에서 생성된 경로

            # final_results 폴더 생성
            final_results_dir = os.path.join(OUTPUT_DIR, '07_Final_results')
            os.makedirs(final_results_dir, exist_ok=True)

            # 최종 결과 파일명 생성
            base_name = os.path.splitext(os.path.basename(TARGET_PATH))[0]
            final_result_path = os.path.join(
                final_results_dir, f'{base_name}_final_initial_corrected.tif')

            # STEP 10 결과 확인 및 복사
            if os.path.exists(step10_result_path):
                print(f"\n📋 STEP 10 결과 복사 중...")
                print(f"   원본: {step10_result_path}")
                print(f"   목적지: {final_result_path}")

                # 파일 복사
                shutil.copy2(step10_result_path, final_result_path)

                # 파일 정보 출력
                try:
                    import rasterio
                    with rasterio.open(final_result_path) as src:
                        print(f"\n✅ 최종 결과 저장 완료 (STEP 10 초기 기하보정 결과)")
                        print(f"   📁 저장 위치: {final_result_path}")
                        print(f"   📊 크기: {src.width} x {src.height} pixels")
                        print(f"   📐 CRS: {src.crs}")
                        print(f"   ⚠️ 참고: RPC 모델은 제공되지 않습니다 (초기 기하보정 결과입니다).")
                        print(f"   ℹ️ 영상은 지오레퍼런싱되어 있습니다.")
                except Exception as info_e:
                    print(f"   ⚠️ 파일 정보 확인 실패: {info_e}")
            else:
                print(f"   ❌ STEP 10 결과 파일을 찾을 수 없습니다: {step10_result_path}")
                print(f"   ⚠️ 최종 결과가 저장되지 않았습니다.")

        # 이하의 기존 인라인 구현은 보존하되 실행 건너뜀
        return

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # 로그 파일 정리
        end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # stdout/stderr 복원 (로그 파일이 열려있는 경우)
        if log_file is not None:
            try:
                print(f"\n{'='*80}")
                print(f"파이프라인 종료 시간: {end_time}")
                print(f"로그 파일 저장 위치: {log_filepath}")
                print(f"{'='*80}\n")
            except:
                pass

            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_file.close()
            print(f"💾 로그가 저장되었습니다: {log_filepath}\n")




if __name__ == "__main__":
    setup_korean_font()

    import argparse
    parser = argparse.ArgumentParser(description="2단계 정밀 기하보정 통합 파이프라인")

    # 필수 경로 인자
    parser.add_argument("--dem", help="DEM 파일 경로")
    parser.add_argument("--geoid", help="Geoid 파일 경로")
    parser.add_argument("--ref", help="Reference(Sentinel) 영상 경로")
    parser.add_argument("--target", help="Target(BlueBON) 영상 경로")
    parser.add_argument("--output", help="출력 디렉토리 경로")

    # 메타데이터 인자
    parser.add_argument("--lat", type=float, help="Target 중심 위도")
    parser.add_argument("--lon", type=float, help="Target 중심 경도")
    parser.add_argument("--res", type=float, help="Target 해상도 (m)")

    # 선택적 인자
    parser.add_argument("--bands", type=int, nargs='+', help="Target 밴드 인덱스 (R G B 순서, 1-based). 예: PlanetScope -> 6 4 2")
    parser.add_argument("--gcp_chips", help="GCP Chips 디렉토리 경로 (재사용 시)")
    parser.add_argument("--gcp_chip_res", type=float, help="GCP chip 해상도 (m/px, 기본값: 1.2)")
    parser.add_argument("--output_name", help="출력 파일 기본 이름 (확장자 제외, 예: bb_l1b_20260116_021517_8band)")

    args = parser.parse_args()

    # 모든 필수 인자가 제공되었는지 확인
    if all([args.dem, args.geoid, args.ref, args.target, args.output, args.lat is not None, args.lon is not None, args.res is not None]):
        main(
            dem_path=args.dem,
            geoid_path=args.geoid,
            reference_path=args.ref,
            target_path=args.target,
            output_dir=args.output,
            target_center_lat=args.lat,
            target_center_lon=args.lon,
            target_resolution=args.res,
            target_bands=args.bands,
            gcp_chips_dir=args.gcp_chips,
            gcp_chip_resolution=args.gcp_chip_res,
            output_name_base=args.output_name
        )
    else:
        # 인자가 부족하면 기존 하드코딩된 설정 사용 (개발/테스트용)
        # print("ℹ️ CLI 인자가 제공되지 않아 내부 설정(CURRENT_SET)을 사용합니다.")
        main()
