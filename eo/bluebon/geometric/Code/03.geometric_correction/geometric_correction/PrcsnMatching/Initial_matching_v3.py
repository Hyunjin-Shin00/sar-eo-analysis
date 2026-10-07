import torch
from torchvision.utils import save_image
from lightglue import LightGlue, SuperPoint, DISK, SIFT, ALIKED, DoGHardNet
from lightglue.utils import rbd
import matplotlib.patches as patches
import cv2
import os, re, cv2, numpy as np, torch, pandas as pd
from openpyxl.styles import PatternFill
import torch.nn.functional as F
import numpy as np
import math
import rasterio
import rasterio.warp
from rasterio.enums import Resampling
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps
import os
import json
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Optional
from affine import Affine
from pyproj import Transformer
import matplotlib.pyplot as plt
import matplotlib
import matplotlib.font_manager as fm
from osgeo import gdal, osr

# GDAL 경고 제거
try:
    gdal.UseExceptions()
except:
    pass

from kornia.feature import LoFTR
from lightglue.utils import load_image, rbd
from openpyxl.styles import PatternFill
from geometric_correction.utils.io import *

def stretch_bhw(tensor: torch.Tensor) -> torch.Tensor:
    """
    텐서를 0-1 범위로 스트레칭 (유틸리티 함수)
    
    Input:
        tensor (torch.Tensor): 입력 텐서
    
    Output:
        torch.Tensor: 스트레칭된 텐서 (0-1 범위)
    
    Algorithm:
        - Min-Max 정규화를 통한 스트레칭
        - 텐서의 최솟값과 최댓값을 기준으로 정규화
        - 딥러닝 모델 입력을 위한 전처리
    """
    tensor = tensor.float()
    tensor = (tensor - tensor.min()) / (tensor.max() - tensor.min() + 1e-8)
    return tensor
