#!/usr/bin/env python3
"""
Strip_correction_3D.py
Top/Bottom 영상 기하보정 (3D RPC 기반)

이 스크립트는 Strip_correction_v2.py의 확장 버전으로,
단순 2D 다항식 변환 대신 3D RPC(Rational Polynomial Coefficients) 모델을 생성하여
지형 고도(DEM)를 고려한 정밀 기하보정(Orthorectification)을 수행합니다.

작동 원리:
1. Center 영상과의 중첩 영역에서 GCP 추출 (v2와 동일)
2. 다항식 모델로 미지 영역(Top/Bottom)의 대략적인 위경도 추정 (Extrapolation)
3. 추정된 위경도 위치에서 DEM 높이 값을 샘플링하여 3D Pseudo GCP 생성 (Line, Samp, Lat, Lon, Height)
4. 3D Pseudo GCP들을 이용해 해당 Strip의 RPC 모델 생성 (rpcfit 라이브러리 사용)
5. 생성된 RPC와 DEM을 사용하여 정밀 기하보정 (gdalwarp)
"""

import os
import json
import glob
import argparse
import numpy as np
import rasterio
from rasterio.windows import Window
from typing import List, Tuple, Optional, Dict, Any
import subprocess
import shutil
import sys
import warnings
import matplotlib.pyplot as plt
from scipy import ndimage
from scipy.stats import linregress
# skimage is optional if we implement phase correlation manually or use the one from compare_mosaics

# rpcfit 임포트 (경고 무시)
warnings.filterwarnings('ignore', category=RuntimeWarning, module='rpcfit')
try:
    from rpcfit.rpc_fit import calibrate_rpc
except ImportError:
    print("Error: 'rpcfit' library not found. Please install it or use the correct environment.")
    sys.exit(1)

# ============================================================
# GDAL Path Helpers
# ============================================================
try:
    # Run as script from repo root: `python Code/Strip_correction_3D.py ...`
    from eval_utils import visualize_gcp_distribution
except ImportError:
    # Run as module/imported context where `Code` package is resolvable.
    from Code.eval_utils import visualize_gcp_distribution
def get_gdal_cmd(cmd: str) -> str:
    """Find GDAL command path relative to python executable or use default"""
    bin_dir = os.path.dirname(sys.executable)
    path = os.path.join(bin_dir, cmd)
    if os.path.exists(path):
        return path
    return cmd

GDAL_TRANSLATE = get_gdal_cmd("gdal_translate")
GDALWARP = get_gdal_cmd("gdalwarp")
GDALBUILDVRT = get_gdal_cmd("gdalbuildvrt")

# ============================================================
# 기본 계산 및 유틸리티 (v2에서 가져옴)
# ============================================================
def calculate_ranges(total_height: int) -> dict:
    """전체 높이를 기준으로 Top/Center/Bottom 및 중첩 영역 범위 계산"""
    center_height = 6000
    overlap_size = 1000
    
    center_start = (total_height - center_height) // 2
    center_end = center_start + center_height
    
    # Top: 0 ~ Center 시작 + 중첩
    top_range = (0, center_start + overlap_size)
    # Center: Center 시작 ~ Center 끝
    center_range = (center_start, center_end)
    # Bottom: Center 끝 - 중첩 ~ 끝
    bottom_range = (center_end - overlap_size, total_height)
    
    # 중첩 영역 (전체 Raw 좌표 기준)
    overlap_top_center = (center_start, center_start + overlap_size)
    overlap_center_bottom = (center_end - overlap_size, center_end)
    
    return {
        'total_height': total_height,
        'center_height': center_height,
        'top_range': top_range,
        'center_range': center_range,
        'bottom_range': bottom_range,
        'overlap_top': overlap_top_center,
        'overlap_bottom': overlap_center_bottom,
        'center_start': center_start,
        'center_end': center_end
    }

def parse_rpb(rpb_path: str) -> dict:
    """RPB 파일 파싱"""
    rpc = {}
    with open(rpb_path, 'r') as f:
        for line in f:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip().rstrip(';')
                
                if key.endswith('_COEFF'):
                    rpc[key] = np.array([float(x) for x in value.split()])
                elif key in ['LINE_OFF', 'SAMP_OFF', 'LAT_OFF', 'LONG_OFF', 'HEIGHT_OFF',
                           'LINE_SCALE', 'SAMP_SCALE', 'LAT_SCALE', 'LONG_SCALE', 'HEIGHT_SCALE']:
                    rpc[key] = float(value)
    return rpc

def rpc_inverse(rpc: dict, line: float, samp: float, height: float = 0, max_iter: int = 20) -> Tuple[float, float]:
    """RPC 역방향: (line, samp, h) → (lat, lon) - 단순 구현"""
    # rpc_forward가 필요하지만, 여기서는 Center RPC 역산용으로만 쓰이므로
    # v2에 있던 코드를 그대로 쓰거나, 혹은 생략하고 v2의 로직을 그대로 가져옴
    
    # 내부 함수로 forward 정의 (독립성 보장)
    def _forward(rpc, lat, lon, h):
        P = (lat - rpc['LAT_OFF']) / rpc['LAT_SCALE']
        L = (lon - rpc['LONG_OFF']) / rpc['LONG_SCALE']
        H = (h - rpc['HEIGHT_OFF']) / rpc['HEIGHT_SCALE']
        terms = np.array([1, L, P, H, L*P, L*H, P*H, L*L, P*P, H*H,
                          P*L*H, L*L*L, L*P*P, L*H*H, L*L*P, P*P*P, P*H*H, L*L*H, P*P*H, H*H*H])
        l = (np.dot(rpc['LINE_NUM_COEFF'], terms) / np.dot(rpc['LINE_DEN_COEFF'], terms)) * rpc['LINE_SCALE'] + rpc['LINE_OFF']
        s = (np.dot(rpc['SAMP_NUM_COEFF'], terms) / np.dot(rpc['SAMP_DEN_COEFF'], terms)) * rpc['SAMP_SCALE'] + rpc['SAMP_OFF']
        return l, s

    lat, lon = rpc['LAT_OFF'], rpc['LONG_OFF']
    for _ in range(max_iter):
        pred_line, pred_samp = _forward(rpc, lat, lon, height)
        d_line, d_samp = line - pred_line, samp - pred_samp
        if abs(d_line) < 1e-10 and abs(d_samp) < 1e-10: break
        
        delta = 1e-7
        pl1, ps1 = _forward(rpc, lat + delta, lon, height)
        pl2, ps2 = _forward(rpc, lat, lon + delta, height)
        
        dlat_dline = (pl1 - pred_line)/delta; dlat_dsamp = (ps1 - pred_samp)/delta
        dlon_dline = (pl2 - pred_line)/delta; dlon_dsamp = (ps2 - pred_samp)/delta
        
        det = dlat_dline * dlon_dsamp - dlat_dsamp * dlon_dline
        if abs(det) < 1e-15: break
        
        lat += (dlon_dsamp * d_line - dlon_dline * d_samp) / det
        lon += (-dlat_dsamp * d_line + dlat_dline * d_samp) / det
        
    return lat, lon

def sanitize_rpc_dict(rpc: dict) -> dict:
    """RPB 딕셔너리의 값을 수치형(float, np.array)으로 변환"""
    sanitized = {}
    for key, value in rpc.items():
        if key.endswith('_COEFF'):
            if isinstance(value, str):
                # 문자열인 경우 공백으로 분리하여 배열 변환
                sanitized[key] = np.array([float(x) for x in value.split()])
            elif isinstance(value, (list, tuple)):
                sanitized[key] = np.array(value)
            else:
                sanitized[key] = value
        elif key.endswith('_OFF') or key.endswith('_SCALE'):
            sanitized[key] = float(value)
        else:
            sanitized[key] = value
    return sanitized

# DEM/고도 래스터: 메타 nodata가 없거나 0이면 -32768로 통일 (0m 해발·지오이드 0은 유효값)
_ELEV_NODATA_STANDARD = -32768

# 붙여넣기 구버전 파이프라인: 스크립트 직접 실행 시 main()에서 기본 True.
# 다른 모듈에서 import만 할 때는 False(예: Full_processing_v2는 modern).
_LEGACY_DEM = False

def _normalize_elevation_nodata(raw_nodata):
    """None 또는 0이면 표준 노데이터 -32768. 그 외 파일에 명시된 값은 유지."""
    if raw_nodata is None:
        return _ELEV_NODATA_STANDARD
    try:
        v = float(raw_nodata)
    except (TypeError, ValueError):
        return _ELEV_NODATA_STANDARD
    if v == 0.0:
        return _ELEV_NODATA_STANDARD
    return raw_nodata

