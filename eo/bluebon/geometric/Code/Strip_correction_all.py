#!/usr/bin/env python3
"""
Strip_correction_all.py
Bottom 영상이 정상(Orthorectified)일 때, 이를 바탕으로 Center를 보정(외삽)하고,
보정된 Center를 바탕으로 Top을 연쇄적으로 보정(외삽)하는 기하보정 스크립트입니다.
(3D RPC 기반)
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

# rpcfit 임포트 (경고 무시)
warnings.filterwarnings('ignore', category=RuntimeWarning, module='rpcfit')
try:
    from rpcfit.rpc_fit import calibrate_rpc
except ImportError:
    print("Error: 'rpcfit' library not found. Please install it or use the correct environment.")
    sys.exit(1)

try:
    from eval_utils import visualize_gcp_distribution
except ImportError:
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

def calculate_ranges(total_height: int) -> dict:
    center_height = 6000
    overlap_size = 1000
    
    center_start = (total_height - center_height) // 2
    center_end = center_start + center_height
    
    top_range = (0, center_start + overlap_size)
    center_range = (center_start, center_end)
    bottom_range = (center_end - overlap_size, total_height)
    
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
    sanitized = {}
    for key, value in rpc.items():
        if key.endswith('_COEFF'):
            if isinstance(value, str):
                sanitized[key] = np.array([float(x) for x in value.split()])
            elif isinstance(value, (list, tuple, np.ndarray)):
                sanitized[key] = np.array([float(x) for x in value])
            else:
                sanitized[key] = value
        elif key.endswith('_OFF') or key.endswith('_SCALE'):
            sanitized[key] = float(value)
        else:
            sanitized[key] = value
    return sanitized

# DEM/고도: 빈 픽셀·메타 nodata 미설정·nodata=0을 모두 높이 0으로 통일 (실제 0m와 구분하지 않음)
# Copernicus DEM(파일 nodata=0)에서 sea pixel을 정상 처리하기 위해 0.0 유지 필수.
_ELEV_NODATA_STANDARD = 0.0
_LEGACY_DEM = False
# True면 파일에 명시된 nodata만 사용 (None/0을 0으로 치환하지 않음)
_STRICT_DEM_NODATA = False

def _normalize_elevation_nodata(raw_nodata):
    """strict가 아니면: None·파싱 실패·메타 nodata 0 → 표준 0.0. 그 외 파일 명시 값은 유지.
    strict면: None은 None, 그 외는 파일 값 유지."""
    if _STRICT_DEM_NODATA:
        if raw_nodata is None:
            return None
        try:
            return float(raw_nodata)
        except (TypeError, ValueError):
            return None
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
    with rasterio.open(dem_path) as src:
        data = src.read(1)
        if _LEGACY_DEM:
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
    """Geoid 래스터 로드 (DEM과 동일 구조 → sample_dem으로 샘플링)"""
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
    bounds = dem['bounds']
    transform = dem['transform']
    data = dem['data']
    nodata = dem['nodata']

    if not (bounds.left <= lon <= bounds.right and bounds.bottom <= lat <= bounds.top):
        return 0.0
    
    col_float = (lon - transform.c) / transform.a
    row_float = (lat - transform.f) / transform.e
    
    col0 = int(np.floor(col_float))
    row0 = int(np.floor(row_float))
    col1 = col0 + 1
    row1 = row0 + 1
    
    h, w = data.shape
    if not (0 <= row0 < h - 1 and 0 <= col0 < w - 1):
        if 0 <= row0 < h and 0 <= col0 < w:
            val = data[row0, col0]
            if _is_invalid_elev_pixel(val, nodata):
                return 0.0
            return float(val)
        return 0.0

    v00 = data[row0, col0]
    v01 = data[row0, col1]
    v10 = data[row1, col0]
    v11 = data[row1, col1]
    
    is_nodata = False
    if _is_invalid_elev_pixel(v00, nodata) or _is_invalid_elev_pixel(v01, nodata) or _is_invalid_elev_pixel(v10, nodata) or _is_invalid_elev_pixel(v11, nodata):
        is_nodata = True
            
    if not is_nodata:
        if np.isnan(v00) or np.isnan(v01) or np.isnan(v10) or np.isnan(v11):
            is_nodata = True
            
    if is_nodata:
         r_near = int(round(row_float))
         c_near = int(round(col_float))
         if 0 <= r_near < h and 0 <= c_near < w:
             val = data[r_near, c_near]
             if _is_invalid_elev_pixel(val, nodata):
                 return 0.0
             return float(val)
         return 0.0
             
    dx = col_float - col0
    dy = row_float - row0
    
    top = (1 - dx) * v00 + dx * v01
    bottom = (1 - dx) * v10 + dx * v11
    val = (1 - dy) * top + dy * bottom
    
    if np.isnan(val): return 0.0
    
    return float(val)

def sample_geoid(geoid: dict, lat: float, lon: float) -> float:
    transform = geoid['transform']
    data = geoid['data']
    col_float = (lon - transform.c) / transform.a
    row_float = (lat - transform.f) / transform.e
    h, w = data.shape
    if h < 2 or w < 2:
        r = int(np.clip(round(row_float), 0, h - 1))
        c = int(np.clip(round(col_float), 0, w - 1))
        return float(data[r, c])
    col0 = int(np.clip(np.floor(col_float), 0, w - 2))
    row0 = int(np.clip(np.floor(row_float), 0, h - 2))
    col1 = col0 + 1
    row1 = row0 + 1
    dx = float(col_float - col0)
    dy = float(row_float - row0)
    top = (1 - dx) * data[row0, col0] + dx * data[row0, col1]
    bottom = (1 - dx) * data[row1, col0] + dx * data[row1, col1]
    val = (1 - dy) * top + dy * bottom
    return float(val)

def generate_overlap_gcps_from_ref(ref_rpc: dict, dem: dict, geoid: dict,
                                   overlap_range: Tuple[int, int],
                                   ref_start_line: int,
                                   target_segment_offset: int,
                                   width: int,
                                   step: int = 200,
                                   ref_full_range: Optional[Tuple[int, int]] = None) -> List[dict]:
    """Anchor GCP 추출.

    ref_full_range가 주어지면 ref 세그먼트 전체에서 anchor 추출 (확장 모드).
    None이면 overlap_range만 사용 (기존 모드).
    확장 모드는 polynomial fit의 line 범위를 넓혀 외삽 drift를 감소시킨다.
    """
    if ref_full_range is not None:
        sample_start, sample_end = ref_full_range
        print(f"      Anchor 확장 모드: ref 전체 line 범위 사용 ({sample_start}~{sample_end})")
    else:
        sample_start, sample_end = overlap_range

    ref_local_start = sample_start - ref_start_line
    ref_local_end = sample_end - ref_start_line

    lines = np.arange(ref_local_start + 50, ref_local_end - 50, step)
    margin = 200
    samps = np.arange(margin, width - margin, step)

    gcps = []
    for ref_line in lines:
        for samp in samps:
            lat, lon = rpc_inverse(ref_rpc, ref_line, samp, height=0)
            height = sample_dem(dem, lat, lon)
            if _LEGACY_DEM:
                geoid_height = sample_geoid(geoid, lat, lon)
            else:
                geoid_height = sample_dem(geoid, lat, lon)
            h_ellipsoid = height + geoid_height
            lat, lon = rpc_inverse(ref_rpc, ref_line, samp, height=h_ellipsoid)
            
            raw_line = ref_line + ref_start_line
            target_line = raw_line - target_segment_offset
            
            gcps.append({
                'line': target_line,
                'samp': samp,
                'lat': lat,
                'lon': lon,
                'height': h_ellipsoid,
                'raw_line': raw_line
            })
    return gcps

def _build_poly_features(lines, samps, line_stats, samp_stats, line_order, samp_order, interaction=True):
    L = (lines - line_stats['mean']) / line_stats['std']
    S = (samps - samp_stats['mean']) / samp_stats['std']
    
    features = []
    if interaction:
        line_terms = [L**i for i in range(line_order + 1)]
        samp_terms = [S**j for j in range(samp_order + 1)]
        for l_term in line_terms:
            for s_term in samp_terms:
                features.append(l_term * s_term)
    else:
        features.append(np.ones_like(L))
        for i in range(1, line_order + 1):
            features.append(L**i)
        for j in range(1, samp_order + 1):
            features.append(S**j)
            
    return np.column_stack(features)

def fit_polynomial_model(gcps: List[dict], line_order: int, samp_order: int) -> dict:
    lines = np.array([g['line'] for g in gcps])
    samps = np.array([g['samp'] for g in gcps])
    lats = np.array([g['lat'] for g in gcps])
    lons = np.array([g['lon'] for g in gcps])
    
    line_stats = {'mean': lines.mean(), 'std': lines.std()}
    samp_stats = {'mean': samps.mean(), 'std': samps.std()}
    
    interaction = False
    A = _build_poly_features(lines, samps, line_stats, samp_stats, line_order, samp_order, interaction=interaction)
    
    lat_coeffs, _, _, _ = np.linalg.lstsq(A, lats, rcond=None)
    lon_coeffs, _, _, _ = np.linalg.lstsq(A, lons, rcond=None)
    
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

def generate_pseudo_gcps_3d(model: dict, dem: dict, geoid: dict,
                            target_wh: Tuple[int, int],
                            overlap_gcps: List[dict],
                            step: int = 200,
                            exclusion_zone: Optional[Tuple[int, int]] = None,
                            line_margin: int = 50,
                            samp_margin: int = 200) -> List[list]:
    width, height = target_wh
    
    lines = np.array([g['line'] for g in overlap_gcps])
    samps = np.array([g['samp'] for g in overlap_gcps])
    
    center_l = np.mean(lines)
    center_s = np.mean(samps)
    
    vals = np.column_stack([lines - center_l, samps - center_s])
    cov = np.cov(vals, rowvar=False)
    eig_vals, eig_vecs = np.linalg.eigh(cov)
    
    vec0 = eig_vecs[:, 0]
    vec1 = eig_vecs[:, 1]
    
    score0 = abs(vec0[0]) 
    score1 = abs(vec1[0])
    
    if score0 > score1:
        u_axis = vec0
        v_axis = vec1
    else:
        u_axis = vec1
        v_axis = vec0
        
    eig_vecs_sorted = np.column_stack([u_axis, v_axis])
    
    corners = np.array([
        [0, 0], [0, width], [height, 0], [height, width]
    ])
    corners_centered = corners - [center_l, center_s]
    uv_corners = corners_centered @ eig_vecs_sorted
    
    min_u, max_u = np.min(uv_corners[:, 0]), np.max(uv_corners[:, 0])
    min_v, max_v = np.min(uv_corners[:, 1]), np.max(uv_corners[:, 1])
    
    u_steps = np.arange(min_u, max_u + step, step)
    v_steps = np.arange(min_v, max_v + step/2, step) 
    
    U_grid, V_grid = np.meshgrid(u_steps, v_steps, indexing='ij')
    U_flat = U_grid.flatten()
    V_flat = V_grid.flatten()
    
    uv_flat = np.column_stack([U_flat, V_flat])
    ls_flat = (uv_flat @ eig_vecs_sorted.T) + [center_l, center_s]
    
    L_flat = ls_flat[:, 0]
    S_flat = ls_flat[:, 1]
    
    interaction = model.get('interaction', True) 
    A = _build_poly_features(L_flat, S_flat, model['line_stats'], model['samp_stats'], 
                             model['orders'][0], model['orders'][1], interaction=interaction)
    
    lat_pred = A @ model['lat_coeffs']
    lon_pred = A @ model['lon_coeffs']
    
    pseudo_gcps = []
    
    for i in range(len(L_flat)):
        l = L_flat[i]
        s = S_flat[i]
        
        if not (line_margin <= l < height - line_margin and samp_margin <= s < width - samp_margin):
            continue
        
        if exclusion_zone:
            if exclusion_zone[0] <= l < exclusion_zone[1]:
                continue
                
        lat = lat_pred[i]
        lon = lon_pred[i]
        
        h0 = sample_dem(dem, lat, lon)
        if _LEGACY_DEM:
            gh = sample_geoid(geoid, lat, lon)
        else:
            gh = sample_dem(geoid, lat, lon)
        h = h0 + gh
        pseudo_gcps.append([l, s, lat, lon, h])
        
    if pseudo_gcps:
        heights = np.array([p[4] for p in pseudo_gcps])
        h_std = np.std(heights)
        
        if h_std < 0.1:
            print(f"      [Info] Low height variance ({h_std:.4f}). Injecting multi-layer height offsets.")
            offsets = [1.0, 10.0, 50.0, 100.0]
            extra_gcps = []
            for p in pseudo_gcps:
                for off in offsets:
                    p_new = list(p)
                    p_new[4] += off
                    extra_gcps.append(p_new)
            pseudo_gcps.extend(extra_gcps)
        
    return pseudo_gcps

def generate_rpc_coefficients(gcps_3d: List[list], target_wh: Tuple[int, int]) -> Dict[str, Any]:
    gcps = np.array(gcps_3d)
    
    valid_mask = np.isfinite(gcps).all(axis=1)
    if not np.all(valid_mask):
        n_dropped = len(gcps) - np.sum(valid_mask)
        print(f"      [Warning] Dropped {n_dropped} invalid GCPs (NaN/Inf)")
        gcps = gcps[valid_mask]
        
    if len(gcps) < 10:
        raise ValueError(f"Not enough valid GCPs for RPC fitting: {len(gcps)}")
    
    target_pts = gcps[:, [1, 0]]
    input_locs = gcps[:, [3, 2, 4]]
    
    print(f"      RPC Fit Input: {len(gcps)} points")
    rpc_obj = calibrate_rpc(target_pts, input_locs, separate=True, tol=1e-2, max_iter=20)
    
    return rpc_obj.to_geotiff_dict()

def save_to_rpb(rpc_dict: dict, output_path: str):
    def _format_coeff(coeffs):
        if isinstance(coeffs, (list, tuple, np.ndarray)):
            c_list = list(coeffs)
        elif isinstance(coeffs, str):
            c_list = [float(x) for x in coeffs.split()]
        else:
            c_list = [0.0]*20
            
        if len(c_list) < 20:
            c_list.extend([0.0] * (20 - len(c_list)))
        return c_list

    with open(output_path, 'w') as f:
        f.write("satId = \"GlueGenerated\"\n")
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
        
        ln = _format_coeff(rpc_dict.get('LINE_NUM_COEFF', []))
        f.write("LINE_NUM_COEFF: " + " ".join([f"{x:.12e}" for x in ln]) + ";\n")
        ld = _format_coeff(rpc_dict.get('LINE_DEN_COEFF', []))
        f.write("LINE_DEN_COEFF: " + " ".join([f"{x:.12e}" for x in ld]) + ";\n")
        sn = _format_coeff(rpc_dict.get('SAMP_NUM_COEFF', []))
        f.write("SAMP_NUM_COEFF: " + " ".join([f"{x:.12e}" for x in sn]) + ";\n")
        sd = _format_coeff(rpc_dict.get('SAMP_DEN_COEFF', []))
        f.write("SAMP_DEN_COEFF: " + " ".join([f"{x:.12e}" for x in sd]) + ";\n")

def extract_segment_raw(raw_path: str, output_path: str, line_range: Tuple[int, int]) -> str:
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
    with rasterio.open(ref_tiff) as ref:
        ref_res_x, ref_res_y = abs(ref.transform.a), abs(ref.transform.e)
        # ref CRS를 gdalwarp가 안전하게 파싱할 수 있는 형태로 변환
        # (신버전 rasterio의 to_string()이 긴 WKT를 반환해 gdalwarp가 GEOGCS로 fallback하는 버그 회피)
        if ref.crs:
            epsg = ref.crs.to_epsg()
            if epsg is not None:
                ref_crs = f'EPSG:{epsg}'
            else:
                ref_crs = ref.crs.to_proj4()
        else:
            ref_crs = 'EPSG:4326'

    with rasterio.open(raw_path) as src:
        h, w = src.height, src.width
    
    numeric_rpc = sanitize_rpc_dict(rpc_dict)
    all_lats, all_lons = [], []
    
    if pseudo_gcps:
        for gcp in pseudo_gcps:
            all_lats.append(gcp[2])
            all_lons.append(gcp[3])
    if overlap_gcps:
        for g in overlap_gcps:
            all_lats.append(g['lat'])
            all_lons.append(g['lon'])
    
    if all_lats:
        gcp_min_lat, gcp_max_lat = min(all_lats), max(all_lats)
        gcp_min_lon, gcp_max_lon = min(all_lons), max(all_lons)
    else:
        gcp_min_lat = gcp_max_lat = gcp_min_lon = gcp_max_lon = None
    
    hm1, wm1 = h - 1, w - 1
    if hm1 < 0:
        hm1 = 0
    if wm1 < 0:
        wm1 = 0
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
    for avg_h in [0, 50]:
        for r, c in sample_points:
            try:
                lat, lon = rpc_inverse(numeric_rpc, float(r), float(c), height=float(avg_h))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    rpc_lats.append(lat)
                    rpc_lons.append(lon)
            except Exception:
                pass
    
    if rpc_lats:
        rpc_min_lat, rpc_max_lat = min(rpc_lats), max(rpc_lats)
        rpc_min_lon, rpc_max_lon = min(rpc_lons), max(rpc_lons)
    else:
        rpc_min_lat = rpc_max_lat = rpc_min_lon = rpc_max_lon = None

    candidate_lats = [v for v in [gcp_min_lat, gcp_max_lat, rpc_min_lat, rpc_max_lat] if v is not None]
    candidate_lons = [v for v in [gcp_min_lon, gcp_max_lon, rpc_min_lon, rpc_max_lon] if v is not None]

    min_lat, max_lat = min(candidate_lats), max(candidate_lats)
    min_lon, max_lon = min(candidate_lons), max(candidate_lons)

    # ── Sanity check: 외삽 폭주 감지 ─────────────────────────────────
    # 일반 segment는 ~6000 lines × 4.8m ≈ 30km ≈ 0.3°. 2° 넘으면 명백히 발산.
    lat_extent = max_lat - min_lat
    lon_extent = max_lon - min_lon
    if lat_extent > 2.0 or lon_extent > 2.0:
        raise RuntimeError(
            f"외삽 폭주 감지: 출력 bounds extent = {lat_extent:.3f}° lat × {lon_extent:.3f}° lon "
            f"(정상 ~0.3°). 다항식 외삽이 발산해 RPC가 깨졌습니다.\n"
            f"   GCP 기반: lat[{gcp_min_lat}, {gcp_max_lat}] lon[{gcp_min_lon}, {gcp_max_lon}]\n"
            f"   RPC 샘플: lat[{rpc_min_lat}, {rpc_max_lat}] lon[{rpc_min_lon}, {rpc_max_lon}]\n"
            f"   대책: anchor 영역 확대, chained 깊이 축소, 또는 실제 ref(Strip_correction_3D) 사용."
        )

    margin = 0.03
    min_lat -= margin
    max_lat += margin
    min_lon -= margin
    max_lon += margin

    vrt_path = output_path.replace('.tiff', '_rpc.vrt')
    subprocess.run([GDAL_TRANSLATE, '-of', 'VRT', raw_path, vrt_path], check=True, capture_output=True)
    
    with open(vrt_path, 'r') as f:
        vrt_content = f.read()
        
    rpc_xml = '  <Metadata domain="RPC">\n'
    for key, value in rpc_dict.items():
        if isinstance(value, (list, tuple, np.ndarray)):
            val_str = " ".join([f"{float(x):.12f}" for x in value])
        elif isinstance(value, str):
            if ' ' in value.strip():
                parts = value.strip().split()
                try:
                    val_str = " ".join([f"{float(x):.12f}" for x in parts])
                except ValueError:
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
    
    if '<VRTRasterBand' in vrt_content:
        vrt_content = vrt_content.replace('<VRTRasterBand', rpc_xml + '<VRTRasterBand', 1)
    else:
        vrt_content = vrt_content.replace('</VRTDataset>', rpc_xml + '</VRTDataset>')
        
    with open(vrt_path, 'w') as f:
        f.write(vrt_content)
    
    print(f"      Orthorectifying...")
    # Copernicus DEM(파일 nodata=0)의 sea pixel을 0m 고도로 처리하기 위해 MISSING_VALUE=0 유지.
    # (Strip_correction_3D는 default가 legacy_dem=True라 동일하게 0이 들어가서 잘 동작)
    cmd = [
        GDALWARP,
        '-rpc',
        '-to', f'RPC_DEM={dem_path}',
        '-to', f'RPC_GEOID={geoid_path}',
        '-to', 'RPC_DEM_MISSING_VALUE=0',
        '-t_srs', ref_crs,                         # ref와 동일 CRS (UTM 등) - 단위 일관성 확보
        '-te_srs', 'EPSG:4326',                    # -te는 lat/lon 단위
        '-te', str(min_lon), str(min_lat), str(max_lon), str(max_lat),
        '-tr', str(ref_res_x), str(ref_res_y),     # ref CRS 단위 (UTM이면 m, 도면 °)
        '-r', 'bilinear',
        '-co', 'COMPRESS=LZW', '-co', 'TILED=YES',
        '-overwrite',
        vrt_path, output_path
    ]
    
    try:
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0:
            print(f"Error in gdalwarp: {res.stderr.decode()}")
            raise RuntimeError("gdalwarp failed")
    finally:
        if os.path.exists(vrt_path):
            os.remove(vrt_path)

def process_segment_extrapolation(target_name: str, ref_name: str,
                                  base_dir: str, raw_tiff: str, ranges: dict,
                                  ref_rpc: dict, ref_result_dir: str, dem: dict, dem_path: str,
                                  geoid: dict, geoid_path: str,
                                  ref_tiff_file: str, width: int) -> Tuple[Optional[str], Optional[dict]]:
    """
    Reference 영상 정보를 바탕으로 Target을 보정 (외삽)
    방향에 따라 Anchor 추출 및 예측 영역이 달라짐
    - Upward (Line 감소 방향): Bottom -> Center, Center -> Top
    - Downward (Line 증가 방향): Top -> Center, Center -> Bottom
    """
    data_name = os.path.basename(base_dir)
    base_name = data_name.replace('l1a', 'l1c')
    
    base_analysis_dir = os.path.join(base_dir, f"analysis_steps/step05_3d_rpc_all_{target_name}_from_{ref_name}")
    os.makedirs(base_analysis_dir, exist_ok=True)
    
    print("\n" + "=" * 60)
    print(f"  처리 중: {target_name.upper()} (from {ref_name.upper()} - Extrapolation)")
    print("=" * 60)
    
    # 1. 겹치는 영역 식별
    # Upward
    if target_name == 'center' and ref_name == 'bottom':
        overlap_range = ranges['overlap_bottom']
        ref_start_line = ranges['bottom_range'][0]
        target_offset = ranges['center_range'][0]
        seg_h = ranges['center_range'][1] - ranges['center_range'][0]
        is_upward = True
        ref_full_range = ranges['bottom_range']
    elif target_name == 'top' and ref_name == 'center':
        overlap_range = ranges['overlap_top']
        ref_start_line = ranges['center_range'][0]
        target_offset = ranges['top_range'][0]
        seg_h = ranges['top_range'][1] - ranges['top_range'][0]
        is_upward = True
        ref_full_range = ranges['center_range']
    # Downward
    elif target_name == 'center' and ref_name == 'top':
        overlap_range = ranges['overlap_top']
        ref_start_line = ranges['top_range'][0]
        target_offset = ranges['center_range'][0]
        seg_h = ranges['center_range'][1] - ranges['center_range'][0]
        is_upward = False
        ref_full_range = ranges['top_range']
    elif target_name == 'bottom' and ref_name == 'center':
        overlap_range = ranges['overlap_bottom']
        ref_start_line = ranges['center_range'][0]
        target_offset = ranges['bottom_range'][0]
        seg_h = ranges['bottom_range'][1] - ranges['bottom_range'][0]
        is_upward = False
        ref_full_range = ranges['center_range']
    else:
        raise ValueError(f"Unsupported target/ref combination: {target_name} from {ref_name}")

    print(f"\n  [1] Anchor GCP 추출 ({target_name} from {ref_name})")
    overlap_gcps = generate_overlap_gcps_from_ref(
        ref_rpc, dem, geoid, overlap_range,
        ref_start_line, target_offset,
        width, step=200,
        ref_full_range=ref_full_range
    )
    print(f"      Anchor GCPs: {len(overlap_gcps)}개")
    
    poly_model = fit_polynomial_model(overlap_gcps, 1, 2)
    print(f"      Poly Model RMSE: {poly_model['rmse_m']:.2f} m")
    
    print(f"\n  [2] 3D Pseudo GCP 생성 ({target_name})")
    
    ov_lines = [g['line'] for g in overlap_gcps]
    if ov_lines:
        min_ov = min(ov_lines)
        max_ov = max(ov_lines)
        if is_upward:
            exclusion_zone = (min_ov - 50, seg_h)
        else:
            exclusion_zone = (0, max_ov + 50)
    else:
        # Fallback
        if is_upward:
            if target_name == 'center':
                ex_start = ranges['center_height'] - (ranges['overlap_bottom'][1] - ranges['overlap_bottom'][0])
            else:
                ex_start = ranges['overlap_top'][1] - ranges['overlap_top'][0]
            exclusion_zone = (ex_start, seg_h)
        else:
            if target_name == 'center':
                overlap_size = ranges['overlap_top'][1] - ranges['overlap_top'][0]
            else:
                overlap_size = ranges['overlap_bottom'][1] - ranges['overlap_bottom'][0]
            exclusion_zone = (0, overlap_size)
        
    pseudo_gcps = generate_pseudo_gcps_3d(
        poly_model, dem, geoid, (width, seg_h),
        overlap_gcps, step=200,
        exclusion_zone=exclusion_zone
    )
    print(f"      Pseudo GCPs: {len(pseudo_gcps)}개")

    # GCP 분포 시각화 (Strip_correction_3D.py와 일치 - 외삽 폭주 디버깅용)
    print(f"      Visualizing GCP Distribution...")
    try:
        ranges_key = f'{target_name}_range'
        bg_offset = ranges[ranges_key][0] if ranges_key in ranges else 0
        visualize_gcp_distribution(
            overlap_gcps, pseudo_gcps,
            width, seg_h,
            os.path.join(base_analysis_dir, "gcp_distribution.png"),
            bg_image_path=raw_tiff,
            bg_offset=bg_offset
        )
    except Exception as e:
        print(f"      [Warning] GCP 분포 시각화 실패: {e}")

    print(f"      Combining GCPs & RPC Fitting")
    combined_gcps = list(pseudo_gcps)

    anchor_weight = 1
    for _ in range(anchor_weight):
        for g in overlap_gcps:
            combined_gcps.append([float(g['line']), float(g['samp']),
                                   float(g['lat']), float(g['lon']), float(g['height'])])
            
    with open(os.path.join(base_analysis_dir, "combined_gcps.json"), 'w') as f:
        json.dump(combined_gcps, f)
        
    rpc_dict = generate_rpc_coefficients(combined_gcps, (width, seg_h))
    rpb_path = os.path.join(base_analysis_dir, f"{base_name}_{target_name}.RPB")
    
    print(f"\n  [3] Orthorectification ({target_name})")
    raw_segment_path = os.path.join(base_analysis_dir, f"{target_name}_raw.tif")
    if target_name == 'center':
        extract_segment_raw(raw_tiff, raw_segment_path, ranges['center_range'])
    elif target_name == 'top':
        extract_segment_raw(raw_tiff, raw_segment_path, ranges['top_range'])
    elif target_name == 'bottom':
        extract_segment_raw(raw_tiff, raw_segment_path, ranges['bottom_range'])
        
    corrected_path = os.path.join(base_analysis_dir, f"{base_name}_{target_name}.tiff")

    # RPB를 먼저 저장 — perform_orthorectification이 sanity check로 raise해도 RPC는 보존되어 디버깅 가능
    save_to_rpb(rpc_dict, rpb_path)

    perform_orthorectification(
        raw_segment_path, rpc_dict, dem_path, geoid_path,
        corrected_path,
        os.path.join(ref_result_dir, ref_tiff_file),
        pseudo_gcps=pseudo_gcps,
        overlap_gcps=overlap_gcps
    )

    # GDALWARP -overwrite가 사이드카 RPB를 덮어썼을 수 있으니 재저장 (성공 경로에서만 도달)
    save_to_rpb(rpc_dict, rpb_path)

    # Copy to target final results directory (Full_processing_v2와 동일 파일명 규약)
    result_dir = os.path.join(base_dir, f"{target_name.capitalize()}/07_Final_results")
    if not os.path.exists(result_dir):
        os.makedirs(result_dir, exist_ok=True)
    final_tiff_path = os.path.join(result_dir, f"{base_name}_{target_name}.tiff")
    final_rpb_path = os.path.join(result_dir, f"{base_name}_{target_name}.RPB")

    shutil.copy(corrected_path, final_tiff_path)
    shutil.copy(rpb_path, final_rpb_path)

    return final_tiff_path, sanitize_rpc_dict(rpc_dict)

def create_mosaic_all(base_dir: str,  top_corrected: str, center_corrected: str, bottom_corrected: str, output_path: str):
    tifs = [top_corrected, center_corrected, bottom_corrected]
    tifs = [t for t in tifs if t and os.path.exists(t)]
    
    if not tifs:
        print("      모자이킹할 파일이 없습니다.")
        return
    
    print(f"      Mosaicking {len(tifs)} files: {[os.path.basename(t) for t in tifs]}")
    
    nodata_str = "0 0 0"
    vrt_path = output_path.replace('.tiff', '.vrt')
    subprocess.run([GDALBUILDVRT, '-srcnodata', nodata_str, '-vrtnodata', nodata_str, vrt_path] + tifs,
                   capture_output=True, check=True)
    subprocess.run([GDAL_TRANSLATE, vrt_path, output_path,
                    '-co', 'COMPRESS=LZW', '-co', 'TILED=YES', '-co', 'BIGTIFF=IF_SAFER'],
                   capture_output=True, check=True)
    if os.path.exists(vrt_path):
        os.remove(vrt_path)
        
    print(f"\n  [Evaluation] Generating Residual Map for ALL Mosaic")
    try:
        from eval_utils import evaluate_mosaic_vs_reference
        # 모자이크는 이제 base_dir의 표준 L1C 파일과 동일 위치/이름이므로,
        # 자기 자신은 reference 후보에서 제외 (남는 파일이 있으면 비교, 없으면 skip)
        output_abs = os.path.abspath(output_path)
        l1c_candidates = [p for p in glob.glob(os.path.join(base_dir, "*l1c*.tiff"))
                          if os.path.abspath(p) != output_abs]
        if l1c_candidates:
            reference_path = l1c_candidates[0]
            print(f"      Reference: {os.path.basename(reference_path)}")
            eval_dir = os.path.join(base_dir, "analysis_steps/evaluation_all")
            evaluate_mosaic_vs_reference(
                mosaic_path=output_path,
                reference_path=reference_path,
                output_dir=eval_dir,
                gdalwarp_cmd=GDALWARP,
                boundaries=[],
                search_range=100,
                rmse_threshold=0.5
            )
            print(f"      Residual Map Saved in: {eval_dir}")
        else:
            print("      Info: No separate L1C reference found — skipping evaluation.")
    except ImportError:
        print("Warning: eval_utils.py not found. Skipping evaluation.")
    except Exception as e:
        print(f"Evaluation failed: {e}")

def main():
    global _LEGACY_DEM, _STRICT_DEM_NODATA
    parser = argparse.ArgumentParser(description="Strip 영상 3D 정밀 기하보정 (연쇄 보정)")
    parser.add_argument("--base_dir", required=True, help="데이터 디렉토리")
    parser.add_argument("--direction", choices=['upward', 'downward'], default='upward',
                        help="외삽 방향 (upward: Bottom->Center->Top, downward: Top->Center->Bottom)")
    parser.add_argument(
        "--legacy_dem",
        action="store_true",
        help="구버전과 유사: DEM nodata/NaN→0, Geoid=sample_geoid, RPC_DEM_MISSING_VALUE=0",
    )
    parser.add_argument(
        "--strict-dem-nodata",
        action="store_true",
        help="DEM/Geoid 메타 nodata를 파일 그대로 사용 (미지정·0을 내부 0.0으로 치환하지 않음). "
             "기본은 빈 픽셀·nodata 0·미설정을 높이 0으로 통일. --legacy_dem 과 함께 쓰이지 않음.",
    )
    args = parser.parse_args()
    _LEGACY_DEM = bool(args.legacy_dem)
    _STRICT_DEM_NODATA = bool(args.strict_dem_nodata) and not _LEGACY_DEM
    
    base_dir = args.base_dir
    direction = args.direction
    data_name = os.path.basename(base_dir)
    
    raw_tiff = os.path.join(base_dir.replace(data_name, ""), f"{data_name}.tiff")
    
    if not os.path.exists(raw_tiff):
        print(f"Error: Raw TIFF not found at {raw_tiff}")
        return
        
    print("=" * 70)
    print(f"Strip 3D Correction (Direction: {direction})")
    print("=" * 70)
    
    with rasterio.open(raw_tiff) as src:
        total_height = src.height
        width = src.width
        
    ranges = calculate_ranges(total_height)
    dem_center_path = os.path.join(base_dir, "Center/01_Download_open_data/Copernicus_DEM_center.tif")
    dem_center = load_dem(dem_center_path)
    geoid_center_path = os.path.join(base_dir, "Center/01_Download_open_data/Geoid_center.tif")
    geoid_top_path = os.path.join(base_dir, "Top/01_Download_open_data/Geoid_top.tif")
    geoid_bottom_path = os.path.join(base_dir, "Bottom/01_Download_open_data/Geoid_bottom.tif")
    
    if direction == 'upward':
        bottom_result_dir = os.path.join(base_dir, "Bottom/07_Final_results")
        print("\n[공통] Bottom RPC & DEM 로드")
        try:
            bottom_rpb_file = [f for f in os.listdir(bottom_result_dir) if f.endswith('.RPB')][0]
            bottom_tiff_file = [f for f in os.listdir(bottom_result_dir) if f.endswith('.tiff')][0]
        except IndexError:
            print("Error: Bottom result not found (RPB or TIFF). Please ensure Bottom is orthorectified first.")
            return

        bottom_rpc = parse_rpb(os.path.join(bottom_result_dir, bottom_rpb_file))
        dem_top_path = os.path.join(base_dir, "Top/01_Download_open_data/Copernicus_DEM_top.tif")
        dem_top = load_dem(dem_top_path)
        for p, label in [(geoid_center_path, "Center Geoid"), (geoid_top_path, "Top Geoid")]:
            if not os.path.exists(p):
                print(f"Error: {label} not found: {p}")
                return
        geoid_center = load_geoid(geoid_center_path)
        geoid_top = load_geoid(geoid_top_path)
    
        # 1. Bottom을 이용해서 Center 예측
        dem_center = load_dem(dem_center_path)
        center_corrected_tiff, center_rpc = process_segment_extrapolation(
            target_name='center',
            ref_name='bottom',
            base_dir=base_dir,
            raw_tiff=raw_tiff,
            ranges=ranges,
            ref_rpc=bottom_rpc,
            ref_result_dir=bottom_result_dir,
            dem=dem_center,
            dem_path=dem_center_path,
            geoid=geoid_center,
            geoid_path=geoid_center_path,
            ref_tiff_file=bottom_tiff_file,
            width=width
        )
        
        # 2. 보정된 Center를 이용해서 Top 예측
        center_result_dir = os.path.join(base_dir, "Center/07_Final_results")
        center_tiff_file = os.path.basename(center_corrected_tiff)
        
        top_corrected_tiff, top_rpc = process_segment_extrapolation(
            target_name='top',
            ref_name='center',
            base_dir=base_dir,
            raw_tiff=raw_tiff,
            ranges=ranges,
            ref_rpc=center_rpc,
            ref_result_dir=center_result_dir,
            dem=dem_top,
            dem_path=dem_top_path,
            geoid=geoid_top,
            geoid_path=geoid_top_path,
            ref_tiff_file=center_tiff_file,
            width=width
        )
        
        bottom_corrected_tiff = os.path.join(bottom_result_dir, bottom_tiff_file)
    else: # downward
        top_result_dir = os.path.join(base_dir, "Top/07_Final_results")
        print("\n[공통] Top RPC & DEM 로드")
        try:
            top_rpb_file = [f for f in os.listdir(top_result_dir) if f.endswith('.RPB')][0]
            top_tiff_file = [f for f in os.listdir(top_result_dir) if f.endswith('.tiff')][0]
        except IndexError:
            print("Error: Top result not found (RPB or TIFF). Please ensure Top is orthorectified first.")
            return

        top_rpc = parse_rpb(os.path.join(top_result_dir, top_rpb_file))
        dem_bottom_path = os.path.join(base_dir, "Bottom/01_Download_open_data/Copernicus_DEM_bottom.tif")
        dem_bottom = load_dem(dem_bottom_path)
        for p, label in [(geoid_center_path, "Center Geoid"), (geoid_bottom_path, "Bottom Geoid")]:
            if not os.path.exists(p):
                print(f"Error: {label} not found: {p}")
                return
        geoid_center = load_geoid(geoid_center_path)
        geoid_bottom = load_geoid(geoid_bottom_path)
    
        # 1. Top을 이용해서 Center 예측
        dem_center = load_dem(dem_center_path)
        center_corrected_tiff, center_rpc = process_segment_extrapolation(
            target_name='center',
            ref_name='top',
            base_dir=base_dir,
            raw_tiff=raw_tiff,
            ranges=ranges,
            ref_rpc=top_rpc,
            ref_result_dir=top_result_dir,
            dem=dem_center,
            dem_path=dem_center_path,
            geoid=geoid_center,
            geoid_path=geoid_center_path,
            ref_tiff_file=top_tiff_file,
            width=width
        )
        
        # 2. 보정된 Center를 이용해서 Bottom 예측
        center_result_dir = os.path.join(base_dir, "Center/07_Final_results")
        center_tiff_file = os.path.basename(center_corrected_tiff)
        
        bottom_corrected_tiff, bottom_rpc = process_segment_extrapolation(
            target_name='bottom',
            ref_name='center',
            base_dir=base_dir,
            raw_tiff=raw_tiff,
            ranges=ranges,
            ref_rpc=center_rpc,
            ref_result_dir=center_result_dir,
            dem=dem_bottom,
            dem_path=dem_bottom_path,
            geoid=geoid_bottom,
            geoid_path=geoid_bottom_path,
            ref_tiff_file=center_tiff_file,
            width=width
        )
        
        top_corrected_tiff = os.path.join(top_result_dir, top_tiff_file)
    
    # 3. 최종 모자이크 — Full_processing_v2와 동일하게 base_dir 직하에 저장
    print("\n[ALL] 최종 모자이킹 (top + center + bottom)")
    mosaic_path = os.path.join(base_dir, f"{data_name.replace('l1a', 'l1c')}.tiff")

    create_mosaic_all(base_dir, top_corrected_tiff, center_corrected_tiff, bottom_corrected_tiff, mosaic_path)
    print(f"\n✅ 최종 모자이크 저장 완료: {mosaic_path}")
    print("\n✅ 모든 작업 완료!")

if __name__ == "__main__":
    main()
