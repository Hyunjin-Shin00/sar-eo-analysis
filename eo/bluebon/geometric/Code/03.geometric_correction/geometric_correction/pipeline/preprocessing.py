"""
Stage 1 Preprocessing Module

This module contains the preprocessing steps (Step 1-5) for geometric correction:
- Step 1: Input validation and metadata extraction
- Step 2: CRS unification
- Step 3: Target extent cropping
- Step 4: Resolution normalization
- Step 5: Low-resolution image preparation
"""

import os
import shutil
import subprocess
from typing import Dict, Optional

import rasterio
import rasterio.warp
from rasterio.enums import Resampling
import numpy as np
import cv2
from osgeo import gdal, osr

def step11_5_estimate_depth_anything(initial_corrected_path: str, output_dir: str,
                                     tile_size: int = 768, overlap: int = 128) -> Optional[str]:
    """
    STEP 11-5: 초기 기하보정된 TARGET 영상에 대해 DepthAnything V2 Large (HF)로 깊이 추정.
    출력: output_dir/step11_5_depth/{depth.tif, depth_colored.png}
    """
    print("\n" + "="*80)
    print("STEP 11-5: DepthAnything V2 Large로 깊이 추정")
    print("="*80)
    try:
        from transformers import pipeline
    except Exception as e:
        print(f"   ❌ transformers 로드 실패: {e}")
        return None

    if not os.path.exists(initial_corrected_path):
        print(f"   ❌ 입력 영상 없음: {initial_corrected_path}")
        return None

    # 입력 로드 및 RGB 8bit 확보
    with rasterio.open(initial_corrected_path) as src:
        arr = np.transpose(src.read(), (1, 2, 0))
        profile = src.profile.copy()

    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=2)
    if arr.shape[2] < 3:
        arr = np.repeat(arr[:, :, :1], 3, axis=2)
    rgb = arr[:, :, :3]

    def percentile_stretch_u16_to_u8(x: np.ndarray, p_low: float = 0.5, p_high: float = 99.5) -> np.ndarray:
        x = x.astype(np.float32)
        out = np.zeros_like(x, dtype=np.uint8)
        if x.ndim == 3 and x.shape[2] == 3:
            for c in range(3):
                ch = x[:, :, c]
                # 유효 픽셀: 0 초과만 사용 (배경 0 제외)
                valid = ch > 0
                if not np.any(valid):
                    continue
                lo = np.percentile(ch[valid], p_low)
                hi = np.percentile(ch[valid], p_high)
                if hi <= lo:
                    lo, hi = float(ch.min()), float(ch.max())
                y = (ch - lo) / (hi - lo + 1e-6)
                y = np.clip(y, 0.0, 1.0) * 255.0
                out[:, :, c] = y.astype(np.uint8)
        else:
            valid = x > 0
            if np.any(valid):
                lo = np.percentile(x[valid], p_low)
                hi = np.percentile(x[valid], p_high)
                if hi <= lo:
                    lo, hi = float(x.min()), float(x.max())
                y = (x - lo) / (hi - lo + 1e-6)
                y = np.clip(y, 0.0, 1.0) * 255.0
                out = y.astype(np.uint8)
        return out

    if rgb.dtype == np.uint16:
        # 0을 제외한 유효 픽셀 기준 0~100% 전체 구간 스트레칭
        rgb_u8 = percentile_stretch_u16_to_u8(rgb, 0.0, 100.0)
    else:
        rgb_u8 = rgb.astype(np.uint8)

    print("   🤖 HF 파이프라인 로딩: Depth-Anything-V2-Large-hf")
    try:
        pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Large-hf", device="cpu")
    except Exception as e:
        print(f"   ❌ HF 모델 로드 실패: {e}")
        return None

    from PIL import Image

    # 기본 내부 처리 크기로 추론 (518x518)
    pil_img = Image.fromarray(rgb_u8)
    result = pipe(pil_img)
    depth = np.array(result["depth"]).astype(np.float32)
    dmin, dmax = float(depth.min()), float(depth.max())
    depth01 = (depth - dmin) / (dmax - dmin + 1e-8)
    depth01 = 1.0 - depth01

    out_dir = os.path.join(output_dir, "step11_5_depth")
    os.makedirs(out_dir, exist_ok=True)
    out_tif = os.path.join(out_dir, "target_depth_map.tif")
    out_png = os.path.join(out_dir, "target_depth_map_gray.png")

    profile.update({"dtype": "uint16", "count": 1, "nodata": 0})
    with rasterio.open(out_tif, 'w', **profile) as dst:
        dst.write((np.clip(depth01, 0.0, 1.0) * 65535).astype(np.uint16), 1)

    depth_u8 = (np.clip(depth01, 0.0, 1.0) * 255).astype(np.uint8)
    cv2.imwrite(out_png, depth_u8)
    print(f"   💾 저장(Grayscale, Inverted): {out_tif}")
    print(f"   💾 저장(Grayscale PNG): {out_png}")
    return out_tif

# --- DEM crop helper (mask-based) ---
def crop_dem_with_mask(dem_path: str, mask_path: str, output_path: str) -> str:
    """
    마스크(0/255)와 겹치는 DEM 영역만 남기고 저장.
    - mask가 PNG이면 지리정보가 없으므로 DEM 크기에 맞춰 최근접 리사이즈 후 적용
    - mask가 GeoTIFF이면 DEM 그리드로 최근접 리샘플 또는 크기 일치 시 직접 적용
    """
    try:
        with rasterio.open(dem_path) as src:
            dem = src.read(1)
            profile = src.profile.copy()
            dem_h, dem_w = dem.shape
            dem_transform = src.transform
            dem_crs = src.crs

        # 마스크 로드
        if mask_path.lower().endswith('.png'):
            m = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            if m is None:
                print(f"   ⚠️ 마스크 PNG 읽기 실패: {mask_path}")
                return dem_path
            if m.shape != (dem_h, dem_w):
                m = cv2.resize(m, (dem_w, dem_h), interpolation=cv2.INTER_NEAREST)
        else:
            with rasterio.open(mask_path) as msrc:
                m = msrc.read(1)
                m_transform = msrc.transform
                m_crs = msrc.crs
            # 마스크를 DEM 그리드로 재투영 (최근접)
            try:
                from rasterio.warp import reproject, Resampling
                dst_mask = np.zeros((dem_h, dem_w), dtype=np.uint8)
                reproject(
                    source=(m > 0).astype(np.uint8),
                    destination=dst_mask,
                    src_transform=m_transform,
                    src_crs=m_crs,
                    dst_transform=dem_transform,
                    dst_crs=dem_crs,
                    resampling=Resampling.nearest
                )
                m = (dst_mask > 0).astype(np.uint8) * 255
            except Exception as _:
                # 실패 시 크기만 일치시키기
                if m.shape != (dem_h, dem_w):
                    m = cv2.resize((m > 0).astype(np.uint8) * 255, (dem_w, dem_h), interpolation=cv2.INTER_NEAREST)

        mask_bool = m > 0

        # 값 마스킹: float32 + NaN으로 확실히 배경 제거
        dem_masked = dem.astype(np.float32)
        dem_masked[~mask_bool] = np.nan
        dem_nodata = np.nan

        # 저장
        profile.update({'dtype': 'float32', 'count': 1, 'nodata': dem_nodata})
        out_dir = os.path.dirname(output_path)
        os.makedirs(out_dir, exist_ok=True)
        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(dem_masked, 1)
            # 데이터셋 마스크 밴드 기록(0/255)
            dst.write_mask((mask_bool.astype(np.uint8) * 255))
        print(f"   💾 DEM 마스크 적용 저장: {output_path}")
        return output_path
    except Exception as e:
        print(f"   ❌ crop_dem_with_mask 실패: {e}")
        return dem_path


def step11_6_crop_dem_with_initial_mask(initial_corrected_path: str,
                                         initial_corrected_mask_path: str,
                                         dem_cropped_path: str,
                                         output_dir: str) -> Optional[str]:
    """
    STEP 11-6: 초기 기하보정에서 생성한 마스크로 DEM을 crop (겹치는 영역만).
    출력: OUTPUT_DIR/step11_6_dem/dem_masked.tif
    """
    try:
        if not (os.path.exists(initial_corrected_path) and os.path.exists(initial_corrected_mask_path) and os.path.exists(dem_cropped_path)):
            print("   ⚠️ 입력 경로가 없습니다")
            return None
        out_dir = os.path.join(output_dir, 'step11_6_dem')
        os.makedirs(out_dir, exist_ok=True)
        out_dem = os.path.join(out_dir, 'dem_masked.tif')
        # 1) 초기 기하보정 영상의 그리드/CRS를 타겟으로 사용
        with rasterio.open(initial_corrected_path) as isrc:
            tgt_h, tgt_w = isrc.height, isrc.width
            tgt_transform = isrc.transform
            tgt_crs = isrc.crs

        # 2) DEM을 타겟 그리드로 재투영
        with rasterio.open(dem_cropped_path) as dsrc:
            dem = dsrc.read(1)
            dem_src_transform = dsrc.transform
            dem_src_crs = dsrc.crs
            dem_dtype = 'float32'
        from rasterio.warp import reproject, Resampling
        dem_reproj = np.zeros((tgt_h, tgt_w), dtype=np.float32)
        reproject(
            source=dem.astype(np.float32),
            destination=dem_reproj,
            src_transform=dem_src_transform,
            src_crs=dem_src_crs,
            dst_transform=tgt_transform,
            dst_crs=tgt_crs,
            resampling=Resampling.bilinear
        )

        # 3) 마스크 로드(0/255) → 타겟 크기에 최근접 맞춤
        if initial_corrected_mask_path.lower().endswith('.png'):
            m = cv2.imread(initial_corrected_mask_path, cv2.IMREAD_GRAYSCALE)
            if m is None:
                print(f"   ⚠️ 마스크 PNG 읽기 실패: {initial_corrected_mask_path}")
                return None
            if m.shape != (tgt_h, tgt_w):
                m = cv2.resize(m, (tgt_w, tgt_h), interpolation=cv2.INTER_NEAREST)
        else:
            with rasterio.open(initial_corrected_mask_path) as msrc:
                m = msrc.read(1)
            if m.shape != (tgt_h, tgt_w):
                m = cv2.resize((m > 0).astype(np.uint8) * 255, (tgt_w, tgt_h), interpolation=cv2.INTER_NEAREST)
        mask_bool = m > 0

        # 4) 마스크 밖은 NaN (float32) + 데이터셋 마스크 기록
        dem_masked = dem_reproj
        dem_masked[~mask_bool] = np.nan
        profile = {
            'driver': 'GTiff',
            'height': tgt_h,
            'width': tgt_w,
            'count': 1,
            'dtype': 'float32',
            'crs': tgt_crs,
            'transform': tgt_transform,
            'nodata': np.nan
        }
        with rasterio.open(out_dem, 'w', **profile) as dst:
            dst.write(dem_masked.astype(np.float32), 1)
            dst.write_mask((mask_bool.astype(np.uint8) * 255))
        print(f"   💾 DEM(마스크 기준 그리드) 저장: {out_dem}")
        return out_dem
    except Exception as e:
        print(f"   ❌ STEP 11-6 (DEM crop) 실패: {e}")
        return None