def _is_invalid_elev_pixel(val, nodata) -> bool:
    if nodata is None:
        return np.isnan(val)
    if np.isnan(val):
        return True
    return val == nodata

def load_dem(dem_path: str) -> dict:
    """DEM 로드"""
    with rasterio.open(dem_path) as src:
        data = src.read(1)
        if _LEGACY_DEM:
            # 구버전: 파일 nodata/NaN 픽셀을 0으로 바꾼 뒤, 샘플링 시 nodata=0으로 비교
            data = np.asarray(data, dtype=np.float64)
            sn = src.nodata
            if sn is not None:
                data = np.where(data == sn, 0.0, data)
            data = np.where(np.isnan(data), 0.0, data)
            return {
                'data': data,
                'transform': src.transform,
                'bounds': src.bounds,
                'nodata': 0.0,
            }
        return {
            'data': data,
            'transform': src.transform,
            'bounds': src.bounds,
            'nodata': _normalize_elevation_nodata(src.nodata)
        }

def load_geoid(geoid_path: str) -> dict:
    """Geoid 로드 (DEM과 동일 구조 → sample_dem으로 샘플링)"""
    with rasterio.open(geoid_path) as src:
        data = src.read(1)
        if _LEGACY_DEM:
            return {
                'data': np.asarray(data, dtype=np.float64),
                'transform': src.transform,
            }
        return {
            'data': data,
            'transform': src.transform,
            'bounds': src.bounds,
            'nodata': _normalize_elevation_nodata(src.nodata)
        }

def sample_dem(dem: dict, lat: float, lon: float) -> float:
    """DEM에서 고도 샘플링 (Bilinear Interpolation)"""
    bounds = dem['bounds']
    transform = dem['transform']
    data = dem['data']
    nodata = dem['nodata']

    if not (bounds.left <= lon <= bounds.right and bounds.bottom <= lat <= bounds.top):
        return 0.0
    
    # Calculate float indices
    col_float = (lon - transform.c) / transform.a
    row_float = (lat - transform.f) / transform.e
    
    col0 = int(np.floor(col_float))
    row0 = int(np.floor(row_float))
    col1 = col0 + 1
    row1 = row0 + 1
    
    # Check bounds (need 2x2 grid)
    h, w = data.shape
    if not (0 <= row0 < h - 1 and 0 <= col0 < w - 1):
        # Fallback to nearest if on edge
        if 0 <= row0 < h and 0 <= col0 < w:
            val = data[row0, col0]
            if _is_invalid_elev_pixel(val, nodata):
                return 0.0
            return float(val)
        return 0.0

    # Get 2x2 values
    v00 = data[row0, col0]
    v01 = data[row0, col1]
    v10 = data[row1, col0]
    v11 = data[row1, col1]
    
    # Check nodata or NaN
    is_nodata = False
    if _is_invalid_elev_pixel(v00, nodata) or _is_invalid_elev_pixel(v01, nodata) or _is_invalid_elev_pixel(v10, nodata) or _is_invalid_elev_pixel(v11, nodata):
        is_nodata = True
            
    if not is_nodata:
        if np.isnan(v00) or np.isnan(v01) or np.isnan(v10) or np.isnan(v11):
            is_nodata = True
            
    if is_nodata:
         # Fallback to nearest if any point is nodata / NaN
         r_near = int(round(row_float))
         c_near = int(round(col_float))
         if 0 <= r_near < h and 0 <= c_near < w:
             val = data[r_near, c_near]
             if _is_invalid_elev_pixel(val, nodata):
                 return 0.0
             return float(val)
         return 0.0
             
    # Bilinear Interpolation
    dx = col_float - col0
    dy = row_float - row0
    
    top = (1 - dx) * v00 + dx * v01
    bottom = (1 - dx) * v10 + dx * v11
    val = (1 - dy) * top + dy * bottom
    
    if np.isnan(val): return 0.0
    
    return float(val)

def sample_geoid(geoid: dict, lat: float, lon: float) -> float:
    """붙여넣기 스크립트와 동일: transform만 사용한 쌍선형(클램프 없음)."""
    transform = geoid['transform']
    data = geoid['data']
    col_float = (lon - transform.c) / transform.a
    row_float = (lat - transform.f) / transform.e
    col0 = int(np.floor(col_float))
    row0 = int(np.floor(row_float))
    col1 = col0 + 1
    row1 = row0 + 1
    dx = col_float - col0
    dy = row_float - row0
    top = (1 - dx) * data[row0, col0] + dx * data[row0, col1]
    bottom = (1 - dx) * data[row1, col0] + dx * data[row1, col1]
    val = (1 - dy) * top + dy * bottom
    return float(val)

# ============================================================
# GCP 생성 및 다항식 모델링 (v2)
# ============================================================
def generate_overlap_gcps(center_rpc: dict, dem: dict, geoid: dict,
                          overlap_range: Tuple[int, int],
                          center_start_line: int,
                          target_segment_offset: int,
                          width: int,
                          step: int = 200) -> List[dict]:
    """중첩 영역에서 GCP 생성"""
    overlap_start, overlap_end = overlap_range
    center_local_start = overlap_start - center_start_line
    center_local_end = overlap_end - center_start_line
    
    lines = np.arange(center_local_start + 50, center_local_end - 50, step)
    margin = 200
    samps = np.arange(margin, width - margin, step)
    
    gcps = []
    for center_line in lines:
        for samp in samps:
            # 1. Center RPC로 지상좌표 계산 (반복법)
            lat, lon = rpc_inverse(center_rpc, center_line, samp, height=0)
            height = sample_dem(dem, lat, lon)
            if _LEGACY_DEM:
                geoid_height = sample_geoid(geoid, lat, lon)
            else:
                geoid_height = sample_dem(geoid, lat, lon)
            lat, lon = rpc_inverse(center_rpc, center_line, samp, height=height+geoid_height) # 정밀 보정
            
            # 2. 타겟 세그먼트 좌표로 변환
            raw_line = center_line + center_start_line
            target_line = raw_line - target_segment_offset
            
            gcps.append({
                'line': target_line,
                'samp': samp,
                'lat': lat,
                'lon': lon,
                'height': height+geoid_height, # 실제 지형 고도
                'raw_line': raw_line
            })
    return gcps

def _build_poly_features(lines, samps, line_stats, samp_stats, line_order, samp_order, interaction=True):
    """
    다항식 Feature Matrix
    interaction=False 이면 Cross-term (L*S 등)을 제외하고 독립적인 항만 생성 (1, L, L^2..., S, S^2...)
    """
    L = (lines - line_stats['mean']) / line_stats['std']
    S = (samps - samp_stats['mean']) / samp_stats['std']
    
    features = []
    
    if interaction:
        # 기존: 모든 조합 생성 (L^i * S^j)
        line_terms = [L**i for i in range(line_order + 1)]
        samp_terms = [S**j for j in range(samp_order + 1)]
        for l_term in line_terms:
            for s_term in samp_terms:
                features.append(l_term * s_term)
    else:
        # 수정됨: Cross-term 제거 (Separator Polynomial) - 안정적 외삽용
        # 1. Bias (always include 1)
        features.append(np.ones_like(L))
        
        # 2. Line terms (L^1 ... L^line_order)
        for i in range(1, line_order + 1):
            features.append(L**i)
            
        # 3. Samp terms (S^1 ... S^samp_order)
        for j in range(1, samp_order + 1):
            features.append(S**j)
            
    return np.column_stack(features)

def fit_polynomial_model(gcps: List[dict], line_order: int, samp_order: int) -> dict:
    """다항식 모델 피팅 (Lat, Lon 예측용)"""
    lines = np.array([g['line'] for g in gcps])
    samps = np.array([g['samp'] for g in gcps])
    lats = np.array([g['lat'] for g in gcps])
    lons = np.array([g['lon'] for g in gcps])
    # height는 피팅하지 않음 (DEM에서 직접 샘플링할 것임)
    
    line_stats = {'mean': lines.mean(), 'std': lines.std()}
    samp_stats = {'mean': samps.mean(), 'std': samps.std()}
    
    # User Request: Cross-term 제거하여 안정성 확보 (외삽 시 튀는 값 방지)
    # Line 방향은 1차(Linear), Sample 방향은 2차(Quadratic) 등으로 독립적으로 모델링
    interaction = True
    
    A = _build_poly_features(lines, samps, line_stats, samp_stats, line_order, samp_order, interaction=interaction)
    
    lat_coeffs, _, _, _ = np.linalg.lstsq(A, lats, rcond=None)
    lon_coeffs, _, _, _ = np.linalg.lstsq(A, lons, rcond=None)
    
    # RMSE check
    lat_pred = A @ lat_coeffs
    lon_pred = A @ lon_coeffs
    rmse_lat = np.sqrt(np.mean((lats - lat_pred)**2)) * 111000
    rmse_lon = np.sqrt(np.mean((lons - lon_pred)**2)) * 85000
    rmse = np.sqrt(rmse_lat**2 + rmse_lon**2)
    
    return {
        'line_stats': line_stats,
        'samp_stats': samp_stats,
        'lat_coeffs': lat_coeffs,
        'lon_coeffs': lon_coeffs,
        'rmse_m': rmse,
        'orders': (line_order, samp_order),
        'interaction': interaction
    }