## Keypoints 제거 순서: NMS 거리 기반 처리 -> 검은 픽셀 0 과다시 제거
def pyramid_matching_quarter_JW(out_path, radius=500, max_show=20, gcp_chips_dir=None, gcp_chip_resolution=None, target_bands=None, match_method=""):
    """
    BlueBON 초기보정 영상에서 그리드 기반 SuperPoint 특징점 균등 추출.

    LightGlue 매칭 없이 순수하게 특징점 추출만 수행:
    - 유효 픽셀 Bounding Box 내에서 10×30 그리드 분할 (가로 10, 세로 30)
    - 각 셀에서 SuperPoint를 배치(batch)로 실행, 가장 score가 높은 특징점 1개 선택
    - 선택된 특징점 좌표를 중심으로 BlueBON 패치 저장

    GCP chip 모드(gcp_chips_dir 지정 시)는 기존 로직을 그대로 사용.
    """
    # ── 경로 설정 ──────────────────────────────────────────────────────────
    bluebon_path  = os.path.join(out_path, 'step11_recropped/step03_cropped/target.tif')
    sentinel_path = os.path.join(out_path, "step11_recropped/step04_normalized/reference_normalized.tif")

    patches_base_dir = os.path.join(out_path, '04_patches')

    # GCP chip 모드 여부 판단
    use_gcp_chip_mode = (gcp_chips_dir is not None and os.path.exists(gcp_chips_dir))

    if use_gcp_chip_mode:
        S_dir = os.path.join(patches_base_dir, 'GCPChip_224')
    else:
        S_dir = os.path.join(patches_base_dir, 'Sentinel_196')   # 하위 호환 (사용 안 함)

    B_dir = os.path.join(patches_base_dir, 'Bluebon_128')
    os.makedirs(B_dir, exist_ok=True)
    os.makedirs(S_dir, exist_ok=True)

    viz_out_dir    = patches_base_dir
    os.makedirs(viz_out_dir, exist_ok=True)

    csv_all_path   = os.path.join(viz_out_dir, "keypoints_all.csv")
    csv_nms_path   = os.path.join(viz_out_dir, "features_NMS.csv")
    csv_final_path = os.path.join(viz_out_dir, "keypoints_final.csv")

    # 패치 크기
    B_patch_size     = 128
    B_patch_size_roi = 128
    if use_gcp_chip_mode:
        S_patch_size     = 224
        S_patch_size_roi = 224
    else:
        S_patch_size     = 192
        S_patch_size_roi = 192
    if match_method.upper() == "ROMAV2":
        B_patch_size = 512
        S_patch_size = 512

    # ══════════════════════════════════════════════════════════════════════
    # GCP chip 모드: 기존 로직 그대로 유지
    # ══════════════════════════════════════════════════════════════════════
    if use_gcp_chip_mode:
        Sentinel = load_image_gdal(sentinel_path, reverse_bands=True)

        # 밴드 수 체크 후 BlueBON 로드
        try:
            with rasterio.open(bluebon_path) as src:
                actual_bands = src.count
            safe_target_bands = target_bands
            if target_bands:
                if max(target_bands) > actual_bands:
                    print(f"   ⚠️ 요청 밴드({target_bands})가 실제 밴드 수({actual_bands})를 초과합니다. 밴드 1을 사용합니다.")
                    safe_target_bands = [1]
            Bluebon = load_image_gdal(bluebon_path, target_bands=safe_target_bands)
        except Exception as e:
            print(f"   ⚠️ 이미지 로드 실패({e}). 기본값으로 재시도합니다.")
            Bluebon = load_image_gdal(bluebon_path, target_bands=None)

        print(f"\n📁 GCP Chip 모드: GCP chip 지리좌표로 패치 추출 및 저장")
        from PIL import Image
        import json
        from pyproj import Transformer

        chip_files = sorted([
            f for f in os.listdir(gcp_chips_dir)
            if f.lower().endswith(('.png', '.tif', '.tiff')) and not f.startswith('._')
        ])

        if len(chip_files) == 0:
            print("   ⚠️ GCP chip 파일을 찾을 수 없습니다. SuperPoint 그리드 모드로 전환합니다.")
            use_gcp_chip_mode = False
        else:
            print(f"   📊 GCP chip 개수: {len(chip_files)}")
            use_gcp_chips = True

            with rasterio.open(bluebon_path) as bluebon_src:
                actual_bands = bluebon_src.count
                # Red 밴드 결정 로직: 8밴드는 4번, 4밴드는 3번
                if actual_bands == 8:
                    red_band_idx = 4
                    print(f"   ℹ️  BlueBON Red 밴드 선택: 4번 (총 8밴드)")
                elif actual_bands == 4:
                    red_band_idx = 3
                    print(f"   ℹ️  BlueBON Red 밴드 선택: 3번 (총 4밴드)")
                else:
                    red_band_idx = 1
                    print(f"   ℹ️  BlueBON Red 밴드 기본 선택: 1번 (총 {actual_bands}밴드)")

                bluebon_img_orig = bluebon_src.read(red_band_idx).astype(np.float32)
                bluebon_transform_orig   = bluebon_src.transform
                bluebon_crs              = bluebon_src.crs
                bluebon_height_orig, bluebon_width_orig = bluebon_img_orig.shape

                target_pixel_size_x_orig_deg = abs(bluebon_transform_orig.a)
                target_pixel_size_y_orig_deg = abs(bluebon_transform_orig.e)

                if bluebon_crs and bluebon_crs.is_geographic:
                    center_x_px = bluebon_width_orig  / 2
                    center_y_px = bluebon_height_orig / 2
                    center_lon  = bluebon_transform_orig.c + center_x_px * bluebon_transform_orig.a + center_y_px * bluebon_transform_orig.b
                    center_lat  = bluebon_transform_orig.f + center_x_px * bluebon_transform_orig.d + center_y_px * bluebon_transform_orig.e
                    meters_per_degree_lat = 111320.0
                    meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_lat))
                    target_pixel_size_x_orig = target_pixel_size_x_orig_deg * meters_per_degree_lon
                    target_pixel_size_y_orig = target_pixel_size_y_orig_deg * meters_per_degree_lat
                else:
                    target_pixel_size_x_orig = target_pixel_size_x_orig_deg
                    target_pixel_size_y_orig = target_pixel_size_y_orig_deg

                target_pixel_size_orig   = max(target_pixel_size_x_orig, target_pixel_size_y_orig)
                gcp_chip_pixel_size_orig = float(gcp_chip_resolution) if gcp_chip_resolution is not None else 1.2
                use_target_resampling    = target_pixel_size_orig < gcp_chip_pixel_size_orig
                use_chip_resampling      = not use_target_resampling

                if use_target_resampling:
                    scale_factor_x = target_pixel_size_x_orig / gcp_chip_pixel_size_orig
                    scale_factor_y = target_pixel_size_y_orig / gcp_chip_pixel_size_orig
                    new_width  = int(round(bluebon_width_orig  * scale_factor_x))
                    new_height = int(round(bluebon_height_orig * scale_factor_y))
                    print(f"   🔄 Target 영상 리샘플링: {target_pixel_size_orig:.3f}m → {gcp_chip_pixel_size_orig:.3f}m")
                    bluebon_img    = cv2.resize(bluebon_img_orig, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
                    scale_x_inv    = bluebon_width_orig  / new_width
                    scale_y_inv    = bluebon_height_orig / new_height
                    bluebon_transform = rasterio.Affine(
                        bluebon_transform_orig.a * scale_x_inv, bluebon_transform_orig.b, bluebon_transform_orig.c,
                        bluebon_transform_orig.d, bluebon_transform_orig.e * scale_y_inv, bluebon_transform_orig.f
                    )
                    bluebon_height, bluebon_width = bluebon_img.shape
                    target_pixel_size_x = gcp_chip_pixel_size_orig
                    target_pixel_size_y = gcp_chip_pixel_size_orig
                else:
                    bluebon_img   = bluebon_img_orig
                    bluebon_transform = bluebon_transform_orig
                    bluebon_height, bluebon_width = bluebon_img.shape
                    target_pixel_size_x = target_pixel_size_x_orig
                    target_pixel_size_y = target_pixel_size_y_orig
                    print(f"   ℹ️  Target 해상도 사용: {target_pixel_size_orig:.3f}m (GCP chip을 리샘플링)")

            with rasterio.open(sentinel_path) as sentinel_src:
                sentinel_transform = sentinel_src.transform
                sentinel_crs       = sentinel_src.crs

            if sentinel_crs != bluebon_crs:
                transformer = Transformer.from_crs(bluebon_crs, sentinel_crs, always_xy=True)
            else:
                transformer = None

            metadata_json_path = os.path.join(gcp_chips_dir, 'gcp_chips_metadata.json')
            metadata_dict = {}
            if os.path.exists(metadata_json_path):
                try:
                    with open(metadata_json_path, 'r', encoding='utf-8') as f:
                        all_metadata = json.load(f)
                        for meta in all_metadata:
                            metadata_dict[meta.get('chip_filename')] = meta
                except Exception:
                    pass

            gcp_chip_info_list = []
            stats = {'total_chips': len(chip_files), 'no_coords': 0, 'out_of_bounds': 0,
                     'too_many_zeros': 0, 'success': 0, 'errors': 0}

            bluebon_img_norm  = (bluebon_img - bluebon_img.min()) / (bluebon_img.max() - bluebon_img.min() + 1e-8)
            bluebon_img_uint8 = (bluebon_img_norm * 255).astype(np.uint8)
            print(f"   📊 Target 영상 크기: {bluebon_width}x{bluebon_height}, Pixel size: {target_pixel_size_x:.3f}m")

            for chip_file in chip_files:
                try:
                    chip_path     = os.path.join(gcp_chips_dir, chip_file)
                    # TIF 파일은 16-bit일 수 있으므로 rasterio로 읽어 정규화
                    if chip_file.lower().endswith(('.tif', '.tiff')):
                        with rasterio.open(chip_path) as _csrc:
                            _cb = _csrc.count
                            _cidx = 4 if _cb >= 8 else (3 if _cb >= 4 else 1)
                            _cdata = _csrc.read(_cidx).astype(np.float32)
                        _cmin, _cmax = _cdata.min(), _cdata.max()
                        chip_img_orig = ((_cdata - _cmin) / (_cmax - _cmin + 1e-8) * 255).astype(np.uint8)
                    else:
                        chip_img_orig = cv2.imread(chip_path, cv2.IMREAD_GRAYSCALE)
                        if chip_img_orig is None:
                            chip_img_orig = np.array(Image.open(chip_path).convert('L'))
                    gcp_chip_size_orig       = chip_img_orig.shape[0]
                    gcp_chip_pixel_size_loop = float(gcp_chip_resolution) if gcp_chip_resolution is not None else 1.2

                    if use_chip_resampling:
                        gcp_chip_ground_size     = gcp_chip_size_orig * gcp_chip_pixel_size_loop
                        gcp_chip_size_resampled  = int(round(gcp_chip_ground_size / target_pixel_size_x))
                        gcp_chip_size_resampled  = max(gcp_chip_size_resampled, gcp_chip_size_orig // 2)
                        chip_img         = cv2.resize(chip_img_orig, (gcp_chip_size_resampled, gcp_chip_size_resampled), interpolation=cv2.INTER_LINEAR)
                        gcp_chip_size    = gcp_chip_size_resampled
                        gcp_chip_pixel_size_x = target_pixel_size_x
                        gcp_chip_pixel_size_y = target_pixel_size_y
                    else:
                        chip_img = chip_img_orig
                        gcp_chip_size    = gcp_chip_size_orig
                        gcp_chip_pixel_size_x = gcp_chip_pixel_size_loop
                        gcp_chip_pixel_size_y = gcp_chip_pixel_size_loop

                    meta  = metadata_dict.get(chip_file, {})
                    geo_x = meta.get('x', 0.0)
                    geo_y = meta.get('y', 0.0)
                    geo_z = meta.get('z', meta.get('altitude', None))  # metadata에서 z 우선 추출
                    if geo_x == 0.0 and geo_y == 0.0:
                        import re as _re
                        m2 = _re.search(r'_x(-?\d+(?:\.\d+)?)_y(-?\d+(?:\.\d+)?)(?:_z(-?\d+(?:\.\d+)?))?', chip_file)
                        if m2:
                            geo_x = float(m2.group(1))
                            geo_y = float(m2.group(2))
                            if geo_z is None and m2.group(3):
                                geo_z = float(m2.group(3))
                    if geo_x == 0.0 or geo_y == 0.0:
                        stats['no_coords'] += 1
                        continue

                    inv_bluebon_transform = ~bluebon_transform
                    target_col, target_row = inv_bluebon_transform * (geo_x, geo_y)
                    target_col = int(round(target_col))
                    target_row = int(round(target_row))

                    gcp_chip_ground_size_x = gcp_chip_size * gcp_chip_pixel_size_x
                    gcp_chip_ground_size_y = gcp_chip_size * gcp_chip_pixel_size_y
                    target_patch_size_x    = max(int(round(gcp_chip_ground_size_x / target_pixel_size_x)), gcp_chip_size)
                    target_patch_size_y    = max(int(round(gcp_chip_ground_size_y / target_pixel_size_y)), gcp_chip_size)
                    half_patch_x = target_patch_size_x // 2
                    half_patch_y = target_patch_size_y // 2

                    if (target_col < half_patch_x or target_col >= bluebon_width  - half_patch_x or
                            target_row < half_patch_y or target_row >= bluebon_height - half_patch_y):
                        stats['out_of_bounds'] += 1
                        continue

                    target_patch_orig = bluebon_img_uint8[
                        target_row - half_patch_y:target_row + half_patch_y,
                        target_col - half_patch_x:target_col + half_patch_x
                    ]
                    zero_ratio = np.sum(target_patch_orig == 0) / target_patch_orig.size
                    if zero_ratio >= 0.1:
                        stats['too_many_zeros'] = stats.get('too_many_zeros', 0) + 1
                        continue

                    stats['success'] += 1
                    ref_geo_x, ref_geo_y = geo_x, geo_y
                    if transformer is not None:
                        ref_geo_x, ref_geo_y = transformer.transform(geo_x, geo_y)
                    inv_sentinel_transform = ~sentinel_transform
                    sentinel_col, sentinel_row = inv_sentinel_transform * (ref_geo_x, ref_geo_y)

                    gcp_chip_info_list.append({
                        'chip_file': chip_file,    'chip_path': chip_path,
                        'chip_img': chip_img.copy(), 'chip_img_orig': chip_img_orig.copy(),
                        'target_patch': target_patch_orig.copy(),
                        'geo_x': geo_x,            'geo_y': geo_y,   'geo_z': geo_z,
                        'target_col': target_col,  'target_row': target_row,
                        'sentinel_col': sentinel_col, 'sentinel_row': sentinel_row,
                        'gcp_chip_size': gcp_chip_size, 'gcp_chip_size_orig': gcp_chip_size_orig,
                        'target_patch_size_x': target_patch_size_x,
                        'target_patch_size_y': target_patch_size_y,
                    })
                except Exception as e:
                    stats['errors'] += 1
                    if stats['errors'] <= 5:
                        print(f"   ⚠️ Chip {chip_file} 처리 실패: {e}")
                    continue

            print(f"   📊 GCP Chip 패치 추출 통계:")
            print(f"      전체: {stats['total_chips']}개")
            print(f"      좌표 없음: {stats['no_coords']}개")
            print(f"      영역 밖: {stats['out_of_bounds']}개")
            print(f"      Zero-padding 과다 (≥10%): {stats.get('too_many_zeros', 0)}개")
            print(f"      에러: {stats['errors']}개")
            print(f"      ✅ 패치 추출 성공: {stats['success']}개")

            if len(gcp_chip_info_list) == 0:
                print("   ⚠️ GCP chip 패치 추출 실패. SuperPoint 그리드 모드로 전환합니다.")
                use_gcp_chip_mode = False
            else:
                # ── GCP chip 패치 파일 저장 ──────────────────────────────────
                print(f"\n💾 GCP chip 패치 저장 ({len(gcp_chip_info_list)}개)...")
                final_rows = []

                for idx, info in enumerate(gcp_chip_info_list):
                    try:
                        # S_dir: GCP chip 이미지 자체를 참조 패치로 저장
                        chip_ref = info['chip_img']
                        if chip_ref.shape[0] != S_patch_size or chip_ref.shape[1] != S_patch_size:
                            chip_ref = cv2.resize(chip_ref, (S_patch_size, S_patch_size),
                                                  interpolation=cv2.INTER_LINEAR)

                        # B_dir: BlueBON 타겟 패치 저장
                        tgt_patch = info['target_patch']
                        if tgt_patch.shape[0] != B_patch_size or tgt_patch.shape[1] != B_patch_size:
                            tgt_patch = cv2.resize(tgt_patch, (B_patch_size, B_patch_size),
                                                   interpolation=cv2.INTER_LINEAR)

                        s_row = info['sentinel_row']
                        s_col = info['sentinel_col']
                        t_row = info['target_row']
                        t_col = info['target_col']

                        base   = f"patch{idx:03d}_Sentinel_{s_row:.2f}_{s_col:.2f}_Bluebon_{t_row:.2f}_{t_col:.2f}.tif"
                        fname_b = os.path.join(B_dir, base)
                        fname_s = os.path.join(S_dir, base)

                        save_image(torch.from_numpy(tgt_patch.astype(np.float32) / 255.0).unsqueeze(0), fname_b)
                        save_image(torch.from_numpy(chip_ref.astype(np.float32) / 255.0).unsqueeze(0), fname_s)

                        final_rows.append({
                            'patch_idx':           idx,
                            'bluebon_x':           float(t_col),
                            'bluebon_y':           float(t_row),
                            'sentinel_x':          float(s_col),
                            'sentinel_y':          float(s_row),
                            'score':               1.0,
                            'bluebon_patch_path':  fname_b,
                            'sentinel_patch_path': fname_s,
                            'B_patch_size_roi':    B_patch_size_roi,
                            'S_patch_size_roi':    S_patch_size_roi,
                            'geo_x':               info['geo_x'],
                            'geo_y':               info['geo_y'],
                            'geo_z':               info['geo_z'],  # GCP chip 파일명의 고도 (HAE)
                        })
                    except Exception as e:
                        print(f"   ⚠️ 패치 저장 실패 ({info.get('chip_file', '?')}): {e}")
                        continue

                pd.DataFrame(final_rows).to_csv(csv_final_path, index=False)
                pd.DataFrame(final_rows).to_csv(csv_nms_path,   index=False)
                pd.DataFrame(final_rows).to_csv(csv_all_path,   index=False)

                # 시각화: BlueBON 위에 GCP 위치 표시
                try:
                    fig, ax = plt.subplots(figsize=(10, 10))
                    ax.imshow(bluebon_img_norm, cmap='gray')
                    if final_rows:
                        xs = [r['bluebon_x'] for r in final_rows]
                        ys = [r['bluebon_y'] for r in final_rows]
                        ax.scatter(xs, ys, s=60, c='lime', marker='+', linewidths=2)
                    ax.set_title(f"GCP Chip Matching — {len(final_rows)} GCPs")
                    ax.axis("off")
                    plt.savefig(os.path.join(viz_out_dir, "BlueBON_features_NMS.png"),
                                dpi=200, bbox_inches="tight")
                    plt.close(fig)
                except Exception as ve:
                    print(f"   ⚠️ 시각화 저장 실패: {ve}")

                print(f"   ✅ GCP chip 패치 저장 완료: {len(final_rows)}개 → B={B_dir}, S={S_dir}")

                return {
                    'B_dir':       B_dir,
                    'S_dir':       S_dir,
                    'num_patches': len(final_rows),
                    'csv_all':     csv_all_path,
                    'csv_nms':     csv_nms_path,
                    'csv_final':   csv_final_path,
                }

    # ══════════════════════════════════════════════════════════════════════
    # SuperPoint 그리드 모드 (LightGlue 없이 순수 특징점 추출)
    # ══════════════════════════════════════════════════════════════════════
    if not use_gcp_chip_mode:
        print("\n🔍 그리드 기반 SuperPoint 특징점 추출 시작")

        # ── 1. BlueBON 영상 로드 (grayscale) ──────────────────────────────
        # 기본: Red 밴드 (8밴드→4, 4밴드→3, 그 외→1)
        # 손상 대응: Sentinel-2 reference와 spectral 매핑 가능한 밴드만 fallback 후보
        #   BlueBON 4(Red)↔Sentinel s_arr[0](B4), 3(Green)↔s_arr[1](B3), 2(Blue)↔s_arr[2](B2)
        chosen_idx = None   # BlueBON에서 실제 선택된 밴드 (Sentinel 측에서 참조)
        try:
            with rasterio.open(bluebon_path) as src:
                actual_bands = src.count
                if actual_bands >= 8:
                    primary_idx = 4
                    trial_order = [4, 3, 2]    # Red → Green → Blue (Sentinel 매핑 가능)
                elif actual_bands >= 4:
                    primary_idx = 3
                    trial_order = [3, 2, 1]
                else:
                    primary_idx = 1
                    trial_order = list(range(1, actual_bands + 1))

                bluebon_np = None
                for b in trial_order:
                    if not (1 <= b <= actual_bands):
                        continue
                    data = src.read(b).astype(np.float32)
                    nz_ratio = float(np.count_nonzero(data)) / data.size
                    if data.max() > 0 and nz_ratio >= 0.01:
                        bluebon_np = data
                        chosen_idx = b
                        if b == primary_idx:
                            print(f"   ℹ️  BlueBON Red 밴드 추출: {b}번 (총 {actual_bands}밴드)")
                        else:
                            print(f"   ⚠️  Red 밴드({primary_idx}번) 손상/비어있음 → 밴드 {b}번으로 대체 (nonzero {nz_ratio*100:.1f}%)")
                            print(f"      Sentinel-2 매칭 밴드도 동일 파장대로 함께 전환됩니다.")
                        break

                if bluebon_np is None:
                    print(f"   ❌ Sentinel 매핑 가능 밴드(R/G/B)가 모두 손상. 밴드 {primary_idx}번을 그대로 사용합니다.")
                    bluebon_np = src.read(primary_idx).astype(np.float32)
                    chosen_idx = primary_idx
        except Exception as e:
            print(f"   ⚠️ 이미지 로드 실패({e}). band 1로 재시도합니다.")
            with rasterio.open(bluebon_path) as src:
                bluebon_np = src.read(1).astype(np.float32)
            chosen_idx = 1
        img_h, img_w = bluebon_np.shape

        # ── 2. 유효 픽셀 Bounding Box 계산 ──────────────────────────────
        # 기울어진 영상에는 검정(=0) 영역이 존재: non-zero 픽셀의 bbox만 사용
        mask     = bluebon_np > 0
        rows_any = np.any(mask, axis=1)
        cols_any = np.any(mask, axis=0)
        valid_rows = np.where(rows_any)[0]
        valid_cols = np.where(cols_any)[0]
        if len(valid_rows) == 0 or len(valid_cols) == 0:
            print("   ⚠️ 유효한 픽셀이 없습니다. 전체 영상 영역을 사용합니다.")
            r_min, r_max = 0, img_h - 1
            c_min, c_max = 0, img_w - 1
        else:
            r_min, r_max = int(valid_rows[0]),  int(valid_rows[-1])
            c_min, c_max = int(valid_cols[0]),  int(valid_cols[-1])

        print(f"   📐 유효 픽셀 BBox: row [{r_min}, {r_max}], col [{c_min}, {c_max}]")
        valid_h = r_max - r_min
        valid_w = c_max - c_min

        # ── 3. 타일 기반 SuperPoint 대량 추출 → spatial NMS ────────────────
        # 전략: 유효 영역을 겹치는 타일로 분할 → 각 타일에서 많은 keypoint 추출
        #       → 전체 영상 좌표로 변환 후 pool 구성 → score 기반 spatial NMS로
        #         균일하게 분포된 강인한 점 선택
        TILE_SIZE   = 512   # SuperPoint 입력 타일 크기
        TILE_STEP   = 448   # 타일 간격 (overlap = TILE_SIZE - TILE_STEP)
        KP_PER_TILE = 200   # 타일당 최대 keypoint 수 (많을수록 좋음)
        TARGET_PTS  = 300   # 최종 목표 특징점 수 (NMS 후)
        NMS_RADIUS  = 300   # spatial NMS 최소 거리 (px) – 값이 작을수록 밀도 높아짐

        # 정규화된 BlueBON 이미지 (0~1 float32)
        bluebon_norm = (bluebon_np - bluebon_np.min()) / (bluebon_np.max() - bluebon_np.min() + 1e-8)

        device    = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        extractor = SuperPoint(max_num_keypoints=KP_PER_TILE).eval().to(device)

        all_kpts   = []  # (global_x, global_y) float32
        all_scores = []  # float32

        # 타일 좌표 생성 (유효 BBox 내에서만)
        r_starts = list(range(r_min, r_max - TILE_SIZE + 1, TILE_STEP))
        if not r_starts or r_starts[-1] + TILE_SIZE < r_max:
            r_starts.append(max(r_min, r_max - TILE_SIZE))
        c_starts = list(range(c_min, c_max - TILE_SIZE + 1, TILE_STEP))
        if not c_starts or c_starts[-1] + TILE_SIZE < c_max:
            c_starts.append(max(c_min, c_max - TILE_SIZE))

        total_tiles = len(r_starts) * len(c_starts)
        print(f"   📦 타일 수: {total_tiles} ({len(r_starts)}행 × {len(c_starts)}열), 타일 크기: {TILE_SIZE}×{TILE_SIZE}, overlap: {TILE_SIZE - TILE_STEP}px")

        for r0 in r_starts:
            r1  = min(img_h, r0 + TILE_SIZE)
            for c0 in c_starts:
                c1 = min(img_w,  c0 + TILE_SIZE)
                tile = bluebon_norm[r0:r1, c0:c1]

                # 검정 픽셀 비율 > 60% 타일은 skip
                zero_ratio = np.sum(tile < 1e-4) / tile.size
                if zero_ratio >= 0.6:
                    continue

                # TILE_SIZE × TILE_SIZE 로 resize (경계 타일 대응)
                th, tw = tile.shape
                if th != TILE_SIZE or tw != TILE_SIZE:
                    tile_r = cv2.resize(tile, (TILE_SIZE, TILE_SIZE), interpolation=cv2.INTER_LINEAR)
                    scale_kx = tw / TILE_SIZE
                    scale_ky = th / TILE_SIZE
                else:
                    tile_r  = tile
                    scale_kx = 1.0
                    scale_ky = 1.0

                img_t = torch.from_numpy(tile_r).unsqueeze(0).unsqueeze(0).to(device)  # (1,1,H,W)

                try:
                    with torch.no_grad():
                        feats = extractor({'image': img_t})

                    kpts   = feats['keypoints']
                    scores = feats['keypoint_scores']

                    # squeeze batch dim if present
                    if kpts.ndim == 3:
                        kpts   = kpts[0]
                        scores = scores[0]

                    if kpts is None or len(kpts) == 0:
                        continue

                    # 타일 좌표 → 전체 영상 좌표로 변환
                    kx_global = c0 + kpts[:, 0].cpu().float() * scale_kx
                    ky_global = r0 + kpts[:, 1].cpu().float() * scale_ky

                    # 유효 픽셀인 점만 추가
                    for kx, ky, sc in zip(kx_global.tolist(), ky_global.tolist(), scores.cpu().tolist()):
                        ri, ci = int(round(ky)), int(round(kx))
                        if 0 <= ri < img_h and 0 <= ci < img_w and bluebon_np[ri, ci] > 0:
                            all_kpts.append((kx, ky))
                            all_scores.append(sc)

                except Exception:
                    continue

        print(f"   📊 전체 추출 keypoint 수 (중복 포함): {len(all_kpts)}개")

        # ── 4. Spatial NMS로 균일 분포 선택 ────────────────────────────────
        if len(all_kpts) == 0:
            selected_pts = []
        else:
            pts_t    = torch.tensor(all_kpts,   dtype=torch.float32)   # (N, 2) x,y
            scores_t = torch.tensor(all_scores, dtype=torch.float32)   # (N,)

            keep_idx = spatial_nms_with_score(pts_t, scores_t,
                                              radius=NMS_RADIUS,
                                              max_keep=TARGET_PTS)
            selected_pts = [
                (float(pts_t[i, 0]), float(pts_t[i, 1]), float(scores_t[i]))
                for i in keep_idx.tolist()
            ]

        print(f"   ✅ NMS 후 최종 특징점: {len(selected_pts)}개 (목표 {TARGET_PTS}개, NMS 반경 {NMS_RADIUS}px)")



        # ── 5. Sentinel 이미지 로드 + 양쪽 transform 읽기 ──────────────────
        # BlueBON pixel → geo(bluebon_tf) → Sentinel pixel(sentinel_tf 역변환)
        sentinel_img = None
        sentinel_tf  = None
        bluebon_tf   = None
        try:
            with rasterio.open(bluebon_path) as bs:
                bluebon_tf = bs.transform
        except Exception:
            pass
        try:
            with rasterio.open(sentinel_path) as ss:
                sentinel_tf = ss.transform
                s_arr = ss.read()                       # (C, H, W)
                # BlueBON에서 선택된 밴드(chosen_idx)에 따라 Sentinel 매핑 밴드 결정
                #   BlueBON 4(Red)→s_arr[0] (B4),  3(Green)→s_arr[1] (B3),  2(Blue)→s_arr[2] (B2)
                BB_TO_S = {4: 0, 3: 1, 2: 2}
                s_idx = BB_TO_S.get(chosen_idx, 0)
                if s_idx >= s_arr.shape[0]:
                    print(f"   ⚠️  Sentinel reference에 밴드 인덱스 {s_idx} 없음 → 첫 번째 밴드(B4)로 대체")
                    s_idx = 0
                _band_name = {0: 'B4(Red)', 1: 'B3(Green)', 2: 'B2(Blue)'}.get(s_idx, f's_arr[{s_idx}]')
                if chosen_idx == 4:
                    print(f"   ℹ️  Sentinel-2 {_band_name} 추출 (BlueBON 밴드 {chosen_idx}와 매칭)")
                else:
                    print(f"   ⚠️  Sentinel-2 {_band_name} 추출 (BlueBON 밴드 {chosen_idx} fallback에 맞춤)")
                s_gray = s_arr[s_idx].astype(np.float32)

                s_max = s_gray.max()
                sentinel_img = (s_gray / s_max * 255).astype(np.uint8) if s_max > 0 else s_gray.astype(np.uint8)
                sent_h, sent_w = sentinel_img.shape
        except Exception as se:
            print(f"   ⚠️ Sentinel 로드 실패({se}) → Sentinel 패치 없이 진행 (Step 13 매칭 불가)")



        # ── 6. CSV + 시각화 저장 ──────────────────────────────────────────
        pts_arr = np.array(selected_pts) if selected_pts else np.empty((0, 3))

        df_pts = pd.DataFrame({
            'bluebon_x': pts_arr[:, 0] if len(pts_arr) > 0 else [],
            'bluebon_y': pts_arr[:, 1] if len(pts_arr) > 0 else [],
            'score':     pts_arr[:, 2] if len(pts_arr) > 0 else [],
        })
        df_pts.to_csv(csv_all_path, index=False)

        # 시각화 (BlueBON 위에 추출된 특징점 표시)
        try:
            fig, ax = plt.subplots(figsize=(10, 10))
            ax.imshow(bluebon_norm, cmap='gray')
            if len(pts_arr) > 0:
                ax.scatter(pts_arr[:, 0], pts_arr[:, 1], s=15, c='lime', marker='+', linewidths=1.5)
            ax.set_title(f"BlueBON SuperPoint + NMS – {len(pts_arr)} points (target {TARGET_PTS}, r={NMS_RADIUS}px)")
            ax.axis("off")
            plt.savefig(os.path.join(viz_out_dir, "BlueBON_features_NMS.png"), dpi=200, bbox_inches="tight")
            plt.close(fig)
        except Exception as ve:
            print(f"   ⚠️ 시각화 저장 실패: {ve}")

        # ── 7. BlueBON + Sentinel 패치 저장 ──────────────────────────────
        # 파일명 포맷: patch{idx:03d}_Sentinel_{Sy:.2f}_{Sx:.2f}_Bluebon_{By:.2f}_{Bx:.2f}.tif
        # → Step_13_RoMaV2의 pat_sentinel regex와 일치해야 common_names 교집합이 생김
        bluebon_uint8 = (bluebon_norm * 255).astype(np.uint8)
        half_b        = B_patch_size // 2
        half_s        = S_patch_size // 2
        final_rows    = []

        for idx, (gx, gy, sc) in enumerate(selected_pts):
            cx, cy = int(round(gx)), int(round(gy))

            # ─ BlueBON 패치 ─
            r0p = max(0, cy - half_b);  r1p = min(img_h, cy + half_b)
            c0p = max(0, cx - half_b);  c1p = min(img_w, cx + half_b)
            if (r1p - r0p) < half_b or (c1p - c0p) < half_b:
                continue
            patch_b = bluebon_uint8[r0p:r1p, c0p:c1p]
            if patch_b.shape != (B_patch_size, B_patch_size):
                patch_b = cv2.resize(patch_b, (B_patch_size, B_patch_size))

            # ─ 대응 Sentinel 픽셀 좌표 계산 (지오 좌표 경유) ─
            sx, sy = gx, gy   # fallback
            if bluebon_tf is not None and sentinel_tf is not None:
                try:
                    geo_x = bluebon_tf.c  + gx * bluebon_tf.a  + gy * bluebon_tf.b
                    geo_y = bluebon_tf.f  + gx * bluebon_tf.d  + gy * bluebon_tf.e
                    inv_s = ~sentinel_tf
                    sx, sy = inv_s * (geo_x, geo_y)
                except Exception:
                    sx, sy = gx, gy

            # ─ Sentinel 패치 ─
            sxi, syi = int(round(sx)), int(round(sy))
            if sentinel_img is not None and 0 <= syi < sent_h and 0 <= sxi < sent_w:
                rs0 = max(0, syi - half_s);  rs1 = min(sent_h, syi + half_s)
                cs0 = max(0, sxi - half_s);  cs1 = min(sent_w, sxi + half_s)
                if (rs1 - rs0) >= half_s and (cs1 - cs0) >= half_s:
                    patch_s = sentinel_img[rs0:rs1, cs0:cs1]
                    if patch_s.shape != (S_patch_size, S_patch_size):
                        patch_s = cv2.resize(patch_s, (S_patch_size, S_patch_size))
                else:
                    patch_s = None
            else:
                patch_s = None

            # ─ 파일명 (Step_13_RoMaV2 pat_sentinel 패턴과 일치) ─
            base    = f"patch{idx:03d}_Sentinel_{sy:.2f}_{sx:.2f}_Bluebon_{gy:.2f}_{gx:.2f}.tif"
            fname_b = os.path.join(B_dir, base)
            fname_s = os.path.join(S_dir, base)

            # BlueBON 패치 저장
            save_image(torch.from_numpy(patch_b.astype(np.float32) / 255.0).unsqueeze(0), fname_b)

            # Sentinel 패치 저장 (없으면 빈 패치로 대체해 파일명 교집합 유지)
            if patch_s is not None:
                save_image(torch.from_numpy(patch_s.astype(np.float32) / 255.0).unsqueeze(0), fname_s)
            else:
                # 빈(Black) 패치로라도 파일을 만들어야 common_names 교집합이 생김
                dummy = torch.zeros(1, S_patch_size, S_patch_size)
                save_image(dummy, fname_s)

            final_rows.append({
                'patch_idx':          idx,
                'bluebon_x':          gx,
                'bluebon_y':          gy,
                'sentinel_x':         sx,
                'sentinel_y':         sy,
                'score':              sc,
                'bluebon_patch_path': fname_b,
                'sentinel_patch_path': fname_s,
                'B_patch_size_roi':   B_patch_size_roi,
                'S_patch_size_roi':   S_patch_size_roi,
            })

        # CSV 최종 저장
        pd.DataFrame(final_rows).to_csv(csv_final_path, index=False)
        pd.DataFrame(final_rows).to_csv(csv_nms_path,   index=False)
        print(f"📄 CSV 저장: {csv_nms_path}")
        print(f"   ✅ 패치 저장 완료: {len(final_rows)}개 → B_dir={B_dir}, S_dir={S_dir}")

        return {
            'B_dir':       B_dir,
            'S_dir':       S_dir,
            'num_patches': len(final_rows),
            'csv_all':     csv_all_path,
            'csv_nms':     csv_nms_path,
            'csv_final':   csv_final_path,
        }



def extract_paired_patches(
        Bluebon,  # (C_b, H_b, W_b)
        Sentinel,  # (C_s, H_s, W_s)
        pts0_hr,  # (N, 2)  x,y on Bluebon
        pts1_hr,  # (N, 2)  x,y on Sentinel
        B_patch_size=128,
        S_patch_size=96,
        thr=0.01,  # 검은 픽셀 비율 임계값
        eps=1e-6,  # 검은 픽셀 판정 허용오차
        padding_mode="border",
        align_corners=True,
        black_mask_source="bluebon",
):
    # ------- Bluebon 템플릿 -------
    device_b = Bluebon.device
    C_b, H_b, W_b = Bluebon.shape
    N_b = pts0_hr.shape[0]

    yy_b, xx_b = torch.meshgrid(
        torch.arange(B_patch_size, device=device_b, dtype=torch.float32),
        torch.arange(B_patch_size, device=device_b, dtype=torch.float32),
        indexing='ij'
    )
    cx_b = (B_patch_size - 1) / 2.0
    cy_b = (B_patch_size - 1) / 2.0
    off_x_b = xx_b - cx_b
    off_y_b = yy_b - cy_b

    grid_x0 = pts0_hr[:, 0].view(N_b, 1, 1).to(device_b) + off_x_b
    grid_y0 = pts0_hr[:, 1].view(N_b, 1, 1).to(device_b) + off_y_b
    gx0 = 2.0 * (grid_x0 / (W_b - 1)) - 1.0
    gy0 = 2.0 * (grid_y0 / (H_b - 1)) - 1.0
    grid0 = torch.stack([gx0, gy0], dim=-1)

    Bluebon_patches = F.grid_sample(
        Bluebon.unsqueeze(0).expand(N_b, -1, -1, -1),
        grid0, mode='bilinear', padding_mode=padding_mode, align_corners=align_corners
    )

    # ------- Sentinel 템플릿 -------
    device_s = Sentinel.device
    C_s, H_s, W_s = Sentinel.shape
    N_s = pts1_hr.shape[0]
    assert N_b == N_s, "pts0_hr와 pts1_hr의 N이 다릅니다."

    yy_s, xx_s = torch.meshgrid(
        torch.arange(S_patch_size, device=device_s, dtype=torch.float32),
        torch.arange(S_patch_size, device=device_s, dtype=torch.float32),
        indexing='ij'
    )
    cx_s = (S_patch_size - 1) / 2.0
    cy_s = (S_patch_size - 1) / 2.0
    off_x_s = xx_s - cx_s
    off_y_s = yy_s - cy_s

    grid_x1 = pts1_hr[:, 0].view(N_s, 1, 1).to(device_s) + off_x_s
    grid_y1 = pts1_hr[:, 1].view(N_s, 1, 1).to(device_s) + off_y_s
    gx1 = 2.0 * (grid_x1 / (W_s - 1)) - 1.0
    gy1 = 2.0 * (grid_y1 / (H_s - 1)) - 1.0
    grid1 = torch.stack([gx1, gy1], dim=-1)  # (N_s, S, S, 2)

    Sentinel_patches = F.grid_sample(
        Sentinel.unsqueeze(0).expand(N_s, -1, -1, -1),
        grid1, mode='bilinear', padding_mode=padding_mode, align_corners=align_corners
    )  # (N_s, C_s, S_patch_size, S_patch_size)

    # ------- 검은 부분 제외 -------
    assert Bluebon_patches.shape[0] == Sentinel_patches.shape[0] == N_b

    def black_fraction(patches):
        sum_ch = patches.abs().sum(dim=1)  # (N, S, S)
        black_pix = (sum_ch <= eps)  # (N, S, S)
        return black_pix.float().mean(dim=(1, 2))  # (N,)

    frac_b = black_fraction(Bluebon_patches)
    frac_s = black_fraction(Sentinel_patches)

    if black_mask_source == "bluebon":
        keep = frac_b < thr
    elif black_mask_source == "sentinel":
        keep = frac_s < thr
    elif black_mask_source == "either":
        keep = (frac_b < thr) | (frac_s < thr)
    elif black_mask_source == "both":
        keep = (frac_b < thr) & (frac_s < thr)
    else:
        raise ValueError("black_mask_source must be one of ['bluebon','sentinel','either','both'].")

    Bluebon_patches = Bluebon_patches[keep]
    Sentinel_patches = Sentinel_patches[keep]
    pts0_keep = pts0_hr[keep]
    pts1_keep = pts1_hr[keep]

    return Bluebon_patches, Sentinel_patches, pts0_keep, pts1_keep, keep


def show_keypoints(image_tensor: torch.Tensor,
                   keypoints: torch.Tensor,
                   title="Keypoints with 128x128 boxes",
                   patch_size=128):
    # Gray 변환
    if image_tensor.ndim == 3 and image_tensor.shape[0] == 3:
        gray = image_tensor.mean(dim=0).detach().cpu().numpy()
    elif image_tensor.ndim == 3 and image_tensor.shape[0] == 1:
        gray = image_tensor[0].detach().cpu().numpy()
    else:
        raise ValueError("지원 shape: (3,H,W) 또는 (1,H,W)")

    gray = np.clip(gray, 0, 1)  # 시각화용 [0,1]

    # keypoints numpy 변환
    kpts = keypoints.detach().cpu().numpy() if torch.is_tensor(keypoints) else keypoints

    half = patch_size // 2

    # 시각화
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(gray, cmap='gray')

    for (x, y) in kpts:
        # 점
        ax.scatter([x], [y], s=15, c='lime', marker='+', linewidths=1.5)
        rect = patches.Rectangle((x - half, y - half),
                                 patch_size, patch_size,
                                 linewidth=1.5,
                                 facecolor='none')
        ax.add_patch(rect)

    ax.set_title(f"{title} (N={len(kpts)})")
    ax.axis("off")
    plt.show()


def spatial_nms_with_score(pts, scores, radius=500, max_keep=None):
    pts = pts.to(torch.float32)
    scores = scores.to(torch.float32)

    N = pts.shape[0]
    if N == 0:
        return torch.empty(0, dtype=torch.long, device=pts.device)

    order = torch.argsort(scores, descending=True)  # 높은 점수부터 순회
    keep = []
    taken = torch.zeros(N, dtype=torch.bool, device=pts.device)

    for idx in order:
        if taken[idx]:
            continue
        keep.append(idx.item())

        d = torch.norm(pts - pts[idx], dim=1)
        taken |= (d < radius)

        if max_keep is not None and len(keep) >= max_keep:
            break

    return torch.tensor(keep, dtype=torch.long, device=pts.device)


def extract_and_match_patch(ref_img: np.ndarray, tar_img: np.ndarray,
                            ref_center: Tuple[int, int], tar_center: Tuple[int, int],
                            patch_size: int,
                            extractor, matcher, device) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    half_size = patch_size // 2

    # Reference patch 추출
    ref_x, ref_y = ref_center
    ref_y1 = max(0, ref_y - half_size)
    ref_y2 = min(ref_img.shape[0], ref_y + half_size + 1)
    ref_x1 = max(0, ref_x - half_size)
    ref_x2 = min(ref_img.shape[1], ref_x + half_size + 1)

    ref_patch = ref_img[ref_y1:ref_y2, ref_x1:ref_x2]

    # Target patch 추출
    tar_x, tar_y = tar_center
    tar_y1 = max(0, tar_y - half_size)
    tar_y2 = min(tar_img.shape[0], tar_y + half_size + 1)
    tar_x1 = max(0, tar_x - half_size)
    tar_x2 = min(tar_img.shape[1], tar_x + half_size + 1)

    tar_patch = tar_img[tar_y1:tar_y2, tar_x1:tar_x2]

    # Patch가 너무 작으면 스킵
    if ref_patch.shape[0] < 10 or ref_patch.shape[1] < 10 or \
            tar_patch.shape[0] < 10 or tar_patch.shape[1] < 10:
        return None, None

    # CLAHE 전처리
    ref_patch = apply_clahe_preprocessing(ref_patch)
    tar_patch = apply_clahe_preprocessing(tar_patch)

    # Torch 텐서 변환
    ref_tensor = torch.from_numpy(ref_patch)[None][None].to(device)
    tar_tensor = torch.from_numpy(tar_patch)[None][None].to(device)

    # 특징점 추출 및 매칭
    try:
        with torch.no_grad():
            feats0 = extractor.extract(ref_tensor)
            feats1 = extractor.extract(tar_tensor)
            matches01 = matcher({'image0': feats0, 'image1': feats1})
            feats0, feats1, matches01 = [rbd(x) for x in [feats0, feats1, matches01]]

        # 매칭 결과 추출
        if 'matches0' in matches01:
            matches = matches01['matches0']
            valid = matches > -1
            mkpts0 = feats0['keypoints'][valid].cpu().numpy()
            mkpts1 = feats1['keypoints'][matches[valid]].cpu().numpy()
        elif 'matches' in matches01:
            matches = matches01['matches']
            if len(matches.shape) == 2:
                valid_mask = (matches[:, 0] >= 0) & (matches[:, 1] >= 0)
                matches = matches[valid_mask]
                mkpts0 = feats0['keypoints'][matches[:, 0]].cpu().numpy()
                mkpts1 = feats1['keypoints'][matches[:, 1]].cpu().numpy()
            else:
                return None, None
        else:
            return None, None

        if len(mkpts0) == 0:
            return None, None

        # 가장 중심에 가까운 매칭점 선택 (patch 중심에서 가장 가까운 점)
        patch_center = np.array([ref_patch.shape[1] / 2, ref_patch.shape[0] / 2])
        distances = np.linalg.norm(mkpts0 - patch_center, axis=1)
        best_idx = np.argmin(distances)

        # 전체 영상 좌표로 변환
        best_ref_pt = mkpts0[best_idx] + np.array([ref_x1, ref_y1])
        best_tar_pt = mkpts1[best_idx] + np.array([tar_x1, tar_y1])

        return best_ref_pt, best_tar_pt

    except Exception as e:
        return None, None