def step11_7_scale_depth_by_dem(depth_tif_path: str, dem_masked_path: str) -> Optional[str]:
    """
    STEP 11-7: dem_masked의 min/max로 depth_tif를 물리 높이 범위로 스케일링하여 저장.
    저장: 동일 폴더에 *_scaled.tif
    """
    try:
        if not (os.path.exists(depth_tif_path) and os.path.exists(dem_masked_path)):
            print("   ⚠️ 입력 파일 없음 (11-7)")
            return None
        with rasterio.open(dem_masked_path) as src:
            dem = src.read(1).astype(np.float32)
            dem_transform = src.transform
            dem_crs = src.crs
        # 유효 영역: finite & not NaN
        valid_dem = np.isfinite(dem)
        if not np.any(valid_dem):
            print("   ⚠️ DEM 마스크 유효 영역 없음")
            return None
        dmin, dmax = float(dem[valid_dem].min()), float(dem[valid_dem].max())

        with rasterio.open(depth_tif_path) as src:
            depth = src.read(1).astype(np.float32)
            profile = src.profile.copy()
            depth_transform = src.transform
            depth_crs = src.crs
        # depth는 0..65535 또는 0..1 가정
        if depth.max() > 1.5:
            depth01 = np.clip(depth / 65535.0, 0.0, 1.0)
        else:
            depth01 = np.clip(depth, 0.0, 1.0)
        # 마스크 밖(depth==0) 제외
        depth_valid = depth01 > 0

        # 그리드 정렬 확인 후 필요 시 depth를 dem 그리드로 리샘플
        if (profile.get('transform') != dem_transform) or (depth.shape != dem.shape) or (depth_crs != dem_crs):
            try:
                from rasterio.warp import reproject, Resampling
                depth01_re = np.zeros_like(dem, dtype=np.float32)
                reproject(
                    source=depth01,
                    destination=depth01_re,
                    src_transform=depth_transform,
                    src_crs=depth_crs,
                    dst_transform=dem_transform,
                    dst_crs=dem_crs,
                    resampling=Resampling.bilinear
                )
                depth01 = np.clip(depth01_re, 0.0, 1.0)
                depth_valid = depth01 > 0
            except Exception as e:
                print(f"   ⚠️ depth 리샘플 실패: {e}")

        # 최종 유효 마스크: DEM 유효 & depth 유효 교집합
        mask_final = valid_dem & depth_valid

        # 유효영역 내에서만 재정규화(로컬 대비 살리기)
        depth01_scaled = np.zeros_like(depth01, dtype=np.float32)
        if np.any(mask_final):
            dv_min, dv_max = float(depth01[mask_final].min()), float(depth01[mask_final].max())
            depth01_n = np.zeros_like(depth01, dtype=np.float32)
            depth01_n[mask_final] = (depth01[mask_final] - dv_min) / (dv_max - dv_min + 1e-8)
            depth01_scaled[mask_final] = depth01_n[mask_final] * (dmax - dmin) + dmin
        else:
            print("   ⚠️ Depth 유효 영역이 없습니다")

        # 마스크 밖은 NaN
        scaled = np.full_like(depth01_scaled, np.nan, dtype=np.float32)
        scaled[mask_final] = depth01_scaled[mask_final]
        
        # 스케일링 후 최소값 미만 제거 (DEM 최소값보다 낮거나 같은 값은 NaN으로 설정)
        # 부동소수점 정밀도 고려하여 약간의 여유를 둠
        scaled[scaled <= dmin + 1e-6] = np.nan
        
        out_path = depth_tif_path.replace('.tif', '_scaled.tif')
        
        # DEM 그리드 기준으로 profile 업데이트
        # nodata 값을 명시적으로 설정 (QGIS 호환성)
        nodata_value = -9999.0
        profile.update({
            'dtype': 'float32', 
            'nodata': nodata_value,
            'height': dem.shape[0],
            'width': dem.shape[1],
            'transform': dem_transform,
            'crs': dem_crs
        })
        
        # NaN을 명시적 nodata 값으로 변경
        scaled[np.isnan(scaled)] = nodata_value
        
        with rasterio.open(out_path, 'w', **profile) as dst:
            dst.write(scaled.astype(np.float32), 1)
            # 마스크 밴드 기록
            dst.write_mask((mask_final.astype(np.uint8) * 255))
        print(f"   💾 Depth 스케일링 저장: {out_path} (범위 {dmin:.2f}~{dmax:.2f})")
        return out_path
    except Exception as e:
        print(f"   ❌ STEP 11-7 실패: {e}")
        return None


def run_step11_5_pipeline(output_dir: str, output_dir2: str, target_path: str, initial_correction_method: str) -> None:
    """
    STEP 11-5 전체 파이프라인 실행:
      1) 초기 기하보정 영상(티프) 경로를 찾아 DepthAnything 수행
      2) 초기 마스크로 DEM crop (step11_6)
      3) DEM min/max로 depth 스케일링 (step11_7)
      4) 원본 TARGET에도 DepthAnything 추가 실행(실험)
    """
    try:
        print("\n" + "="*80)
        print("STEP 11-5: DepthAnything V2 Large로 깊이 추정")
        print("="*80)
        init_tif = os.path.join(output_dir, "step10_initial_correction",
                                f"target_initial_{initial_correction_method.upper()}_corrected.tif")
        init_tif_alt = os.path.join(output_dir, "step10_initial_correction",
                                    f"target_initial_{initial_correction_method.lower()}_corrected.tif")
        init_path = init_tif if os.path.exists(init_tif) else (init_tif_alt if os.path.exists(init_tif_alt) else None)
        if init_path is None:
            print("   ⚠️ 초기 기하보정 영상이 없어 STEP 11-5 건너뜀")
            return

        # 11-5-1: 초기 기하보정 영상에 대해 추정
        _ = step11_5_estimate_depth_anything(init_path, output_dir2)

        # 11-5-2: 원본 TARGET 영상에 대해서도 추정(실험)
        if os.path.exists(target_path):
            print("   🔁 원본 TARGET 영상에도 DepthAnything 적용")
            _ = step11_5_estimate_depth_anything(target_path, os.path.join(output_dir2, "raw_target"))

        # STEP 11-6: 마스크로 DEM crop
        print("\n" + "="*80)
        print("STEP 11-6: 마스크로 DEM crop")
        print("="*80)
        dem_cropped_path2 = os.path.join(output_dir2, "step03_cropped", "dem_cropped.tif")
        init_mask_png = init_path.replace('.tif', '_mask.png')
        dem_masked_path = None
        if os.path.exists(dem_cropped_path2) and os.path.exists(init_mask_png):
            dem_masked_path = step11_6_crop_dem_with_initial_mask(init_path, init_mask_png, dem_cropped_path2, output_dir2)
        else:
            print("   ⚠️ DEM 또는 마스크가 없어 STEP 11-6 건너뜀")

        # STEP 11-7: DEM min/max로 11-5 depth 스케일링
        print("\n" + "="*80)
        print("STEP 11-7: DEM min/max 기반 Depth 스케일링")
        print("="*80)
        depth11_5_tif = os.path.join(output_dir2, "step11_5_depth", "target_depth_map.tif")
        if dem_masked_path and os.path.exists(depth11_5_tif):
            _ = step11_7_scale_depth_by_dem(depth11_5_tif, dem_masked_path)
        else:
            print("   ⚠️ 11-5 결과 또는 dem_masked 없음, STEP 11-7 건너뜀")
    except Exception as e:
        print(f"   ⚠️ STEP 11-5 파이프라인 실패: {e}")
        return

# 전역 변수 정의
TARGET_CENTER_LAT = None
TARGET_CENTER_LON = None
TARGET_RESOLUTION = None

def set_target_info(lat: float, lon: float, resolution: float):
    """TARGET 이미지 정보를 전역 변수로 설정
    0.5m 해상도는 자동으로 2.0m로 변경
    """
    global TARGET_CENTER_LAT, TARGET_CENTER_LON, TARGET_RESOLUTION
    TARGET_CENTER_LAT = lat
    TARGET_CENTER_LON = lon
    # 0.5m 해상도면 2.0m로 자동 변경
    if abs(resolution - 0.5) < 0.1:
        print(f"   ℹ️  TARGET 해상도 {resolution}m 감지 → 2.0m로 자동 변경")
        TARGET_RESOLUTION = 2.0
    else:
        TARGET_RESOLUTION = resolution