# ============================================================
# 3D Pseudo GCP 생성 및 RPC 모델링
# ============================================================
def generate_pseudo_gcps_3d(model: dict, dem: dict, geoid: dict,
                            target_wh: Tuple[int, int],
                            overlap_gcps: List[dict],
                            step: int = 200,
                            exclusion_zone: Optional[Tuple[int, int]] = None,
                            line_margin: int = 50,
                            samp_margin: int = 200) -> List[list]:
    """
    전체 영상 영역에 대해 Grid를 생성하고,
    Polynomial Model로 Lat/Lon을 예측한 뒤,
    DEM에서 Height를 샘플링하여 3D GCP 생성
    
    * New Feature: Strip Direction Aligned Grid (PCA)
      Overlap GCPs의 분포를 분석하여 스트립 진행 방향(Principal Axis)을 찾고,
      그 방향에 정렬된 Grid를 생성함.
    
    exclusion_zone: (min_line, max_line) -> 해당 라인 범위 제외 (중첩 영역)
    margin: int -> Sample 방향 양쪽 가장자리 제외 범위 (값이 튀는 것 방지)
    
    Returns:
        List of [line, samp, lat, lon, height]
    """
    width, height = target_wh
    
    # 1. PCA Analysis on Overlap GCPs
    lines = np.array([g['line'] for g in overlap_gcps])
    samps = np.array([g['samp'] for g in overlap_gcps])
    
    # Center calculation
    center_l = np.mean(lines)
    center_s = np.mean(samps)
    
    vals = np.column_stack([lines - center_l, samps - center_s])
    cov = np.cov(vals, rowvar=False)
    eig_vals, eig_vecs = np.linalg.eigh(cov)
    
    # Sort eigenvalues (descending)
    # idx = np.argsort(eig_vals)[::-1]
    # eig_vecs = eig_vecs[:, idx]
    
    # Principal Axis Identification (Robust)
    # Overlap Region might be wider (Sample) than long (Line), so just sorting by variance
    # makes U-axis align with Sample direction, causing V-axis to restrict Line range instead of Width.
    # Result: Grid generated only in Overlap Line range -> Filtered out -> 0 points.
    
    # Solution: Find which eigenvector is closer to Line axis [1, 0]
    # evt_vecs columns are the vectors.
    
    vec0 = eig_vecs[:, 0]
    vec1 = eig_vecs[:, 1]
    
    # Dot product with Line axis [1, 0]
    # vector is [line_comp, samp_comp]
    score0 = abs(vec0[0]) 
    score1 = abs(vec1[0])
    
    if score0 > score1:
        u_axis = vec0 # Closer to Line (Along-Track)
        v_axis = vec1 # Closer to Sample (Across-Track)
    else:
        u_axis = vec1
        v_axis = vec0
        
    # Re-assemble eig_vecs in [u, v] order for projection
    eig_vecs_sorted = np.column_stack([u_axis, v_axis])
    
    # 2. Define Grid Range in Rotated Frame (U, V)
    
    # Project image corners to (U, V) for Along-Track (U) range
    corners = np.array([
        [0, 0], [0, width], [height, 0], [height, width]
    ])
    corners_centered = corners - [center_l, center_s]
    uv_corners = corners_centered @ eig_vecs_sorted
    
    min_u, max_u = np.min(uv_corners[:, 0]), np.max(uv_corners[:, 0])
    
    # Project Image Corners to (U, V) for Across-Track (V) range (Cover full width)
    # Previously used Overlap GCPs for V range which restricted coverage
    min_v, max_v = np.min(uv_corners[:, 1]), np.max(uv_corners[:, 1])
    
    # Generate Grid in (U, V)
    u_steps = np.arange(min_u, max_u + step*1.5, step)
    
    # Adjust V steps to cover min_v to max_v
    # Ensure max_v is included or covered
    v_steps = np.arange(min_v, max_v + step/2, step) 
    
    U_grid, V_grid = np.meshgrid(u_steps, v_steps, indexing='ij')
    U_flat = U_grid.flatten()
    V_flat = V_grid.flatten()
    
    # 3. Rotate Back to Image Coordinates (L, S)
    uv_flat = np.column_stack([U_flat, V_flat])
    ls_flat = (uv_flat @ eig_vecs_sorted.T) + [center_l, center_s]
    
    L_flat = ls_flat[:, 0]
    S_flat = ls_flat[:, 1]
    
    # 4. Predict Lat/Lon using Polynomial Model
    interaction = model.get('interaction', True) 
    A = _build_poly_features(L_flat, S_flat, model['line_stats'], model['samp_stats'], 
                             model['orders'][0], model['orders'][1], interaction=interaction)
    
    lat_pred = A @ model['lat_coeffs']
    lon_pred = A @ model['lon_coeffs']
    
    pseudo_gcps = []
    
    for i in range(len(L_flat)):
        l = L_flat[i]
        s = S_flat[i]
        
        # Check Image Bounds with Margins
        if not (line_margin <= l < height - line_margin and samp_margin <= s < width - samp_margin):
            continue
        
        # Check Exclusion Zone (Line based filter is still valid approximation or check strictly?)
        # Let's keep line-based exclusion for now as it maps to overlap region physically
        if exclusion_zone:
            if exclusion_zone[0] <= l < exclusion_zone[1]:
                continue
                
        lat = lat_pred[i]
        lon = lon_pred[i]
        
        # DEM Height Sampling
        h0 = sample_dem(dem, lat, lon)
        if _LEGACY_DEM:
            gh = sample_geoid(geoid, lat, lon)
        else:
            gh = sample_dem(geoid, lat, lon)
        h = h0 + gh
        
        # Valid Check
        pseudo_gcps.append([l, s, lat, lon, h])
        
    # Check Height Variance (logging only, injection is handled before RPC fitting)
    if pseudo_gcps:
        heights = np.array([p[4] for p in pseudo_gcps])
        h_std = np.std(heights)
        if h_std < 0.1:
            print(f"      [Info] Low height variance ({h_std:.4f}).")
        
    return pseudo_gcps

def generate_rpc_coefficients(gcps_3d: List[list], target_wh: Tuple[int, int]) -> Dict[str, Any]:
    """
    3D GCP들을 사용하여 RPC 계수 생성 (rpcfit 사용)
    gcps_3d: [[line, samp, lat, lon, height], ...]
    """
    gcps = np.array(gcps_3d)
    
    # Filter out NaNs and Infs
    valid_mask = np.isfinite(gcps).all(axis=1)
    if not np.all(valid_mask):
        n_dropped = len(gcps) - np.sum(valid_mask)
        print(f"      [Warning] Dropped {n_dropped} invalid GCPs (NaN/Inf)")
        gcps = gcps[valid_mask]
        
    if len(gcps) < 10:
        raise ValueError(f"Not enough valid GCPs for RPC fitting: {len(gcps)}")
    
    # 3D GCP 확장 (Singular Matrix 방지)
    # RPC fitting은 3D 공간(체적)이 필요하기 때문에, 고도가 평탄하거나 단순히 지형 표면에만 
    # 위치한 경우 X.T @ X 행렬이 특이행렬(Singular)이 됩니다. 이를 막기 위해 여러 고도 레이어를 쌓습니다.
    expanded_gcps = []
    offsets = [-100.0, -10.0, 10.0, 100.0]
    for p in gcps:
        expanded_gcps.append(p)
        for off in offsets:
            p_ext = p.copy()
            p_ext[4] += off
            expanded_gcps.append(p_ext)
    gcps = np.array(expanded_gcps)
    
    # image_coords: [col, row] -> [samp, line]
    
    target_pts = gcps[:, [1, 0]] # samp, line
    input_locs = gcps[:, [3, 2, 4]] # lon, lat, height
    
    print(f"      RPC Fit Input: {len(gcps)} points")
    
    # Debug: Check stats
    print(f"      GCP Stats (Min): {np.min(gcps, axis=0)}")
    print(f"      GCP Stats (Max): {np.max(gcps, axis=0)}")
    print(f"      GCP Stats (Std): {np.std(gcps, axis=0)}")
    
    # Calibrate
    # gdal compatible dict 반환
    rpc_obj = calibrate_rpc(target_pts, input_locs, separate=True, tol=1e-2, max_iter=20)
    
    return rpc_obj.to_geotiff_dict()

def save_to_rpb(rpc_dict: dict, output_path: str):
    """RPC dictionary를 RPB 포맷 파일로 저장"""
    
    def _format_coeff(coeffs):
        # 20개 계수를 포맷팅
        if isinstance(coeffs, (list, tuple, np.ndarray)):
             # 문자열이면 파싱, 아니면 리스트로 변환
            c_list = list(coeffs)
        elif isinstance(coeffs, str):
            c_list = [float(x) for x in coeffs.split()]
        else:
            c_list = [0.0]*20
            
        # 20개 맞추기
        if len(c_list) < 20:
            c_list.extend([0.0] * (20 - len(c_list)))
            
        return c_list

    # 키 매핑 (GDAL dict -> RPB keys)
    # GDAL: LINE_OFF, LINE_Scale, LINE_NUM_COEFF (str)...
    
    with open(output_path, 'w') as f:
        f.write("satId = \"GlueGenerated\"\n") # Dummy
        
        # Offsets & Scales
        f.write(f"LINE_OFF: {float(rpc_dict.get('LINE_OFF', 0)):.10f};\n")
        f.write(f"SAMP_OFF: {float(rpc_dict.get('SAMP_OFF', 0)):.10f};\n")
        f.write(f"LAT_OFF: {float(rpc_dict.get('LAT_OFF', 0)):.10f};\n")
        f.write(f"LONG_OFF: {float(rpc_dict.get('LONG_OFF', 0)):.10f};\n")
        f.write(f"HEIGHT_OFF: {float(rpc_dict.get('HEIGHT_OFF', 0)):.10f};\n")
        
        f.write(f"LINE_SCALE: {float(rpc_dict.get('LINE_SCALE', 1)):.10f};\n")
        f.write(f"SAMP_SCALE: {float(rpc_dict.get('SAMP_SCALE', 1)):.10f};\n")
        f.write(f"LAT_SCALE: {float(rpc_dict.get('LAT_SCALE', 1)):.10f};\n")
        f.write(f"LONG_SCALE: {float(rpc_dict.get('LONG_SCALE', 1)):.10f};\n")
        f.write(f"HEIGHT_SCALE: {float(rpc_dict.get('HEIGHT_SCALE', 1)):.10f};\n")
        
        # Coefficients
        # LINE_NUM
        ln = _format_coeff(rpc_dict.get('LINE_NUM_COEFF', []))
        f.write("LINE_NUM_COEFF: " + " ".join([f"{x:.12e}" for x in ln]) + ";\n")
        
        # LINE_DEN
        ld = _format_coeff(rpc_dict.get('LINE_DEN_COEFF', []))
        f.write("LINE_DEN_COEFF: " + " ".join([f"{x:.12e}" for x in ld]) + ";\n")
        
        # SAMP_NUM
        sn = _format_coeff(rpc_dict.get('SAMP_NUM_COEFF', []))
        f.write("SAMP_NUM_COEFF: " + " ".join([f"{x:.12e}" for x in sn]) + ";\n")
        
        # SAMP_DEN
        sd = _format_coeff(rpc_dict.get('SAMP_DEN_COEFF', []))
        f.write("SAMP_DEN_COEFF: " + " ".join([f"{x:.12e}" for x in sd]) + ";\n")

# ============================================================
# Orthorectification & Mosaic
# ============================================================
def extract_segment_raw(raw_path: str, output_path: str, line_range: Tuple[int, int]) -> str:
    """Raw 영상에서 특정 구간 추출 (v2와 동일)"""
    if os.path.exists(output_path): return output_path

    start, end = line_range
    height = end - start
    
    with rasterio.open(raw_path) as src:
        data = src.read(window=Window(0, start, src.width, height))
        profile = src.profile.copy()
        profile.update({'height': height, 'compress': 'lzw'})
        
        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(data)
    return output_path