def validate_inputs(reference_path: str, target_path: str, dem_path: str, geoid_path: str, output_dir: str) -> dict:
    """
    STEP 1: 입력 파일 검증 및 메타데이터 추출
    
    Input:
        reference_path (str): Reference 이미지 파일 경로
        target_path (str): Target 이미지 파일 경로  
        dem_path (str): DEM 파일 경로
    
    Output:
        dict: 각 파일의 메타데이터 정보 (CRS, bounds, transform, size 등)
    
    Algorithm:
        - 파일 존재 여부 확인
        - rasterio를 사용한 메타데이터 추출
        - 좌표계, 경계, 변환행렬, 크기 정보 수집
    """
    print("\n" + "="*80)
    print("STEP 1: 입력 파일 검증 및 메타데이터 추출")
    print("="*80)
    
    metadata = {}
    
    # Reference 이미지 검증
    print(f"📂 Reference Image: {reference_path}")
    if not os.path.exists(reference_path):
        raise FileNotFoundError(f"Reference image not found: {reference_path}")
    
    with rasterio.open(reference_path) as src:
        metadata['reference'] = {
            'path': reference_path,
            'crs': src.crs.to_string() if src.crs else None,
            'bounds': src.bounds,
            'transform': src.transform,
            'width': src.width,
            'height': src.height,
            'count': src.count,
            'dtype': src.dtypes[0],
            'resolution': (abs(src.transform.a), abs(src.transform.e))
        }
        print(f"   ✅ CRS: {metadata['reference']['crs']}")
        print(f"   ✅ Size: {src.width} x {src.height}")
        print(f"   ✅ Resolution: {metadata['reference']['resolution'][0]:.2f} x {metadata['reference']['resolution'][1]:.2f} m")
    
    # Target 이미지 검증
    print(f"\n📂 Target Image: {target_path}")
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Target image not found: {target_path}")
    
    with rasterio.open(target_path) as src:
        metadata['target'] = {
            'path': target_path,
            'crs': src.crs.to_string() if src.crs else None,
            'bounds': src.bounds if src.crs else None,
            'transform': src.transform if src.crs else None,
            'width': src.width,
            'height': src.height,
            'count': src.count,
            'dtype': src.dtypes[0],
            'resolution': (abs(src.transform.a), abs(src.transform.e)) if src.transform else None
        }
        print(f"   ✅ CRS: {metadata['target']['crs']}")
        print(f"   ✅ Size: {src.width} x {src.height}")
        if metadata['target']['resolution']:
            print(f"   ✅ Resolution: {metadata['target']['resolution'][0]:.2f} x {metadata['target']['resolution'][1]:.2f} m")
    
    # DEM 검증
    print(f"\n📂 DEM: {dem_path}")
    if not os.path.exists(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")
    
    with rasterio.open(dem_path) as src:
        metadata['dem'] = {
            'path': dem_path,
            'crs': src.crs.to_string() if src.crs else None,
            'bounds': src.bounds,
            'transform': src.transform,
            'width': src.width,
            'height': src.height,
            'dtype': src.dtypes[0],
            'resolution': (abs(src.transform.a), abs(src.transform.e))
        }
        print(f"   ✅ CRS: {metadata['dem']['crs']}")
        print(f"   ✅ Size: {src.width} x {src.height}")
        print(f"   ✅ Resolution: {metadata['dem']['resolution'][0]:.2f} x {metadata['dem']['resolution'][1]:.2f} m")
    
    # Geoid 검증
    print(f"\n📂 Geoid: {geoid_path}")
    if not os.path.exists(geoid_path):
        raise FileNotFoundError(f"Geoid not found: {geoid_path}")
    
    with rasterio.open(geoid_path) as src:
        metadata['geoid'] = {
            'path': geoid_path,
            'crs': src.crs.to_string() if src.crs else None,
            'bounds': src.bounds,
            'transform': src.transform,
            'width': src.width,
            'height': src.height,
            'dtype': src.dtypes[0],
            'resolution': (abs(src.transform.a), abs(src.transform.e))
        }
        print(f"   ✅ CRS: {metadata['geoid']['crs']}")
        print(f"   ✅ Size: {src.width} x {src.height}")
        print(f"   ✅ Resolution: {metadata['geoid']['resolution'][0]:.2f} x {metadata['geoid']['resolution'][1]:.2f} m")
    
    print("\n✅ STEP 1 완료: 모든 입력 파일이 유효합니다.")
    return metadata


def unify_crs(metadata: dict, output_dir: str, sub_dir: Optional[str] = None, experiment_set: Optional[str] = None) -> dict:
    """
    STEP 2: 좌표계 통일 (REFERENCE 기준 또는 강제 통일)
    
    Input:
        metadata (dict): 입력 파일들의 메타데이터 정보
        output_dir (str): 출력 디렉토리 경로
        sub_dir (str, optional): 하위 디렉토리명
        experiment_set (str, optional): 실험 셋 이름 (Jamsil_cas, Iksan_cas의 경우 32652로 강제 통일)
    
    Output:
        dict: 좌표계가 통일된 파일 경로들 (reference, target, dem)
    
    Algorithm:
        - Jamsil_cas, Iksan_cas의 경우 EPSG:32652로 강제 통일
        - 그 외의 경우 Reference 이미지의 CRS를 기준으로 설정
        - rasterio.warp.reproject를 사용한 좌표계 변환
        - Target과 DEM을 기준 좌표계로 변환
        - 변환된 파일들을 새 위치에 저장
    """
    print("\n" + "="*80)
    print("STEP 2: 좌표계 통일 (REFERENCE 기준)")
    print("="*80)
    
    # Jamsil_cas, Iksan_cas의 경우 EPSG:32652로 강제 통일
    if experiment_set and experiment_set in ['Jamsil_cas', 'Iksan_cas']:
        target_crs_str = 'EPSG:32652'
        from rasterio.crs import CRS
        ref_crs = CRS.from_string(target_crs_str)
        print(f"🎯 기준 좌표계 (강제 통일): {ref_crs}")
        print(f"   ⚠️ {experiment_set}의 경우 EPSG:32652로 강제 통일합니다.")
    else:
        ref_crs = metadata['reference']['crs']
        print(f"🎯 기준 좌표계: {ref_crs}")

    unified_dir = os.path.join(output_dir, sub_dir) if sub_dir else output_dir
    os.makedirs(unified_dir, exist_ok=True)
    
    # Jamsil_cas, Iksan_cas의 경우 REFERENCE도 32652로 변환
    if experiment_set and experiment_set in ['Jamsil_cas', 'Iksan_cas']:
        ref_original_crs = metadata['reference']['crs']
        if ref_original_crs and str(ref_original_crs) != 'EPSG:32652':
            print(f"\n📍 REFERENCE 좌표계 변환: {ref_original_crs} → EPSG:32652")
            unified_ref_path = os.path.join(unified_dir, "reference_unified.tif")
            
            cmd = [
                'gdalwarp', '-overwrite',
                '-s_srs', str(ref_original_crs),
                '-t_srs', 'EPSG:32652',
                '-r', 'bilinear',
                '-co', 'COMPRESS=LZW',
                '-co', 'BIGTIFF=YES',
                metadata['reference']['path'],
                unified_ref_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"REFERENCE 좌표계 변환 실패: {result.stderr}")
            
            unified_paths = {
                'reference': unified_ref_path
            }
            print(f"   ✅ 변환 완료: {unified_ref_path}")
        else:
            unified_paths = {
                'reference': metadata['reference']['path']  # Reference는 그대로 사용
            }
            print(f"   ℹ️  REFERENCE이 이미 EPSG:32652입니다.")
    else:
        unified_paths = {
            'reference': metadata['reference']['path']  # Reference는 그대로 사용
        }
    
    # TARGET 좌표계 변환
    target_crs = metadata['target']['crs']
    if target_crs and target_crs != ref_crs:
        print(f"\n📍 TARGET 좌표계 변환: {target_crs} → {ref_crs}")
        unified_target_path = os.path.join(unified_dir, "target_unified.tif")
        
        cmd = [
            'gdalwarp', '-overwrite',
            '-s_srs', str(target_crs),
            '-t_srs', str(ref_crs),
            '-r', 'bilinear',
            '-co', 'COMPRESS=LZW',
            '-co', 'BIGTIFF=YES',
            metadata['target']['path'],
            unified_target_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"TARGET 좌표계 변환 실패: {result.stderr}")
        
        unified_paths['target'] = unified_target_path
        print(f"   ✅ 변환 완료: {unified_target_path}")
    else:
        unified_paths['target'] = metadata['target']['path']
        print(f"   ℹ️  TARGET이 이미 동일한 좌표계입니다.")
    
    # DEM 좌표계 변환
    dem_crs = metadata['dem']['crs']
    if dem_crs != ref_crs:
        print(f"\n📍 DEM 좌표계 변환: {dem_crs} → {ref_crs}")
        unified_dem_path = os.path.join(unified_dir, "dem_unified.tif")
        
        cmd = [
            'gdalwarp', '-overwrite',
            '-s_srs', str(dem_crs),
            '-t_srs', str(ref_crs),
            '-r', 'bilinear',
            '-co', 'COMPRESS=LZW',
            '-co', 'BIGTIFF=YES',
            metadata['dem']['path'],
            unified_dem_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"   ⚠️ DEM 좌표계 변환 실패: {result.stderr}")
            print("   ⚠️ DEM 변환을 건너뛰고 원본 파일을 사용합니다. 결과가 부정확할 수 있습니다.")
            unified_paths['dem'] = metadata['dem']['path']
        else:
            unified_paths['dem'] = unified_dem_path
            print(f"   ✅ 변환 완료: {unified_dem_path}")
    else:
        unified_paths['dem'] = metadata['dem']['path']
        print(f"   ℹ️  DEM이 이미 동일한 좌표계입니다.")
    
    # Geoid 좌표계 변환
    geoid_crs = metadata['geoid']['crs']
    if geoid_crs != ref_crs:
        print(f"\n📍 Geoid 좌표계 변환: {geoid_crs} → {ref_crs}")
        unified_geoid_path = os.path.join(unified_dir, "geoid_unified.tif")
        
        cmd = [
            'gdalwarp', '-overwrite',
            '-s_srs', str(geoid_crs),
            '-t_srs', str(ref_crs),
            '-r', 'bilinear',
            '-co', 'COMPRESS=LZW',
            '-co', 'BIGTIFF=YES',
            metadata['geoid']['path'],
            unified_geoid_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"   ⚠️ Geoid 좌표계 변환 실패: {result.stderr}")
            print("   ⚠️ Geoid 변환을 건너뛰고 원본 파일을 사용합니다. 결과가 부정확할 수 있습니다.")
            unified_paths['geoid'] = metadata['geoid']['path']
        else:
            unified_paths['geoid'] = unified_geoid_path
            print(f"   ✅ 변환 완료: {unified_geoid_path}")
    else:
        unified_paths['geoid'] = metadata['geoid']['path']
        print(f"   ℹ️  Geoid이 이미 동일한 좌표계입니다.")
    
    print("\n✅ STEP 2 완료: 모든 데이터가 동일한 좌표계로 통일되었습니다.")
    return unified_paths


def crop_to_target_extent(unified_paths: dict, metadata: dict, output_dir: str, buffer_factor: float = 1.5, sub_dir: Optional[str] = None) -> dict:
    """
    STEP 3: Target 영역 기준 크롭핑 (버퍼 포함)
    
    Input:
        unified_paths (dict): 좌표계가 통일된 파일 경로들
        metadata (dict): 메타데이터 정보
        output_dir (str): 출력 디렉토리 경로
        buffer_factor (float): 버퍼 팩터 (기본값: 1.5)
        sub_dir (str, optional): 하위 디렉토리명
    
    Output:
        dict: 크롭된 파일 경로들 (reference, target, dem)
    
    Algorithm:
        - Target 영상의 경계를 기준으로 설정
        - buffer_factor를 적용하여 확장된 영역 계산
        - rasterio.mask를 사용한 영역별 크롭핑
        - Reference와 DEM을 Target 영역에 맞춰 자름
        - 처리 효율 향상을 위해 해상도 변환 전에 수행
    """
    print("\n" + "="*80)
    print(f"STEP 3: TARGET 영역 기준 잘라내기 (버퍼: {int((buffer_factor-1)*100)}%)")
    print("="*80)
    
    cropped_dir = os.path.join(output_dir, sub_dir) if sub_dir else output_dir
    os.makedirs(cropped_dir, exist_ok=True)
    
    cropped_paths = {}
    
    # TARGET 정보 가져오기
    # 주의: TARGET은 지리참조가 되어있든 안되어있든 항상 안된 것으로 간주
    with rasterio.open(unified_paths['target']) as src:
        target_width = src.width
        target_height = src.height
    
    # TARGET을 cropped 폴더에 복사 (원본 그대로, crop 하지 않음)
    target_output_path = os.path.join(cropped_dir, "target.tif")
    shutil.copy2(unified_paths['target'], target_output_path)
    cropped_paths['target'] = target_output_path
    print(f"✅ TARGET 복사 완료 (원본): {target_width} x {target_height} pixels")
    
    # REFERENCE 정보 가져오기
    with rasterio.open(unified_paths['reference']) as src:
        ref_bounds = src.bounds
        ref_crs = src.crs
        ref_width = src.width
        ref_height = src.height
        ref_transform = src.transform
        ref_res_x = ref_transform.a
        ref_res_y = abs(ref_transform.e)
    
    print(f"\n📐 REFERENCE 원본:")
    print(f"   크기: {ref_width} x {ref_height} pixels")
    print(f"   해상도: {ref_res_x:.2f} x {ref_res_y:.2f} m")
    print(f"   Bounds: {ref_bounds}")
    
    # 원본 파일의 transform이 경도/위도 단위로 저장되어 있는지 확인
    # (CRS는 UTM인데 transform이 경도/위도인 경우)
    ref_bounds_is_geographic = (ref_bounds.left > -180 and ref_bounds.left < 180 and 
                                ref_bounds.bottom > -90 and ref_bounds.bottom < 90 and
                                abs(ref_bounds.left) > 1.0)  # 경도/위도 범위
    
    if ref_bounds_is_geographic and ref_crs is not None and not ref_crs.is_geographic:
        print(f"   ⚠️ 경고: CRS는 {ref_crs}인데 bounds가 경도/위도로 읽힘")
        print(f"      → transform이 경도/위도 단위로 저장된 것으로 보임")
        print(f"      → 크롭 시 경도/위도 bounds 사용")
    
    # TARGET은 항상 지리참조가 없는 것으로 간주: TARGET 중심좌표와 해상도를 사용
    print(f"\n📍 TARGET 정보 (항상 중심좌표 기반으로 계산):")
    print(f"   중심 좌표: ({TARGET_CENTER_LAT}, {TARGET_CENTER_LON})")
    print(f"   해상도: {TARGET_RESOLUTION} m")
    print(f"   픽셀 크기: {target_width} x {target_height}")
    
    # TARGET 크기(픽셀) * 해상도 = 물리적 크기 (미터 단위)
    target_physical_width = target_width * TARGET_RESOLUTION
    target_physical_height = target_height * TARGET_RESOLUTION
    
    # 버퍼 적용
    buffered_width = target_physical_width * buffer_factor
    buffered_height = target_physical_height * buffer_factor
    
    # ref_crs가 None인 경우에 대한 기본 처리 추가
    if ref_crs is None:
        print(f"   ⚠️ REFERENCE에 좌표계 정보가 없습니다. 픽셀 기반 크롭을 시도하거나 중앙 부근으로 가정합니다.")
        # 만약 좌표계가 없으면 lat/lon 변환이 불가능하므로, 그냥 전체 영역을 사용하거나 에러 방지를 위해 mock bounds 리턴
        # 여기서는 최소한 에러는 안 나게 dummy bounds를 설정하거나 ref_bounds를 그대로 사용
        buffered_bounds = ref_bounds 
    # 원본 파일의 bounds가 경도/위도인 경우 경도/위도로 크롭 영역 계산
    elif ref_bounds_is_geographic:
        # TARGET 중심좌표는 이미 경도/위도
        center_x = TARGET_CENTER_LON
        center_y = TARGET_CENTER_LAT
        
        print(f"   변환된 중심 (경도/위도): ({center_x:.2f}, {center_y:.2f})")
        
        # 미터를 도로 변환
        import math
        meters_per_degree_lat = 111320.0
        meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_y))
        
        width_degrees = buffered_width / meters_per_degree_lon
        height_degrees = buffered_height / meters_per_degree_lat
        
        # Crop 영역 계산 (중앙 기준, 도 단위)
        buffered_bounds = (
            center_x - width_degrees / 2,
            center_y - height_degrees / 2,
            center_x + width_degrees / 2,
            center_y + height_degrees / 2
        )
    elif ref_crs and ref_crs.is_geographic:
        # CRS가 geographic이고 bounds도 geographic인 경우
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:4326", ref_crs, always_xy=True)
        center_x, center_y = transformer.transform(TARGET_CENTER_LON, TARGET_CENTER_LAT)
        
        print(f"   변환된 중심 ({ref_crs}): ({center_x:.2f}, {center_y:.2f})")
        
        import math
        meters_per_degree_lat = 111320.0
        meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_y))
        
        width_degrees = buffered_width / meters_per_degree_lon
        height_degrees = buffered_height / meters_per_degree_lat
        
        buffered_bounds = (
            center_x - width_degrees / 2,
            center_y - height_degrees / 2,
            center_x + width_degrees / 2,
            center_y + height_degrees / 2
        )
    else:
        # Projected CRS (미터 단위)인 경우
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:4326", ref_crs, always_xy=True)
        center_x, center_y = transformer.transform(TARGET_CENTER_LON, TARGET_CENTER_LAT)
        
        print(f"   변환된 중심 ({ref_crs}): ({center_x:.2f}, {center_y:.2f})")
        
        buffered_bounds = (
            center_x - buffered_width / 2,
            center_y - buffered_height / 2,
            center_x + buffered_width / 2,
            center_y + buffered_height / 2
        )
    
    print(f"\n📐 영역 계산:")
    print(f"   TARGET 물리적 크기: {target_physical_width:.2f} x {target_physical_height:.2f} m")
    print(f"   버퍼 적용 크기: {buffered_width:.2f} x {buffered_height:.2f} m")
    print(f"   Left: {buffered_bounds[0]:.2f}, Bottom: {buffered_bounds[1]:.2f}")
    print(f"   Right: {buffered_bounds[2]:.2f}, Top: {buffered_bounds[3]:.2f}") 
    
    # REFERENCE 잘라내기
    print(f"\n✂️  REFERENCE 잘라내는 중...")
    # VRT를 그대로 사용 (큰 파일 처리에 최적, 크기 제한 없음)
    cropped_ref_path = os.path.join(cropped_dir, "reference_cropped.vrt")
    
    # VRT 생성 (가상 크롭, 실제 파일 생성 없음)
    # 원본 파일의 transform이 경도/위도인 경우 좌표계를 명시적으로 지정
    if ref_bounds_is_geographic:
        # bounds가 경도/위도이므로 -te_srs로 좌표계 명시
        cmd_vrt = [
            'gdalwarp', '-overwrite', '-of', 'VRT',
            '-s_srs', 'EPSG:4326',  # 소스 좌표계 명시 (경도/위도)
            '-t_srs', str(ref_crs),  # 타겟 좌표계 (원본 CRS 유지)
            '-te_srs', 'EPSG:4326',  # -te 옵션의 좌표계 명시 (경도/위도)
            '-te', str(buffered_bounds[0]), str(buffered_bounds[1]), 
                   str(buffered_bounds[2]), str(buffered_bounds[3]),
            unified_paths['reference'],
            cropped_ref_path
        ]
    else:
        # 일반적인 경우
        cmd_vrt = [
            'gdalwarp', '-overwrite', '-of', 'VRT',
            '-te', str(buffered_bounds[0]), str(buffered_bounds[1]), 
                   str(buffered_bounds[2]), str(buffered_bounds[3]),
            unified_paths['reference'],
            cropped_ref_path
        ]
    
    result_vrt = subprocess.run(cmd_vrt, capture_output=True, text=True)
    if result_vrt.returncode != 0:
        raise RuntimeError(f"VRT 생성 실패: {result_vrt.stderr}")
    
    print(f"   ✅ VRT 생성 완료 (가상 파일, 크기 제한 없음)")
    cropped_paths['reference'] = cropped_ref_path
    
    # VRT 파일의 크기를 직접 읽기 (rasterio가 bounds를 잘못 읽을 수 있으므로)
    with rasterio.open(cropped_ref_path) as src:
        # VRT의 실제 크기 (rasterio가 올바르게 읽음)
        cropped_width = src.width
        cropped_height = src.height
        ref_bounds_vrt = src.bounds
        ref_transform_vrt = src.transform
        
        # 해상도는 transform에서 계산
        if ref_bounds_is_geographic:
            # transform이 경도/위도 단위인 경우, 미터로 변환
            import math
            center_lat = (ref_bounds_vrt.top + ref_bounds_vrt.bottom) / 2
            meters_per_degree_lat = 111320.0
            meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_lat))
            res_x_m = abs(ref_transform_vrt.a) * meters_per_degree_lon
            res_y_m = abs(ref_transform_vrt.e) * meters_per_degree_lat
        else:
            # UTM 등 미터 단위
            res_x_m = abs(ref_transform_vrt.a)
            res_y_m = abs(ref_transform_vrt.e)
        
        print(f"   ✅ 완료: {cropped_width} x {cropped_height} pixels")
        print(f"   해상도: {res_x_m:.4f} x {res_y_m:.4f} m")
        
        # 크기 변화 출력
        size_ratio = (cropped_width * cropped_height) / (ref_width * ref_height) * 100
        print(f"   📊 크기 변화: {ref_width}x{ref_height} → {cropped_width}x{cropped_height} ({size_ratio:.1f}% 유지)")
    
    # DEM 잘라내기 (REFERENCE 좌표계로 변환 + crop)
    print(f"\n✂️  DEM 잘라내는 중...")
    print(f"   REFERENCE 좌표계로 변환 및 crop...")
    cropped_dem_path = os.path.join(cropped_dir, "dem_cropped.tif")
    
    # DEM 크롭 bounds 결정
    # REFERENCE bounds가 경도/위도인 경우, DEM은 이미 UTM이므로 bounds를 UTM으로 변환
    if ref_bounds_is_geographic:
        # 경도/위도 bounds를 UTM으로 변환
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:4326", ref_crs, always_xy=True)
        dem_crop_bounds = transformer.transform_bounds(
            buffered_bounds[0], buffered_bounds[1],  # left, bottom
            buffered_bounds[2], buffered_bounds[3],  # right, top
        )
        print(f"   경도/위도 bounds를 UTM으로 변환:")
        print(f"      {buffered_bounds} → {dem_crop_bounds}")
    else:
        # 이미 같은 좌표계
        dem_crop_bounds = buffered_bounds
    
    cmd = [
        'gdalwarp', '-overwrite',
        '-t_srs', str(ref_crs),  # REFERENCE 좌표계로 변환
        '-te', str(dem_crop_bounds[0]), str(dem_crop_bounds[1]), 
               str(dem_crop_bounds[2]), str(dem_crop_bounds[3]),
        '-r', 'bilinear',
        '-co', 'COMPRESS=LZW',
        '-co', 'BIGTIFF=YES',
        '-co', 'TILED=NO',  # STRIP 방식 사용
        unified_paths['dem'],
        cropped_dem_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"DEM 잘라내기 실패: {result.stderr}")
    
    cropped_paths['dem'] = cropped_dem_path
    
    with rasterio.open(cropped_dem_path) as src:
        print(f"   ✅ 완료: {src.width} x {src.height} pixels")
    
    # Geoid 잘라내기 (REFERENCE 좌표계로 변환 + crop)
    print(f"\n✂️  Geoid 잘라내는 중...")
    cropped_geoid_path = os.path.join(cropped_dir, "geoid_cropped.tif")
    
    cmd = [
        'gdalwarp', '-overwrite',
        '-t_srs', str(ref_crs),  # REFERENCE 좌표계로 변환
        '-te', str(dem_crop_bounds[0]), str(dem_crop_bounds[1]), 
               str(dem_crop_bounds[2]), str(dem_crop_bounds[3]),
        '-r', 'bilinear',
        '-co', 'COMPRESS=LZW',
        '-co', 'BIGTIFF=YES',
        '-co', 'TILED=NO',
        unified_paths['geoid'],
        cropped_geoid_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Geoid 잘라내기 실패: {result.stderr}")
    
    cropped_paths['geoid'] = cropped_geoid_path
    
    with rasterio.open(cropped_geoid_path) as src:
        print(f"   ✅ 완료: {src.width} x {src.height} pixels")

    
    # 결과 요약
    print("\n" + "="*80)
    print("📊 STEP 3 결과 요약:")
    print("="*80)
    print(f"✅ TARGET (원본, crop 안함): {target_output_path}")
    with rasterio.open(target_output_path) as src:
        print(f"   크기: {src.width} x {src.height} pixels")
        if src.transform != rasterio.Affine.identity():
            res_x = src.transform.a
            res_y = abs(src.transform.e)
            print(f"   해상도: {res_x:.2f} x {res_y:.2f} m")
        else:
            print(f"   해상도: 좌표정보 없음")
    
    print(f"\n✅ REFERENCE (crop된 영상, 아직 원본 해상도): {cropped_ref_path}")
    with rasterio.open(cropped_ref_path) as src:
        print(f"   크기: {src.width} x {src.height} pixels")
        print(f"   해상도: {src.transform.a:.2f} x {abs(src.transform.e):.2f} m")
        print(f"   좌표계: {src.crs}")
    
    print(f"\n✅ DEM (REFERENCE 좌표계 + crop): {cropped_dem_path}")
    with rasterio.open(cropped_dem_path) as src:
        print(f"   크기: {src.width} x {src.height} pixels")
        print(f"   해상도: {src.transform.a:.2f} x {abs(src.transform.e):.2f} m")
        print(f"   좌표계: {src.crs}")
        
    print(f"\n✅ Geoid (REFERENCE 좌표계 + crop): {cropped_geoid_path}")
    with rasterio.open(cropped_geoid_path) as src:
        print(f"   크기: {src.width} x {src.height} pixels")
        print(f"   해상도: {src.transform.a:.2f} x {abs(src.transform.e):.2f} m")
        print(f"   좌표계: {src.crs}")
    
    print("\n✅ STEP 3 완료:")
    print(f"   • TARGET: 원본 복사 (crop 안함)")
    print(f"   • REFERENCE: TARGET 영역 crop (원본 해상도 유지)")
    print(f"   • DEM: REFERENCE 좌표계 변환 + crop")
    print(f"   • Geoid: REFERENCE 좌표계 변환 + crop")
    print(f"   📁 저장 위치: {cropped_dir}")
    return cropped_paths

def crop_to_target_extent2(unified_paths: dict,
                          output_dir: str,
                          buffer_factor: float = 1.5) -> dict:
    """
    Target 영상의 공간 범위(Extent)에 맞게 reference, dem 영상을 크롭.
    결과는 OUTPUT_DIR/step03_cropped/reference_cropped.tif, dem_cropped.tif 로 저장됨.

    Args:
        unified_paths (dict):
            {
                "reference": <참조 영상 경로>,
                "target":    <타겟(기준) 영상 경로>,
                "dem":       <DEM 영상 경로>
            }
        output_dir (str): 크롭 결과를 저장할 루트 디렉토리
        buffer_factor (float): 타겟 extent를 얼마나 확장할지 비율 (기본 1.5배)

    Returns:
        dict: 크롭된 파일 경로들
            {
                "reference": <크롭된 reference 경로>,
                "target":    <원본 target 경로(변경 없음)>,
                "dem":       <크롭된 dem 경로>
            }
    """
    # 출력 폴더 생성
    step03_dir = os.path.join(output_dir, "step03_cropped")
    os.makedirs(step03_dir, exist_ok=True)

    ref_path = unified_paths.get("reference")
    tar_path = unified_paths.get("target")
    dem_path = unified_paths.get("dem")
    geoid_path = unified_paths.get("geoid")

    # ---- 타겟 영상 열기 ----
    target_ds = gdal.Open(tar_path, gdal.GA_ReadOnly)
    if target_ds is None:
        raise FileNotFoundError(f"Target 파일을 열 수 없습니다: {tar_path}")

    t_gt = target_ds.GetGeoTransform()
    t_proj = target_ds.GetProjection()
    t_cols = target_ds.RasterXSize
    t_rows = target_ds.RasterYSize

    # ---- 타겟 코너 좌표 ----
    def corners_from_gt(gt, cols, rows):
        x0, px_w, rot_x, y0, rot_y, px_h = gt

        def pix2geo(c, r):
            X = x0 + c * px_w + r * rot_x
            Y = y0 + c * rot_y + r * px_h
            return (X, Y)

        UL = pix2geo(0, 0)
        UR = pix2geo(cols, 0)
        LR = pix2geo(cols, rows)
        LL = pix2geo(0, rows)
        return [UL, UR, LR, LL]

    t_corners = corners_from_gt(t_gt, t_cols, t_rows)
    txs = [p[0] for p in t_corners]
    tys = [p[1] for p in t_corners]

    tx_min, tx_max = float(np.min(txs)), float(np.max(txs))
    ty_min, ty_max = float(np.min(tys)), float(np.max(tys))

    # ---- 버퍼 적용 ----
    if buffer_factor != 1.0:
        cx = 0.5 * (tx_min + tx_max)
        cy = 0.5 * (ty_min + ty_max)
        half_w = 0.5 * (tx_max - tx_min) * buffer_factor
        half_h = 0.5 * (ty_max - ty_min) * buffer_factor
        tx_min = cx - half_w
        tx_max = cx + half_w
        ty_min = cy - half_h
        ty_max = cy + half_h

    # 타겟 좌표계
    t_srs = osr.SpatialReference()
    t_srs.ImportFromWkt(t_proj)
    t_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    # ---- TARGET 복사 (step03_cropped 폴더에) ----
    # STEP 12에서 step03_cropped/target.tif를 찾으므로 여기에 복사 필요
    target_output_path = os.path.join(step03_dir, "target.tif")
    shutil.copy2(tar_path, target_output_path)
    print(f"✅ TARGET 복사 완료 (원본): {t_cols} x {t_rows} pixels")
    print(f"   📁 저장: {target_output_path}")
    
    out_paths = {
        "target": target_output_path,  # step03_cropped 폴더의 복사본 경로
        "reference": None,
        "dem": None,
        "geoid": None
    }

    # ---- 공통 크롭 함수 ----
    def crop_one(src_path: str, key_name: str, out_name: str) -> str:
        if src_path is None:
            return None

        src_ds = gdal.Open(src_path, gdal.GA_ReadOnly)
        if src_ds is None:
            raise FileNotFoundError(f"{key_name} 파일을 열 수 없습니다: {src_path}")

        s_proj = src_ds.GetProjection()

        s_srs = osr.SpatialReference()
        s_srs.ImportFromWkt(s_proj)
        s_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        # 타겟 -> 해당 영상 좌표계로 변환
        ct = osr.CoordinateTransformation(t_srs, s_srs)
        bbox_corners_t = [
            (tx_min, ty_min),
            (tx_min, ty_max),
            (tx_max, ty_min),
            (tx_max, ty_max),
        ]
        bbox_corners_s = [ct.TransformPoint(x, y) for (x, y) in bbox_corners_t]
        bbox_corners_s = [(xy[0], xy[1]) for xy in bbox_corners_s]

        xs = [p[0] for p in bbox_corners_s]
        ys = [p[1] for p in bbox_corners_s]

        x_min, x_max = float(np.min(xs)), float(np.max(xs))
        y_min, y_max = float(np.min(ys)), float(np.max(ys))

        ulx, uly = x_min, y_max
        lrx, lry = x_max, y_min

        out_path = os.path.join(step03_dir, out_name)

        translate_opts = gdal.TranslateOptions(
            projWin=[ulx, uly, lrx, lry],
            projWinSRS=s_proj,
            creationOptions=["COMPRESS=LZW", "TILED=YES"]
        )
        _ = gdal.Translate(out_path, src_ds, options=translate_opts)
        src_ds = None
        return out_path

    # ---- reference / dem / geoid 크롭 ----
    out_paths["reference"] = crop_one(ref_path, "reference", "reference_cropped.tif")
    out_paths["dem"] = crop_one(dem_path, "dem", "dem_cropped.tif")
    out_paths["geoid"] = crop_one(geoid_path, "geoid", "geoid_cropped.tif")

    target_ds = None
    return out_paths

def normalize_resolution(cropped_paths: dict, metadata: dict, output_dir: str, sub_dir: Optional[str] = None, experiment_set: Optional[str] = None) -> dict:
    """
    STEP 4: 해상도 정규화 (Target 기준)
    
    Input:
        cropped_paths (dict): 크롭된 파일 경로들
        metadata (dict): 메타데이터 정보
        output_dir (str): 출력 디렉토리 경로
        sub_dir (str, optional): 하위 디렉토리명
    
    Output:
        dict: 해상도가 정규화된 파일 경로들 (reference, target, dem)
    
    Algorithm:
        - Target 영상의 해상도를 기준으로 설정
        - rasterio.warp.reproject를 사용한 해상도 변환
        - Reference와 DEM을 Target 해상도로 리샘플링
        - Cubic 리샘플링으로 고품질 보간 수행
        - 모든 영상이 동일한 해상도를 갖도록 정규화
    """
    print("\n" + "="*80)
    print("STEP 4: 해상도 정규화 (crop된 영상만 처리)")
    print("="*80)
    
    normalized_dir = os.path.join(output_dir, sub_dir) if sub_dir else output_dir
    os.makedirs(normalized_dir, exist_ok=True)
    
    normalized_paths = {}
    
    # global 선언 (변수 사용 전에 선언해야 함)
    global TARGET_RESOLUTION
    
    # TARGET 정보 확인
    # 주의: TARGET은 지리참조가 되어있든 안되어있든 항상 안된 것으로 간주
    with rasterio.open(cropped_paths['target']) as src:
        target_width = src.width
        target_height = src.height
        # TARGET의 실제 해상도 확인 (transform에서)
        if src.transform != rasterio.Affine.identity():
            target_actual_res_x = abs(src.transform.a)
            target_actual_res_y = abs(src.transform.e)
        else:
            # transform이 없으면 TARGET_RESOLUTION 사용
            target_actual_res_x = TARGET_RESOLUTION
            target_actual_res_y = TARGET_RESOLUTION
    
    # 0.5m 해상도면 2.0m로 리샘플링
    if TARGET_RESOLUTION is not None and abs(TARGET_RESOLUTION - 0.5) < 0.1:
        print(f"\n📍 TARGET 해상도 확인:")
        print(f"   TARGET 크기: {target_width} x {target_height} pixels")
        print(f"   입력 해상도: {TARGET_RESOLUTION}m")
        print(f"   🔄 0.5m 해상도 감지 → 2.0m로 리샘플링 수행")
        
        # TARGET_RESOLUTION을 2.0m로 업데이트
        TARGET_RESOLUTION = 2.0
        tar_res_x, tar_res_y = 2.0, 2.0
        
        # TARGET을 2.0m로 리샘플링
        target_resampled_path = os.path.join(normalized_dir, "target_resampled_2m.tif")
        
        # gdalwarp로 리샘플링
        cmd = [
            'gdalwarp', '-overwrite',
            '--config', 'CHECK_DISK_FREE_SPACE', 'FALSE',
            '-tr', str(tar_res_x), str(tar_res_y),
            '-r', 'cubic',
            '-co', 'COMPRESS=LZW',
            '-co', 'BIGTIFF=YES',
            cropped_paths['target'],
            target_resampled_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"TARGET 리샘플링 실패: {result.stderr}")
        
        normalized_paths['target'] = target_resampled_path
        
        with rasterio.open(target_resampled_path) as src_resampled:
            print(f"   ✅ 리샘플링 완료: {src_resampled.width} x {src_resampled.height} pixels ({tar_res_x:.2f}m)")
            print(f"   📊 크기 변화: {target_width}x{target_height} → {src_resampled.width}x{src_resampled.height}")
    else:
        # 기준 해상도 결정: 항상 TARGET_RESOLUTION 사용
        print(f"\n📍 TARGET 해상도 (항상 설정된 값 사용):")
        print(f"   TARGET 크기: {target_width} x {target_height} pixels")
        print(f"   🎯 기준 해상도: {TARGET_RESOLUTION}m (설정된 TARGET 해상도)")
        tar_res_x, tar_res_y = TARGET_RESOLUTION, TARGET_RESOLUTION
        
        # TARGET은 그대로 사용
        normalized_paths['target'] = cropped_paths['target']
        print(f"✅ TARGET: 원본 사용")
    
    # REFERENCE 해상도 결정
    # Jamsil_cas, Iksan_cas의 경우 0.3m로 하드코딩
    if experiment_set and experiment_set in ['Jamsil_cas', 'Iksan_cas']:
        ref_res_x, ref_res_y = 0.3, 0.3
        print(f"\n📐 REFERENCE 해상도 (하드코딩):")
        print(f"   실험 셋: {experiment_set}")
        print(f"   해상도: {ref_res_x:.2f} x {ref_res_y:.2f} m (하드코딩)")
    else:
        ref_res_x, ref_res_y = metadata['reference']['resolution']
        print(f"\n📐 REFERENCE 해상도 (메타데이터에서 읽음):")
        print(f"   해상도: {ref_res_x:.2f} x {ref_res_y:.2f} m")
    
    # crop된 REFERENCE 정보 읽기
    # VRT 파일인 경우 크기 정보가 잘못 읽힐 수 있으므로 bounds 기반으로 계산
    with rasterio.open(cropped_paths['reference']) as src:
        ref_crs = src.crs
        ref_bounds = src.bounds
        
        # VRT 파일인 경우 크기를 bounds와 해상도로부터 계산
        if cropped_paths['reference'].endswith('.vrt'):
            # bounds와 해상도로부터 크기 계산
            if ref_crs and ref_crs.is_geographic:
                import math
                center_lat = (ref_bounds.top + ref_bounds.bottom) / 2
                meters_per_degree_lat = 111320.0
                meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_lat))
                width_m = (ref_bounds.right - ref_bounds.left) * meters_per_degree_lon
                height_m = (ref_bounds.top - ref_bounds.bottom) * meters_per_degree_lat
            else:
                width_m = ref_bounds.right - ref_bounds.left
                height_m = ref_bounds.top - ref_bounds.bottom
            
            ref_cropped_width = int(width_m / ref_res_x)
            ref_cropped_height = int(height_m / ref_res_y)
        else:
            ref_cropped_width = src.width
            ref_cropped_height = src.height
    
    print(f"\n📐 REFERENCE (crop된 상태):")
    print(f"   크기: {ref_cropped_width} x {ref_cropped_height} pixels")
    print(f"   해상도: {ref_res_x:.2f} x {ref_res_y:.2f} m")
    
    if abs(ref_res_x - tar_res_x) > 0.01 or abs(ref_res_y - tar_res_y) > 0.01:
        print(f"\n🔄 해상도 변환: {ref_res_x:.2f}x{ref_res_y:.2f}m → {tar_res_x:.2f}x{tar_res_y:.2f}m")
        print(f"   ⚡ crop된 영상만 처리하므로 빠릅니다!")
        
        normalized_ref_path = os.path.join(normalized_dir, "reference_normalized.tif")
        
        # 중심 좌표 가져오기 (도 변환에 필요)
        center_lat = (ref_bounds.top + ref_bounds.bottom) / 2
        
        # CRS가 geographic인 경우 미터를 도로 변환
        if ref_crs and ref_crs.is_geographic:
            import math
            meters_per_degree_lat = 111320.0  # 위도 방향은 항상 일정
            meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_lat))
            
            # 미터를 도로 변환
            tar_res_x_deg = tar_res_x / meters_per_degree_lon
            tar_res_y_deg = tar_res_y / meters_per_degree_lat
            
            print(f"   📐 Geographic CRS 감지: 미터를 도로 변환")
            print(f"      {tar_res_x:.2f}m → {tar_res_x_deg:.8f}도 (경도)")
            print(f"      {tar_res_y:.2f}m → {tar_res_y_deg:.8f}도 (위도)")
            
            tr_x, tr_y = tar_res_x_deg, tar_res_y_deg
        else:
            # Projected CRS인 경우 미터 단위 그대로 사용
            tr_x, tr_y = tar_res_x, tar_res_y
        
        # VRT 파일인 경우 원본 파일을 직접 사용하여 크롭과 해상도 변환을 한 번에 수행
        # (VRT를 경유하면 메모리 할당 문제 발생)
        if cropped_paths['reference'].endswith('.vrt'):
            # VRT의 bounds는 이미 UTM (EPSG:32652)로 변환되어 있음
            # unified된 파일이 있는지 확인 (Jamsil_cas, Iksan_cas의 경우)
            unified_ref_path = None
            if experiment_set and experiment_set in ['Jamsil_cas', 'Iksan_cas']:
                # unified 디렉토리에서 unified된 파일 찾기
                unified_dir = os.path.join(output_dir, 'step02_unified_crs')
                unified_ref_path = os.path.join(unified_dir, "reference_unified.tif")
                if os.path.exists(unified_ref_path):
                    print(f"   📌 VRT 감지: unified된 파일 사용 (EPSG:32652)")
                    print(f"      unified 파일: {unified_ref_path}")
                    print(f"      크롭 영역 (UTM): {ref_bounds}")
                    # unified된 파일과 UTM bounds 사용
                    original_path = unified_ref_path
                    orig_bounds_is_geographic = False
                else:
                    # unified 파일이 없으면 원본 사용 (하지만 이 경우는 없어야 함)
                    original_path = metadata['reference']['path']
                    orig_bounds_is_geographic = True
            else:
                # 다른 실험 셋의 경우 원본 파일 사용
                original_path = metadata['reference']['path']
                with rasterio.open(original_path) as orig_src:
                    orig_bounds = orig_src.bounds
                    orig_crs = orig_src.crs
                
                # 원본 파일의 bounds가 경도/위도인지 확인
                orig_bounds_is_geographic = (orig_bounds.left > -180 and orig_bounds.left < 180 and 
                                             orig_bounds.bottom > -90 and orig_bounds.bottom < 90 and
                                             abs(orig_bounds.left) > 1.0)
            
            if orig_bounds_is_geographic:
                # 경도/위도 bounds를 다시 계산 (crop_to_target_extent와 동일한 로직)
                from pyproj import Transformer
                import math
                
                # TARGET 정보 가져오기
                with rasterio.open(cropped_paths['target']) as tgt_src:
                    target_width = tgt_src.width
                    target_height = tgt_src.height
                
                # TARGET 물리적 크기 계산
                target_physical_width = target_width * TARGET_RESOLUTION
                target_physical_height = target_height * TARGET_RESOLUTION
                
                # 버퍼 적용 (crop_to_target_extent와 동일한 버퍼 팩터 사용)
                buffer_factor = 1.19  # 기본값
                buffered_width = target_physical_width * buffer_factor
                buffered_height = target_physical_height * buffer_factor
                
                # 중심 좌표 (경도/위도)
                center_x = TARGET_CENTER_LON
                center_y = TARGET_CENTER_LAT
                
                # 미터를 도로 변환
                meters_per_degree_lat = 111320.0
                meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_y))
                
                width_degrees = buffered_width / meters_per_degree_lon
                height_degrees = buffered_height / meters_per_degree_lat
                
                # 경도/위도 bounds 계산
                crop_bounds = (
                    center_x - width_degrees / 2,
                    center_y - height_degrees / 2,
                    center_x + width_degrees / 2,
                    center_y + height_degrees / 2
                )
                print(f"   📌 VRT 감지: 원본 파일 직접 사용하여 크롭+해상도 변환 수행")
                print(f"      원본: {original_path}")
                print(f"      크롭 영역 (경도/위도): {crop_bounds}")
            else:
                # UTM bounds인 경우 VRT의 bounds 사용
                crop_bounds = (ref_bounds.left, ref_bounds.bottom, ref_bounds.right, ref_bounds.top)
                print(f"   📌 VRT 감지: 원본 파일 직접 사용하여 크롭+해상도 변환 수행")
                print(f"      원본: {original_path}")
                print(f"      크롭 영역 (UTM): {crop_bounds}")
            
            # 원본 파일을 직접 사용하여 크롭과 해상도 변환을 한 번에 수행
            # 단계적 해상도 변환으로 메모리 문제 회피
            if os.path.exists(original_path):
                
                # 해상도 비율이 너무 크면 단계적으로 변환
                resolution_ratio = tar_res_x / ref_res_x
                if resolution_ratio > 3.0:  # 3배 이상이면 단계적 변환
                    print(f"   🔄 해상도 비율이 큼 ({resolution_ratio:.1f}배): 단계적 변환 수행")
                    # 중간 해상도 계산 (약 1m)
                    intermediate_res = tar_res_x / 2.0  # 최종 해상도의 절반
                    
                    # 원본 파일의 transform이 경도/위도인 경우 도 단위로 변환
                    if orig_bounds_is_geographic:
                        # center_lat은 이미 위에서 계산됨 (ref_bounds 기반)
                        center_lat = (ref_bounds.top + ref_bounds.bottom) / 2
                        meters_per_degree_lat = 111320.0
                        meters_per_degree_lon = 111320.0 * math.cos(math.radians(center_lat))
                        int_res_x = intermediate_res / meters_per_degree_lon
                        int_res_y = intermediate_res / meters_per_degree_lat
                    elif ref_crs and ref_crs.is_geographic:
                        int_res_x = intermediate_res / meters_per_degree_lon
                        int_res_y = intermediate_res / meters_per_degree_lat
                    else:
                        int_res_x = intermediate_res
                        int_res_y = intermediate_res
                    
                    # 중간 파일 경로
                    intermediate_path = os.path.join(normalized_dir, "reference_intermediate.tif")
                    
                    # Step 1: 중간 해상도로 변환
                    print(f"   Step 1/2: 중간 해상도 ({intermediate_res:.2f}m)로 변환...")
                    cmd1 = ['gdalwarp', '-overwrite', '-wm', '512', '-multi',
                            '-wo', 'NUM_THREADS=ALL_CPUS', '-wo', 'CHUNKYSIZE=200']
                    
                    # 경도/위도 bounds인 경우 좌표계 명시
                    if orig_bounds_is_geographic:
                        cmd1.extend(['-s_srs', 'EPSG:4326', '-te_srs', 'EPSG:4326'])
                        crop_bounds_te = crop_bounds  # 경도/위도 bounds
                    else:
                        # UTM bounds 사용 (VRT의 bounds 그대로 사용)
                        crop_bounds_te = (ref_bounds.left, ref_bounds.bottom, ref_bounds.right, ref_bounds.top)
                    
                    cmd1.extend([
                        '-te', str(crop_bounds_te[0]), str(crop_bounds_te[1]), 
                               str(crop_bounds_te[2]), str(crop_bounds_te[3]),
                        '-tr', str(int_res_x), str(int_res_y),
                        '-r', 'bilinear',
                        '-co', 'COMPRESS=LZW',
                        '-co', 'BIGTIFF=YES',
                        '-co', 'TILED=YES',
                        '-co', 'BLOCKXSIZE=256',
                        '-co', 'BLOCKYSIZE=256',
                        original_path,
                        intermediate_path
                    ])
                    
                    result1 = subprocess.run(cmd1, capture_output=True, text=True)
                    if result1.returncode != 0:
                        raise RuntimeError(f"중간 해상도 변환 실패: {result1.stderr}")
                    
                    # Step 2: 최종 해상도로 변환
                    print(f"   Step 2/2: 최종 해상도 ({tar_res_x:.2f}m)로 변환...")
                    cmd = [
                        'gdalwarp', '-overwrite',
                        '-wm', '512',
                        '-multi',
                        '-wo', 'NUM_THREADS=ALL_CPUS',
                        '-wo', 'CHUNKYSIZE=500',
                        '-tr', str(tr_x), str(tr_y),
                        '-r', 'bilinear',
                        '-co', 'COMPRESS=LZW',
                        '-co', 'BIGTIFF=YES',
                        '-co', 'TILED=YES',
                        '-co', 'BLOCKXSIZE=256',
                        '-co', 'BLOCKYSIZE=256',
                        intermediate_path,
                        normalized_ref_path
                    ]
                    
                    # 중간 파일 정리
                    if os.path.exists(intermediate_path):
                        def cleanup_intermediate():
                            try:
                                os.remove(intermediate_path)
                            except:
                                pass
                        import atexit
                        atexit.register(cleanup_intermediate)
                else:
                    # 한 번에 변환
                    cmd = ['gdalwarp', '-overwrite', '-wm', '512', '-multi',
                           '-wo', 'NUM_THREADS=ALL_CPUS', '-wo', 'CHUNKYSIZE=200']
                    
                    # 경도/위도 bounds인 경우 좌표계 명시
                    if orig_bounds_is_geographic:
                        cmd.extend(['-s_srs', 'EPSG:4326', '-te_srs', 'EPSG:4326'])
                        crop_bounds_te = crop_bounds  # 경도/위도 bounds
                    else:
                        # UTM bounds 사용 (VRT의 bounds 그대로 사용)
                        crop_bounds_te = (ref_bounds.left, ref_bounds.bottom, ref_bounds.right, ref_bounds.top)
                    
                    cmd.extend([
                        '-te', str(crop_bounds_te[0]), str(crop_bounds_te[1]), 
                               str(crop_bounds_te[2]), str(crop_bounds_te[3]),
                        '-tr', str(tr_x), str(tr_y),
                        '-r', 'bilinear',
                        '-co', 'COMPRESS=LZW',
                        '-co', 'BIGTIFF=YES',
                        '-co', 'TILED=YES',
                        '-co', 'BLOCKXSIZE=256',
                        '-co', 'BLOCKYSIZE=256',
                        original_path,
                        normalized_ref_path
                    ])
            else:
                # 원본 파일이 없으면 VRT를 사용하되 매우 작은 청크로
                print(f"   ⚠️ 원본 파일을 찾을 수 없음, VRT 사용 (메모리 부족 가능)")
                cmd = [
                    'gdalwarp', '-overwrite',
                    '-wm', '1024',  # 작은 작업 메모리
                    '-multi',
                    '-wo', 'NUM_THREADS=ALL_CPUS',
                    '-wo', 'CHUNKYSIZE=200',  # 매우 작은 청크
                    '-tr', str(tr_x), str(tr_y),
                    '-r', 'bilinear',
                    '-co', 'COMPRESS=LZW',
                    '-co', 'BIGTIFF=YES',
                    '-co', 'TILED=YES',
                    '-co', 'BLOCKXSIZE=256',
                    '-co', 'BLOCKYSIZE=256',
                    cropped_paths['reference'],
                    normalized_ref_path
                ]
        else:
            # 일반 TIF 파일인 경우
            cmd = [
                'gdalwarp', '-overwrite',
                '-wm', '2048',
                '-multi',
                '-wo', 'NUM_THREADS=ALL_CPUS',
                '-wo', 'CHUNKYSIZE=500',
                '-tr', str(tr_x), str(tr_y),
                '-r', 'bilinear',
                '-co', 'COMPRESS=LZW',
                '-co', 'BIGTIFF=YES',
                '-co', 'TILED=YES',
                '-co', 'BLOCKXSIZE=256',
                '-co', 'BLOCKYSIZE=256',
                cropped_paths['reference'],
                normalized_ref_path
            ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"REFERENCE 해상도 정규화 실패: {result.stderr}")
        
        normalized_paths['reference'] = normalized_ref_path
        
        with rasterio.open(normalized_ref_path) as src:
            normalized_width = src.width
            normalized_height = src.height
            print(f"   ✅ 정규화 완료: {normalized_width} x {normalized_height} pixels ({tar_res_x:.2f}m)")
            
            # 해상도 비율 계산
            res_ratio = ref_res_x / tar_res_x
            size_ratio_width = normalized_width / ref_cropped_width
            size_ratio_height = normalized_height / ref_cropped_height
            print(f"   📊 크기 변화: {ref_cropped_width}x{ref_cropped_height} → {normalized_width}x{normalized_height}")
            print(f"      (폭: {size_ratio_width:.2f}배, 높이: {size_ratio_height:.2f}배, 해상도 비율: {res_ratio:.2f}배)")
            print(f"   📁 파일: {normalized_ref_path}")
    else:
        # 이미 같은 해상도면 복사
        normalized_ref_path = os.path.join(normalized_dir, "reference_normalized.tif")
        shutil.copy2(cropped_paths['reference'], normalized_ref_path)
        normalized_paths['reference'] = normalized_ref_path
        print(f"\n✅ 이미 {tar_res_x:.2f}m 해상도입니다 (복사)")
        print(f"   크기: {ref_cropped_width} x {ref_cropped_height} pixels (변화 없음)")
        print(f"   📁 파일: {normalized_ref_path}")
    
    # DEM은 그대로 사용
    normalized_paths['dem'] = cropped_paths['dem']
    print(f"\n✅ DEM: crop된 원본 사용")
    
    # Geoid은 그대로 사용
    normalized_paths['geoid'] = cropped_paths['geoid']
    print(f"\n✅ Geoid: crop된 원본 사용")
    
    # 최종 결과 요약
    print("\n" + "="*80)
    print("✅ STEP 4 완료: 해상도 정규화 완료")
    print("="*80)
    print(f"📁 저장 위치: {normalized_dir}")
    with rasterio.open(normalized_paths['reference']) as src:
        print(f"   • reference_normalized.tif: {src.width}x{src.height} pixels, {tar_res_x:.2f}m 해상도")
    print(f"   • TARGET, DEM, Geoid: 원본 경로 참조")
    
    return normalized_paths


def prepare_lowres_images(normalized_paths: dict, output_dir: str, resolution_divisor: int = 4, sub_dir: Optional[str] = None) -> dict:
    """
    STEP 5: 저해상도 영상 생성 (빠른 매칭용)
    
    Input:
        normalized_paths (dict): 해상도가 정규화된 파일 경로들
        output_dir (str): 출력 디렉토리 경로
        resolution_divisor (int): 해상도 나누기 값 (기본값: 4)
        sub_dir (Optional[str]): 하위 디렉토리 이름 (기본값: "step05_lowres")
    
    Output:
        dict: 저해상도 파일 경로들 (reference, target)
    
    Algorithm:
        - resolution_divisor로 해상도를 나누어 저해상도 생성
        - rasterio.warp.reproject를 사용한 다운샘플링
        - Nearest neighbor 리샘플링으로 빠른 처리
        - AI 기반 매칭의 속도 향상을 위해 사용
        - 원본 해상도로 스케일링할 때 정확도 보장
    """
    print("\n" + "="*80)
    print(f"STEP 5: 저해상도 영상 생성 (1/{resolution_divisor} 해상도)")
    print("="*80)
    
    if sub_dir is None:
        sub_dir = "step05_lowres"
    lowres_dir = os.path.join(output_dir, sub_dir)
    os.makedirs(lowres_dir, exist_ok=True)
    
    lowres_paths = {}
    
    for key in ['reference', 'target']:
        print(f"\n📉 {key.upper()} 다운샘플링 중...")
        
        with rasterio.open(normalized_paths[key]) as src:
            orig_width = src.width
            orig_height = src.height
            orig_res = src.transform.a if src.transform != rasterio.Affine.identity() else TARGET_RESOLUTION
            
            print(f"   원본: {orig_width} x {orig_height} pixels ({orig_res:.2f}m)")
            # 저해상도 크기 계산
            new_width = src.width // resolution_divisor
            new_height = src.height // resolution_divisor
            
            # 데이터 읽기 및 리샘플링
            data = src.read(
                out_shape=(src.count, new_height, new_width),
                resampling=Resampling.bilinear
            )
            
            # 메타데이터 업데이트
            transform = src.transform * src.transform.scale(
                (src.width / new_width),
                (src.height / new_height)
            )
            
            meta = src.meta.copy()
            meta.update({
                'width': new_width,
                'height': new_height,
                'transform': transform
            })
            
            # 저장
            lowres_path = os.path.join(lowres_dir, f"{key}_lowres.tif")
            with rasterio.open(lowres_path, 'w', **meta) as dst:
                dst.write(data)
            
            lowres_paths[key] = lowres_path
            
            # 다운샘플링 비율 출력
            actual_divisor_w = orig_width / new_width
            actual_divisor_h = orig_height / new_height
            print(f"   ✅ 완료: {new_width} x {new_height} pixels")
            print(f"   📊 다운샘플링: {orig_width}x{orig_height} → {new_width}x{new_height} (1/{actual_divisor_w:.2f})")
            print(f"   📁 저장: {lowres_path}")
    
    print("\n✅ STEP 5 완료: 저해상도 영상이 생성되었습니다.")
    print(f"   💡 REFERENCE와 TARGET이 동일한 해상도({orig_res:.2f}m)로 정규화되어")
    print(f"      다운샘플링 비율도 동일하게 적용됩니다 (1/{resolution_divisor})")
    return lowres_paths