def perform_orthorectification(raw_path: str, rpc_dict: dict, dem_path: str, geoid_path: str, output_path: str, ref_tiff: str,
                               pseudo_gcps: Optional[List[list]] = None, overlap_gcps: Optional[List[dict]] = None):
    """gdalwarp with RPC & DEM via VRT injection

    Bounds 계산 전략 (Bottom 잘림 완전 해결):
    1. GCP (pseudo + overlap) lat/lon 범위로 1차 bounds 계산
    2. RPC 역투영으로 raw image 코너 + 하단 중간점들의 lat/lon 계산
    3. 두 결과를 union → 항상 raw image 전체 geo extent를 포함
    4. 충분한 margin 추가
    """
    
    # Reference 해상도 + CRS 가져오기 (Center와 동일 grid로 맞춤)
    # 신버전 rasterio의 to_string()이 긴 WKT를 반환해 gdalwarp가 GEOGCS로 fallback하는 버그 회피
    with rasterio.open(ref_tiff) as ref:
        ref_res_x, ref_res_y = abs(ref.transform.a), abs(ref.transform.e)
        if ref.crs:
            epsg = ref.crs.to_epsg()
            if epsg is not None:
                ref_crs = f'EPSG:{epsg}'
            else:
                ref_crs = ref.crs.to_proj4()
        else:
            ref_crs = 'EPSG:4326'
        
    # Input Image Size
    with rasterio.open(raw_path) as src:
        h, w = src.height, src.width
    
    numeric_rpc = sanitize_rpc_dict(rpc_dict)
    
    all_lats = []
    all_lons = []
    
    # ── [A] GCP 기반 bounds ──
    if pseudo_gcps:
        for gcp in pseudo_gcps:
            all_lats.append(gcp[2])   # lat
            all_lons.append(gcp[3])   # lon
    if overlap_gcps:
        for g in overlap_gcps:
            all_lats.append(g['lat'])
            all_lons.append(g['lon'])
    
    if all_lats:
        gcp_min_lat, gcp_max_lat = min(all_lats), max(all_lats)
        gcp_min_lon, gcp_max_lon = min(all_lons), max(all_lons)
        print(f"      Bounds from GCPs: {gcp_min_lon:.6f}, {gcp_min_lat:.6f}, {gcp_max_lon:.6f}, {gcp_max_lat:.6f}")
    else:
        gcp_min_lat = gcp_max_lat = gcp_min_lon = gcp_max_lon = None
    
    # ── [B] RPC 역투영: raw image 코너 + 하단 중간점들 ──
    # legacy: 붙여넣기 스크립트와 동일(h, w-1, int(h*frac)).
    # modern: 마지막 유효 픽셀(h-1,w-1) 기준(범위 밖 라인 샘플 감소).
    if _LEGACY_DEM:
        sample_points = [
            (0, 0), (0, w // 2), (0, w - 1),
            (h // 2, 0), (h // 2, w - 1),
            (h - 1, 0), (h - 1, w // 2), (h - 1, w - 1),
        ]
        for frac in [0.7, 0.8, 0.9, 0.95, 1.0]:
            row = int(h * frac)
            for col in [0, w // 4, w // 2, 3 * w // 4, w - 1]:
                sample_points.append((row, col))
    else:
        hm1, wm1 = max(h - 1, 0), max(w - 1, 0)
        sample_points = [
            (0, 0), (0, wm1 // 2), (0, wm1),
            (hm1 // 2, 0), (hm1 // 2, wm1),
            (hm1, 0), (hm1 // 2, wm1 // 2), (hm1, wm1 // 2), (hm1, wm1),
        ]
        for frac in [0.7, 0.8, 0.9, 0.95, 1.0]:
            row = int(hm1 * frac)
            for col in [0, wm1 // 4, wm1 // 2, 3 * wm1 // 4, wm1]:
                sample_points.append((row, col))
    
    rpc_lats, rpc_lons = [], []
    for avg_h in [0, 50]:   # 고도 0m / 50m 두 가지로 시도
        for r, c in sample_points:
            try:
                lat, lon = rpc_inverse(numeric_rpc, float(r), float(c), height=float(avg_h))
                # 발산 값 필터 (위경도 범위 체크)
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    rpc_lats.append(lat)
                    rpc_lons.append(lon)
            except Exception:
                pass
    
    if rpc_lats:
        rpc_min_lat, rpc_max_lat = min(rpc_lats), max(rpc_lats)
        rpc_min_lon, rpc_max_lon = min(rpc_lons), max(rpc_lons)
        print(f"      Bounds from RPC sampling: {rpc_min_lon:.6f}, {rpc_min_lat:.6f}, {rpc_max_lon:.6f}, {rpc_max_lat:.6f}")
    else:
        rpc_min_lat = rpc_max_lat = rpc_min_lon = rpc_max_lon = None

    # ── [C] Union ──
    candidate_lats = []
    candidate_lons = []
    for v in [gcp_min_lat, gcp_max_lat, rpc_min_lat, rpc_max_lat]:
        if v is not None:
            candidate_lats.append(v)
    for v in [gcp_min_lon, gcp_max_lon, rpc_min_lon, rpc_max_lon]:
        if v is not None:
            candidate_lons.append(v)
    
    min_lat = min(candidate_lats)
    max_lat = max(candidate_lats)
    min_lon = min(candidate_lons)
    max_lon = max(candidate_lons)

    # ── Sanity check: 외삽 폭주 감지 ─────────────────────────────────
    # 일반 segment는 ~6000 lines × 4.8m ≈ 30km ≈ 0.3°. 2° 넘으면 명백히 발산.
    lat_extent = max_lat - min_lat
    lon_extent = max_lon - min_lon
    if lat_extent > 2.0 or lon_extent > 2.0:
        raise RuntimeError(
            f"외삽 폭주 감지: 출력 bounds extent = {lat_extent:.3f}° lat × {lon_extent:.3f}° lon "
            f"(정상 ~0.3°). 다항식 외삽이 발산해 RPC가 깨졌습니다.\n"
            f"   GCP 기반: lat[{gcp_min_lat}, {gcp_max_lat}] lon[{gcp_min_lon}, {gcp_max_lon}]\n"
            f"   RPC 샘플: lat[{rpc_min_lat}, {rpc_max_lat}] lon[{rpc_min_lon}, {rpc_max_lon}]"
        )

    # ── [D] Margin ──
    margin = 0.03   # ~3km, 하단 잘림 안전 마진
    min_lat -= margin
    max_lat += margin
    min_lon -= margin
    max_lon += margin
    
    print(f"      Final Bounds (union + margin): {min_lon:.6f}, {min_lat:.6f}, {max_lon:.6f}, {max_lat:.6f}")
    
    # 2. Build VRT
    vrt_path = output_path.replace('.tiff', '_rpc.vrt')
    # gdal_translate로 VRT 생성만 (데이터 복사 없음)
    subprocess.run([GDAL_TRANSLATE, '-of', 'VRT', raw_path, vrt_path], check=True, capture_output=True)
    
    # 3. Inject RPC into VRT manually
    # VRT XML을 읽어서 <Metadata domain="RPC"> ... </Metadata> 추가
    with open(vrt_path, 'r') as f:
        vrt_content = f.read()
        
    rpc_xml = '  <Metadata domain="RPC">\n'
    for key, value in rpc_dict.items():
        # List형태인 경우 (COEFF) 문자열로 변환 필요
        if isinstance(value, (list, tuple, np.ndarray)):
            # "v1 v2 v3 ..."
            val_str = " ".join([f"{float(x):.12f}" for x in value])
        elif isinstance(value, str):
            # 문자열인데 스페이스가 있으면 리스트로 간주
            if ' ' in value.strip():
                parts = value.strip().split()
                try:
                    # 숫자 변환 테스트
                    val_str = " ".join([f"{float(x):.12f}" for x in parts])
                except ValueError:
                    # 숫자가 아니면 그대로
                    val_str = value
            else:
                try:
                    val_str = f"{float(value):.12f}"
                except ValueError:
                    val_str = value
        else:
            val_str = f"{float(value):.12f}"
            
        rpc_xml += f'    <MDI key="{key}">{val_str}</MDI>\n'
    rpc_xml += '  </Metadata>\n'
    
    # <VRTRasterBand> 앞에 삽입 (Global Metadata)
    if '<VRTRasterBand' in vrt_content:
        vrt_content = vrt_content.replace('<VRTRasterBand', rpc_xml + '<VRTRasterBand', 1)
    else:
        # Fallback: 맨 뒤 </VRTDataset> 앞
        vrt_content = vrt_content.replace('</VRTDataset>', rpc_xml + '</VRTDataset>')
        
    with open(vrt_path, 'w') as f:
        f.write(vrt_content)
    
    # 4. Warp
    print(f"      Orthorectifying...")
    dem_missing = 0 if _LEGACY_DEM else _ELEV_NODATA_STANDARD
    cmd = [
        GDALWARP,
        '-rpc', # RPC 사용 강제
        '-to', f'RPC_DEM={dem_path}', # DEM 지정
        '-to', f'RPC_GEOID={geoid_path}', # Geoid 지정
        '-to', f'RPC_DEM_MISSING_VALUE={dem_missing}',
        '-t_srs', ref_crs,                 # Center와 동일 CRS (UTM 등)
        '-te_srs', 'EPSG:4326',            # -te 는 lat/lon 단위
        '-te', str(min_lon), str(min_lat), str(max_lon), str(max_lat), # Explicit Bounds
        '-tr', str(ref_res_x), str(ref_res_y),  # ref_crs 단위 (UTM이면 m)
        '-r', 'bilinear',
        '-co', 'COMPRESS=LZW', '-co', 'TILED=YES',
        '-overwrite',
        vrt_path, output_path # Input is VRT with RPC
    ]
    
    # 오류 메시지 캡처
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        print(f"Error in gdalwarp: {res.stderr.decode()}")
        # VRT 내용 디버깅용 출력 (앞부분만)
        print(f"VRT Context (Head): {vrt_content[:500]}")
        raise RuntimeError("gdalwarp failed")
        
    if os.path.exists(vrt_path):
        os.remove(vrt_path)

def create_mosaic(target: str, base_dir: str, new_corrected_path: str, output_path: str):
    """모자이킹 (v2와 동일)"""
    def find_tiff(folder):
        p = os.path.join(base_dir, folder, "07_Final_results")
        if not os.path.exists(p): return None
        # 하위 폴더가 있을 수 있음 (mode 이름 등). 재귀적으로 찾거나, 
        # v2 구조상 '07_Final_results' 아래에 바로 파일이 있거나 모드 폴더 안에 있음.
        # 여기서는 단순히 07_Final_results 바로 아래나, 가장 최근거 찾기
        for root, dirs, files in os.walk(p):
            for f in files:
                if f.endswith(f"_{folder.lower()}.tiff"):
                    return os.path.join(root, f)
        return None

    center_tiff = find_tiff("Center")
    
    if target == 'top':
        # Top (New) + Center + Bottom (Old)
        # 만약 Bottom도 3D로 했다면 그걸 찾아야 하는데... 
        # 일단 기존 로직대로 'Bottom' 폴더에서 찾음
        tifs = [new_corrected_path, center_tiff, find_tiff("Bottom")]
    else: # bottom
        tifs = [find_tiff("Top"), center_tiff, new_corrected_path]
        
    tifs = [t for t in tifs if t and os.path.exists(t)]
    
    if not tifs:
        print("      모자이킹할 파일이 없습니다.")
        return

    # NoData 처리
    nodata_str = "0 0 0" # 3밴드 가정
    
    vrt_path = output_path.replace('.tiff', '.vrt')
    subprocess.run([GDALBUILDVRT, '-srcnodata', nodata_str, '-vrtnodata', nodata_str, vrt_path] + tifs,  
                   capture_output=True, check=True)
    subprocess.run([GDAL_TRANSLATE, vrt_path, output_path, 
                    '-co', 'COMPRESS=LZW', '-co', 'TILED=YES', '-co', 'BIGTIFF=IF_SAFER'],
                   capture_output=True, check=True)
    
    if os.path.exists(vrt_path):
        os.remove(vrt_path)


# ============================================================
# 메인 파이프라인
# ============================================================
def process_top_segment(base_dir: str, raw_tiff: str, ranges: dict,
                        center_rpc: dict, center_result_dir: str, dem: dict, dem_path: str, geoid: dict, geoid_path: str,
                        center_tiff_file: str, width: int,
                        save_intermediate: bool = True) -> Tuple[Optional[str], Optional[List[list]], Optional[List[dict]]]:
    """
    Top 세그먼트 처리 (Center -> Anchor -> Top, 상향식 외삽)
    Anchor: Center 상단과 Top 하단의 중첩 영역 (Top 세그먼트 기준 하단부)
    Extrapolation: Anchor 위쪽 영역 (Line 감소 방향)
    """
    target = 'top'
    data_name = os.path.basename(base_dir)
    base_name = data_name.replace('l1a', 'l1c')
    
    base_analysis_dir = os.path.join(base_dir, f"analysis_steps/step05_3d_rpc_{target}")
    os.makedirs(base_analysis_dir, exist_ok=True)
    
    print("\n" + "=" * 60)
    print(f"  처리 중: {target.upper()} (Upward Extrapolation)")
    print("=" * 60)
    
    # [1] Anchor GCP 생성 (Top 세그먼트의 하단부 = Center 상단부)
    print(f"\n  [1] Anchor GCP 추출 ({target})")
    overlap_range = ranges['overlap_top'] # Center 기준 좌표
    target_offset = ranges['top_range'][0] # Top 시작점 (보통 0)
    
    # Center RPC를 이용해 지상좌표 추출 후 Top 로컬 좌표로 변환
    overlap_gcps = generate_overlap_gcps(
        center_rpc, dem, geoid, overlap_range,
        ranges['center_start'], target_offset,
        width, step=200
    )
    print(f"      Anchor GCPs: {len(overlap_gcps)}개")
    
    # [2] 다항식 모델 피팅
    # Top은 위쪽으로 갈수록 Line이 감소하므로, 이를 고려한 모델링이 필요하나
    # 현재 다항식 모델은 좌표 자체를 피팅하므로 방향성은 자동 반영됨.
    poly_model = fit_polynomial_model(overlap_gcps, 1, 2)
    print(f"      Poly Model RMSE: {poly_model['rmse_m']:.2f} m")
    
    # [3] 3D Pseudo GCP 생성 (외삽)
    print(f"\n  [2] 3D Pseudo GCP 생성 ({target})")
    seg_h = ranges['top_range'][1] - ranges['top_range'][0]
    
    # Exclusion Zone: 중첩 영역 (하단부) 제외하고 상단부만 외삽
    # Overlap은 Top 이미지의 끝부분에 위치함.
    # Top 이미지: 0 ~ (End - Overlap) ~ End
    # Extrapolation Target: 0 ~ (End - Overlap)
    
    # overlap_gcp의 line 범위 확인
    ov_lines = [g['line'] for g in overlap_gcps]
    if ov_lines:
        min_ov = min(ov_lines)
        max_ov = max(ov_lines)
        # 안전 마진을 두고 제외 구역 설정
        exclusion_zone = (min_ov - 50, seg_h) # 하단부 제외
    else:
        # Fallback
        ex_start = ranges['center_start'] - ranges['top_range'][0]
        exclusion_zone = (ex_start, seg_h)
        
    pseudo_gcps = generate_pseudo_gcps_3d(
        poly_model, dem, geoid, (width, seg_h),
        overlap_gcps, step=200,
        exclusion_zone=exclusion_zone
    )
    print(f"      Pseudo GCPs: {len(pseudo_gcps)}개")
    
    # [4] RPC 모델링
    
    # Distribution Visualization
    print(f"      Visualizing GCP Distribution...")
    visualize_gcp_distribution(
        overlap_gcps, pseudo_gcps, 
        width, seg_h, 
        os.path.join(base_analysis_dir, "gcp_distribution.png"),
        bg_image_path=raw_tiff,
        bg_offset=ranges['top_range'][0]
    )

    print(f"      Combining GCPs & RPC Fitting")
    combined_gcps = list(pseudo_gcps)
    
    # Anchor Weighting
    anchor_weight = 1
    for _ in range(anchor_weight):
        for g in overlap_gcps:
            combined_gcps.append([float(g['line']), float(g['samp']),
                                   float(g['lat']), float(g['lon']), float(g['height'])])
            
    # Save GCPs
    with open(os.path.join(base_analysis_dir, "combined_gcps.json"), 'w') as f:
        json.dump(combined_gcps, f)
        
    rpc_dict = generate_rpc_coefficients(combined_gcps, (width, seg_h))
    rpb_path = os.path.join(base_analysis_dir, f"{base_name}_{target}.RPB")
    # RPB 사전 저장 (sanity check raise 시에도 디버깅용으로 보존)
    save_to_rpb(rpc_dict, rpb_path)

    # [5] Orthorectification
    print(f"\n  [3] Orthorectification ({target})")
    raw_segment_path = os.path.join(base_analysis_dir, f"{target}_raw.tif")
    extract_segment_raw(raw_tiff, raw_segment_path, ranges['top_range'])

    corrected_path = os.path.join(base_analysis_dir, f"{base_name}_{target}.tiff")
    perform_orthorectification(
        raw_segment_path, rpc_dict, dem_path, geoid_path,
        corrected_path,
        os.path.join(center_result_dir, center_tiff_file),
        pseudo_gcps=pseudo_gcps,
        overlap_gcps=overlap_gcps
    )

    # GDALWARP -overwrite가 사이드카 RPB를 덮어썼을 수 있으니 재저장 (성공 경로에서만 도달)
    save_to_rpb(rpc_dict, rpb_path)

    if save_intermediate:
        _finalize_segment(target, base_dir, data_name, corrected_path, center_result_dir, center_tiff_file, base_analysis_dir)

    return corrected_path, pseudo_gcps, overlap_gcps


def process_bottom_segment(base_dir: str, raw_tiff: str, ranges: dict,
                           center_rpc: dict, center_result_dir: str, dem: dict, dem_path: str, geoid: dict, geoid_path: str,
                           center_tiff_file: str, width: int,
                           save_intermediate: bool = True) -> Tuple[Optional[str], Optional[List[list]], Optional[List[dict]]]:
    """
    Bottom 세그먼트 처리 (Center -> Anchor -> Bottom, 하향식 외삽)
    Anchor: Center 하단과 Bottom 상단의 중첩 영역 (Bottom 세그먼트 기준 상단부)
    Extrapolation: Anchor 아래쪽 영역 (Line 증가 방향)
    """
    target = 'bottom'
    data_name = os.path.basename(base_dir)
    base_name = data_name.replace('l1a', 'l1c')
    
    base_analysis_dir = os.path.join(base_dir, f"analysis_steps/step05_3d_rpc_{target}")
    os.makedirs(base_analysis_dir, exist_ok=True)
    
    print("\n" + "=" * 60)
    print(f"  처리 중: {target.upper()} (Downward Extrapolation)")
    print("=" * 60)
    
    # [1] Anchor GCP 생성 (Bottom 세그먼트의 상단부 = Center 하단부)
    print(f"\n  [1] Anchor GCP 추출 ({target})")
    overlap_range = ranges['overlap_bottom'] # Center 기준 좌표
    target_offset = ranges['bottom_range'][0] # Bottom 시작점
    
    overlap_gcps = generate_overlap_gcps(
        center_rpc, dem, geoid, overlap_range,
        ranges['center_start'], target_offset,
        width, step=200
    )
    print(f"      Anchor GCPs: {len(overlap_gcps)}개")
    
    # [2] 다항식 모델 피팅
    poly_model = fit_polynomial_model(overlap_gcps, 1, 2)
    print(f"      Poly Model RMSE: {poly_model['rmse_m']:.2f} m")
    
    # [3] 3D Pseudo GCP 생성 (외삽)
    print(f"\n  [2] 3D Pseudo GCP 생성 ({target})")
    seg_h = ranges['bottom_range'][1] - ranges['bottom_range'][0]
    
    # Exclusion Zone: 상단부(Anchor) 제외하고 하단부만 외삽
    # Bottom 이미지: 0(Overlap) ~ Overlap_End ~ End
    
    ov_lines = [g['line'] for g in overlap_gcps]
    if ov_lines:
        max_ov = max(ov_lines)
        # 상단 중첩부는 제외, 그 아래부터 끝까지 생성
        exclusion_zone = (0, max_ov + 50)
    else:
        # Fallback (약 1000px)
        overlap_size = ranges['overlap_bottom'][1] - ranges['overlap_bottom'][0]
        exclusion_zone = (0, overlap_size)
    
    pseudo_gcps = generate_pseudo_gcps_3d(
        poly_model, dem, geoid, (width, seg_h),
        overlap_gcps, step=200,
        exclusion_zone=exclusion_zone
    )
    print(f"      Pseudo GCPs: {len(pseudo_gcps)}개")
    
    # [4] RPC 모델링
    
    # Distribution Visualization
    print(f"      Visualizing GCP Distribution...")
    visualize_gcp_distribution(
        overlap_gcps, pseudo_gcps, 
        width, seg_h, 
        os.path.join(base_analysis_dir, "gcp_distribution.png"),
        bg_image_path=raw_tiff,
        bg_offset=ranges['bottom_range'][0]
    )
    
    print(f"      Combining GCPs & RPC Fitting")
    combined_gcps = list(pseudo_gcps)
    
    # Anchor Weighting
    anchor_weight = 10
    for _ in range(anchor_weight):
        for g in overlap_gcps:
            combined_gcps.append([float(g['line']), float(g['samp']),
                                   float(g['lat']), float(g['lon']), float(g['height'])])
            
    with open(os.path.join(base_analysis_dir, "combined_gcps.json"), 'w') as f:
        json.dump(combined_gcps, f)
        
    rpc_dict = generate_rpc_coefficients(combined_gcps, (width, seg_h))
    rpb_path = os.path.join(base_analysis_dir, f"{base_name}_{target}.RPB")
    # RPB 사전 저장 (sanity check raise 시에도 디버깅용으로 보존)
    save_to_rpb(rpc_dict, rpb_path)

    # [5] Orthorectification
    print(f"\n  [3] Orthorectification ({target})")
    raw_segment_path = os.path.join(base_analysis_dir, f"{target}_raw.tif")
    extract_segment_raw(raw_tiff, raw_segment_path, ranges['bottom_range'])

    corrected_path = os.path.join(base_analysis_dir, f"{base_name}_{target}.tiff")
    perform_orthorectification(
        raw_segment_path, rpc_dict, dem_path, geoid_path,
        corrected_path,
        os.path.join(center_result_dir, center_tiff_file),
        pseudo_gcps=pseudo_gcps,
        overlap_gcps=overlap_gcps
    )

    # GDALWARP -overwrite가 사이드카 RPB를 덮어썼을 수 있으니 재저장 (성공 경로에서만 도달)
    save_to_rpb(rpc_dict, rpb_path)

    if save_intermediate:
        _finalize_segment(target, base_dir, data_name, corrected_path, center_result_dir, center_tiff_file, base_analysis_dir)

    return corrected_path, pseudo_gcps, overlap_gcps


def _l1c_scene_stem_from_center_tiff(center_tiff_file: str) -> str:
    """Center 결과 파일명에서 씬 stem 추출 (예: *_center.tiff → *_ 제거)."""
    stem = os.path.splitext(os.path.basename(center_tiff_file))[0]
    if stem.lower().endswith("_center"):
        return stem[: -len("_center")]
    return stem


def _publish_to_final_results(
    target: str,
    base_dir: str,
    center_tiff_file: str,
    data_name: str,
    corrected_tiff_src: str,
    analysis_dir: str,
) -> str:
    """
    Top/Bottom 보정 결과를 Center와 동일 규칙으로 Segment/07_Final_results 에 저장.
    TIFF: {stem}_top.tiff / {stem}_bottom.tiff, RPB: 동일 stem.
    """
    seg = target.lower()
    scene_stem = _l1c_scene_stem_from_center_tiff(center_tiff_file)
    result_dir = os.path.join(base_dir, "Top" if seg == "top" else "Bottom", "07_Final_results")
    os.makedirs(result_dir, exist_ok=True)
    base_name = data_name.replace("l1a", "l1c")
    out_tiff = os.path.join(result_dir, f"{scene_stem}_{seg}.tiff")
    src_rpb = os.path.join(analysis_dir, f"{base_name}_{target}.RPB")
    out_rpb = os.path.join(result_dir, f"{scene_stem}_{seg}.RPB")
    shutil.copy2(corrected_tiff_src, out_tiff)
    if os.path.isfile(src_rpb):
        shutil.copy2(src_rpb, out_rpb)
    print(f"      [07_Final_results] {out_tiff}")
    print(f"      [07_Final_results] {out_rpb}")
    return out_tiff


def _compute_mosaic_center_latlon(mosaic_path: str) -> Tuple[float, float]:
    """모자이크 raster의 중심점을 (lat, lon)으로 반환."""
    from rasterio.warp import transform as rio_transform
    with rasterio.open(mosaic_path) as src:
        b = src.bounds
        cx = (b.left + b.right) / 2.0
        cy = (b.bottom + b.top) / 2.0
        src_crs = src.crs
    if src_crs and src_crs.to_string() != 'EPSG:4326':
        xs, ys = rio_transform(src_crs, 'EPSG:4326', [cx], [cy])
        lon, lat = float(xs[0]), float(ys[0])
    else:
        lon, lat = float(cx), float(cy)
    return lat, lon


def _save_mosaic_center(mosaic_path: str) -> str:
    """모자이크와 같은 stem으로 *_center.json 사이드카 저장."""
    lat, lon = _compute_mosaic_center_latlon(mosaic_path)
    center_json = os.path.splitext(mosaic_path)[0] + "_center.json"
    with open(center_json, 'w') as f:
        json.dump({'lat': lat, 'lon': lon}, f, indent=2)
    print(f"      Center (lat, lon): ({lat:.6f}, {lon:.6f}) → {center_json}")
    return center_json


def _finalize_segment(target: str, base_dir: str, data_name: str, corrected_path: str,
                      center_result_dir: str, center_tiff_file: str, base_analysis_dir: str):
    """결과 복사, 모자이킹, 평가 (공통 로직 분리)"""
    final_path = _publish_to_final_results(
        target, base_dir, center_tiff_file, data_name, corrected_path, base_analysis_dir
    )

    # Mosaic (base_dir 바로 아래, 원래 명명규칙으로 저장)
    print(f"\n  [4] Mosaicking ({target})")
    with rasterio.open(final_path) as src:
        band_count = src.count
    mosaic_path = os.path.join(base_dir, f"{data_name.replace('l1a', 'l1c')}.tiff")
    create_mosaic(target, base_dir, final_path, mosaic_path)
    print(f"      Mosaic Saved: {mosaic_path}")
    _save_mosaic_center(mosaic_path)
    
    # Evaluation
    # print(f"\n  [5] Evaluation ({target})")
    # try:
    #     from eval_utils import evaluate_mosaic_vs_reference
    #     center_final_path = os.path.join(center_result_dir, center_tiff_file)
    #     l1c_candidates = glob.glob(os.path.join(base_dir, "*l1c*.tiff"))
    #     reference_path = l1c_candidates[0] if l1c_candidates else center_final_path
    #     print(f"      Reference: {os.path.basename(reference_path)}")
    #     eval_metrics = evaluate_mosaic_vs_reference(
    #         mosaic_path=mosaic_path,
    #         reference_path=reference_path,
    #         output_dir=os.path.join(base_analysis_dir, "evaluation"),
    #         gdalwarp_cmd=GDALWARP,
    #         boundaries=[],
    #         search_range=100,
    #         rmse_threshold=0.5
    #     )
    #     if eval_metrics:
    #         with open(os.path.join(base_analysis_dir, "evaluation", "metrics.json"), 'w') as f:
    #             json.dump(eval_metrics, f, indent=2)
    # except ImportError:
    #     print("Warning: eval_utils.py not found. Skipping evaluation.")
    # except Exception as e:
    #     print(f"Evaluation failed: {e}")
    #     import traceback
    #     traceback.print_exc()


def create_mosaic_all(base_dir: str, center_result_dir: str, top_corrected: str, bottom_corrected: str, output_path: str):
    """
    --target all 전용: top + center + bottom 을 모자이킹해 한 장 저장
    """
    def find_center_tiff():
        for root, dirs, files in os.walk(center_result_dir):
            for f in files:
                if f.endswith('.tiff'):
                    return os.path.join(root, f)
        return None
    
    center_tiff = find_center_tiff()
    tifs = [top_corrected, center_tiff, bottom_corrected]
    tifs = [t for t in tifs if t and os.path.exists(t)]
    
    if not tifs:
        print("      모자이킹할 파일이 없습니다.")
        return
    
    print(f"      Mosaicking {len(tifs)} files: {[os.path.basename(t) for t in tifs]}")
    
    nodata_str = "0 0 0"  # 3밴드 가정
    vrt_path = output_path.replace('.tiff', '.vrt')
    subprocess.run([GDALBUILDVRT, '-srcnodata', nodata_str, '-vrtnodata', nodata_str, vrt_path] + tifs,
                   capture_output=True, check=True)
    subprocess.run([GDAL_TRANSLATE, vrt_path, output_path,
                    '-co', 'COMPRESS=LZW', '-co', 'TILED=YES', '-co', 'BIGTIFF=IF_SAFER'],
                   capture_output=True, check=True)
    if os.path.exists(vrt_path):
        os.remove(vrt_path)
    
    # -------------------------------------------------------------
    # [NEW] Evaluation & Residual Map for ALL mode (User Request)
    # -------------------------------------------------------------
    print(f"\n  [Evaluation] Generating Residual Map for ALL Mosaic")
    try:
        from eval_utils import evaluate_mosaic_vs_reference
        
        # Reference: L1C center or finding any L1C
        l1c_candidates = glob.glob(os.path.join(base_dir, "*l1c*.tiff"))
        # L1C파일이 여러개일 수 있으니, Center나 전체에 해당하는 것을 찾아야 함.
        # 보통 L1C는 한 장으로 제공되거나 분할되어 있음.
        # 여기서는 가장 먼저 발견되는 L1C를 Reference로 사용 (보통 전체 씬)
        if l1c_candidates:
            reference_path = l1c_candidates[0]
            print(f"      Reference: {os.path.basename(reference_path)}")
            
            # Output Dir
            eval_dir = os.path.join(os.path.dirname(output_path), "evaluation_all")
            
            eval_metrics = evaluate_mosaic_vs_reference(
                mosaic_path=output_path,
                reference_path=reference_path,
                output_dir=eval_dir,
                gdalwarp_cmd=GDALWARP,
                boundaries=[],
                search_range=100,
                rmse_threshold=0.5,
                exclude_tiff=center_tiff
            )
            print(f"      Residual Map Saved in: {eval_dir}")
            
            if eval_metrics:
                with open(os.path.join(eval_dir, "metrics.json"), 'w') as f:
                    json.dump(eval_metrics, f, indent=2)
                print(f"      Metrics Saved in: {os.path.join(eval_dir, 'metrics.json')}")
        else:
            print("      Warning: No L1C reference found for evaluation.")
            
    except ImportError:
        print("Warning: eval_utils.py not found. Skipping evaluation.")
    except Exception as e:
        print(f"Evaluation failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    global _LEGACY_DEM
    parser = argparse.ArgumentParser(description="Strip 영상 3D 정밀 기하보정 (RPC + DEM + Geoid)")
    parser.add_argument("--base_dir", required=True, help="데이터 디렉토리")
    parser.add_argument("--target", required=True, choices=['top', 'bottom', 'all'], help="타겟 세그먼트")
    parser.add_argument(
        "--modern_dem",
        action="store_true",
        help="nodata -32768·RPC_DEM_MISSING_VALUE=-32768·안전 출력범위 샘플 (Copernicus 권장)",
    )
    parser.add_argument(
        "--legacy_dem",
        action="store_true",
        help="붙여넣기 스크립트와 동일(명시). 직접 실행 시 기본이 legacy라 덜 필요함",
    )
    args = parser.parse_args()
    if args.modern_dem:
        _LEGACY_DEM = False
    elif args.legacy_dem:
        _LEGACY_DEM = True
    else:
        _LEGACY_DEM = True  # 붙여넣기 단독 스크립트와 동일한 기본
    print(f"  [설정] DEM 기하 파이프라인: {'legacy (붙여넣기 스크립트와 동일)' if _LEGACY_DEM else 'modern (nodata -32768, 권장)'}")
    
    base_dir = args.base_dir
    target = args.target
    data_name = os.path.basename(base_dir)
    
    # Paths
    raw_tiff = os.path.join(base_dir.replace(data_name, ""), f"{data_name}.tiff")
    center_result_dir = os.path.join(base_dir, "Center/07_Final_results")
    
    # Check inputs
    if not os.path.exists(raw_tiff):
        print(f"Error: Raw TIFF not found at {raw_tiff}")
        return
        
    print("=" * 70)
    print(f"Strip 3D Correction (RPC + DEM + Geoid): {target.upper()}")
    print("=" * 70)
    
    # 1. 범위 계산
    with rasterio.open(raw_tiff) as src:
        total_height = src.height
        width = src.width
        
    ranges = calculate_ranges(total_height)
    
    # 2. Load Center/DEM
    print("\n[공통] Center RPC & DEM 로드")
    try:
        center_rpb_file = [f for f in os.listdir(center_result_dir) if f.endswith('.RPB')][0]
        center_tiff_file = [f for f in os.listdir(center_result_dir) if f.endswith('.tiff')][0]
    except IndexError:
        print("Error: Center result not found (RPB or TIFF).")
        return

    center_rpc = parse_rpb(os.path.join(center_result_dir, center_rpb_file))
    
    # DEM Paths
    dem_center_path = os.path.join(base_dir, "Center/01_Download_open_data/Copernicus_DEM_center.tif")
    dem_top_path = os.path.join(base_dir, "Top/01_Download_open_data/Copernicus_DEM_top.tif")
    dem_bottom_path = os.path.join(base_dir, "Bottom/01_Download_open_data/Copernicus_DEM_bottom.tif")
    
    # Geoid Paths (Top/Bottom 세그먼트 외삽용; Center와 겹침 영역은 해당 DEM·Geoid 그리드 사용)
    geoid_top_path = os.path.join(base_dir, "Top/01_Download_open_data/Geoid_top.tif")
    geoid_bottom_path = os.path.join(base_dir, "Bottom/01_Download_open_data/Geoid_bottom.tif")
    
    # Load Center DEM by default (for anchor GCPs if needed, or fallback)
    # But for 3D processing, we need the specific DEM for the target area.
    # Note: Anchor GCPs are in the overlap region. 
    # Top Anchor is Top-Bottom / Center-Top overlap -> Center's top area / Top's bottom area.
    # Bottom Anchor is Bottom-Top / Center-Bottom overlap -> Center's bottom area / Bottom's top area.
    # Ideally we should use the DEM that covers the specific lat/lon. 
    # Since we have separate DEMs, we should pass the appropriate one.
    
    dem_center = load_dem(dem_center_path)
    
    def _require_geoid_paths(paths: list) -> bool:
        for p, label in paths:
            if not os.path.exists(p):
                print(f"Error: {label} not found: {p}")
                return False
        return True
    
    # -------------------------------------------------------
    #  --target all: top + bottom 외삽 후 center와 모자이킹 1장 저장
    # -------------------------------------------------------
    if target == 'all':
        print("\n[ALL MODE] Top & Bottom 외삽 후 Center와 모자이킹 1장 생성")
        if not _require_geoid_paths([
            (geoid_top_path, "Top Geoid"),
            (geoid_bottom_path, "Bottom Geoid"),
        ]):
            return
        
        # Top 처리
        dem_top = load_dem(dem_top_path)
        geoid_top = load_geoid(geoid_top_path)
        top_corrected, _, _ = process_top_segment(
            base_dir, raw_tiff, ranges,
            center_rpc, center_result_dir, dem_top, dem_top_path,
            geoid_top, geoid_top_path,
            center_tiff_file, width,
            save_intermediate=False
        )
        
        # Bottom 처리
        dem_bottom = load_dem(dem_bottom_path)
        geoid_bottom = load_geoid(geoid_bottom_path)
        bottom_corrected, _, _ = process_bottom_segment(
            base_dir, raw_tiff, ranges,
            center_rpc, center_result_dir, dem_bottom, dem_bottom_path,
            geoid_bottom, geoid_bottom_path,
            center_tiff_file, width,
            save_intermediate=False
        )
        
        # Center와 동일 규칙으로 Top/Bottom → 각 07_Final_results
        top_analysis = os.path.join(base_dir, "analysis_steps/step05_3d_rpc_top")
        bottom_analysis = os.path.join(base_dir, "analysis_steps/step05_3d_rpc_bottom")
        print("\n[ALL] Top/Bottom → Segment/07_Final_results (Center 네이밍)")
        top_final = _publish_to_final_results(
            "top", base_dir, center_tiff_file, data_name, top_corrected, top_analysis
        )
        bottom_final = _publish_to_final_results(
            "bottom", base_dir, center_tiff_file, data_name, bottom_corrected, bottom_analysis
        )
        
        # 최종 모자이크 1장 저장 (base_dir 바로 아래, 원래 명명규칙)
        print("\n[ALL] 최종 모자이킹 (top + center + bottom)")
        mosaic_path = os.path.join(base_dir, f"{data_name.replace('l1a', 'l1c')}.tiff")

        create_mosaic_all(base_dir, center_result_dir, top_final, bottom_final, mosaic_path)
        print(f"\n✅ 최종 모자이크 저장 완료: {mosaic_path}")
        _save_mosaic_center(mosaic_path)
        return
    
    # -------------------------------------------------------
    #  단일 타겟 처리 (top 또는 bottom)
    # -------------------------------------------------------
    if target == 'top':
        if not _require_geoid_paths([(geoid_top_path, "Top Geoid")]):
            return
        dem_top = load_dem(dem_top_path)
        geoid_top = load_geoid(geoid_top_path)
        process_top_segment(
            base_dir, raw_tiff, ranges,
            center_rpc, center_result_dir, dem_top, dem_top_path,
            geoid_top, geoid_top_path,
            center_tiff_file, width,
            save_intermediate=True
        )
    elif target == 'bottom':
        if not _require_geoid_paths([(geoid_bottom_path, "Bottom Geoid")]):
            return
        dem_bottom = load_dem(dem_bottom_path)
        geoid_bottom = load_geoid(geoid_bottom_path)
        process_bottom_segment(
            base_dir, raw_tiff, ranges,
            center_rpc, center_result_dir, dem_bottom, dem_bottom_path,
            geoid_bottom, geoid_bottom_path,
            center_tiff_file, width,
            save_intermediate=True
        )
    
    print("\n✅ 모든 작업 완료!")


if __name__ == "__main__":
    main()




