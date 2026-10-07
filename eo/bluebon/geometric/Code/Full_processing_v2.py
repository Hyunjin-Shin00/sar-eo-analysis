#!/usr/bin/env python3
"""
BlueBON 기하보정 통합 파이프라인 v2
====================================

GUI 인터페이스를 통한 입력 + 새로운 출력 구조 + 모자이킹 통합

입력:
- GUI를 통한 TIFF 파일 선택
- 중심 좌표 (위도, 경도) 입력
- 분할 개수 (1/2/3) 선택
- 중간 결과물 저장 On/Off

출력:
- 최종 결과물: bb_l1c_{yyyymmdd}_{HHMMSS}_{band}.tiff (모자이킹)
- 중간 결과물 (선택적): 세그먼트별 폴더 구조

처리 단계:
- Step 0: 영상 분할
- Step 1: Sentinel-2 다운로드
- Step 2: DEM 다운로드
- Step 3: 기하보정 (geometric_correction.py 호출)
- Step 4: 결과물 모자이킹
"""

import os
import sys
import subprocess
import argparse
import re
import math
import io
import zipfile
import threading
import queue as _queue
import json
import glob
import shutil
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

import tempfile
import concurrent.futures

# ==============================================================================
# PROJ_DATA 설정 — shell PROJ_LIB 제거 후 conda env 경로 강제 설정
# 원인: shell PROJ_LIB=/mnt/hdd/miniconda3/share/proj (base conda, VERSION.MINOR=2)가
#       env의 pyproj/GDAL(VERSION.MINOR>=6)와 버전 충돌.
# 수정: (1) pyproj import 전에 env var pop (import 중 caching 방지)
#       (2) sys.prefix/share/proj로 경로 직접 결정
#       (3) osr.SetPROJSearchPaths()로 GDAL PROJ context에도 반영
# ==============================================================================
os.environ.pop('PROJ_LIB', None)
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

import cv2
import numpy as np
import rasterio
from rasterio.windows import from_bounds
import ee
import requests
from requests.adapters import HTTPAdapter
from rasterio.warp import transform as warp_transform_xy

# GDAL PROJ context에 올바른 경로 전달 (rasterio는 GDAL 경유로 PROJ 사용)
try:
    from osgeo import osr as _osr
    _proj_data = os.environ.get('PROJ_DATA', '')
    if _proj_data and hasattr(_osr, 'SetPROJSearchPaths'):
        _osr.SetPROJSearchPaths([_proj_data])
    del _osr, _proj_data
except Exception:
    pass

# 설정/유틸리티 임포트
from pipeline_config import (
    PipelineConfig,
    parse_filename,
    get_rgb_band_indices,
    get_output_folder_name,
    get_output_filename,
    get_segment_names,
)
from pipeline_gui import get_pipeline_config

# =====================================================
# 설정 파라미터 (전역)
# =====================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_KEY_PATH = os.path.join(SCRIPT_DIR, "auth", "ee-service-account-key.json")

# Step 0: 영상 분할 파라미터
DY = 0.216399   # 위도 차이
DX = 0.098737   # 경도 차이

# Step 1 & 2: 공통 다운로드 설정
BOX_SIZE_KM = 150.0
S2_BOX_SIZE_KM = 60.0   # S2 전용: orbit track 내 완전 커버 확보
GEE_DL_MAX_BYTES = 20 * 1024 * 1024
GEE_DL_SAFETY = 0.85
PARALLEL_TILE_WORKERS = 12
MAX_TILE_PX = 1024

# Step 1: Sentinel-2 전용 설정
MAX_CLOUD_PERCENTAGE = 10
SEARCH_WINDOW_DAYS = 90
FALLBACK_YEAR_OFFSET = 1
FALLBACK_WINDOW_DAYS = 30
MIN_OVERLAP_RATIO = 0.7
S2_BANDS = ["B4", "B3", "B2"]

# Step 2: DEM 전용 설정
DEM_SCALE = 30
DEM_TYPE = 'Copernicus'

# HTTP 세션 설정 (전역 공유)
HTTP_SESSION = requests.Session()
_adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3)
HTTP_SESSION.mount('https://', _adapter)
HTTP_SESSION.mount('http://', _adapter)


# =====================================================
# 로그 유틸리티
# =====================================================
class Logger:
    """깔끔한 로그 출력"""
    
    @staticmethod
    def header(title: str):
        print("\n" + "=" * 60)
        print(f"  {title}")
        print("=" * 60)
    
    @staticmethod
    def step(step_num: int, title: str):
        print(f"\n{'─' * 50}")
        print(f"  [Step {step_num}] {title}")
        print(f"{'─' * 50}")
    
    @staticmethod
    def info(msg: str):
        print(f"  ℹ️  {msg}")
    
    @staticmethod
    def success(msg: str):
        print(f"  ✅ {msg}")
    
    @staticmethod
    def warning(msg: str):
        print(f"  ⚠️  {msg}")
    
    @staticmethod
    def error(msg: str):
        print(f"  ❌ {msg}")
    
    @staticmethod
    def progress(current: int, total: int, label: str = ""):
        percent = (current / total) * 100
        bar_len = 30
        filled = int(bar_len * current / total)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r  [{bar}] {percent:.0f}% {label}", end="", flush=True)
        if current == total:
            print()


# =====================================================
# Earth Engine 및 유틸리티
# =====================================================
def init_earth_engine():
    """Earth Engine 초기화 (서비스 계정 사용)"""
    if not os.path.exists(SERVICE_ACCOUNT_KEY_PATH):
        raise FileNotFoundError(f"서비스 계정 키 파일을 찾을 수 없습니다: {SERVICE_ACCOUNT_KEY_PATH}")
    
    with open(SERVICE_ACCOUNT_KEY_PATH, 'r') as f:
        key_data = json.load(f)
    
    service_account_email = key_data.get('client_email')
    credentials = ee.ServiceAccountCredentials(service_account_email, SERVICE_ACCOUNT_KEY_PATH)
    ee.Initialize(credentials)
    Logger.success("Earth Engine 초기화 완료")


def parse_date_from_config(config: PipelineConfig) -> datetime:
    """설정에서 날짜 추출 (yyyymmdd -> datetime)"""
    date_str = config.date
    if date_str == 'unknown':
        # 오늘 날짜 사용
        return datetime.now()
    return datetime(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))


def create_bbox_from_center(lat: float, lon: float, size_km: float) -> list:
    """중심 좌표로부터 bbox 생성 [min_lon, min_lat, max_lon, max_lat]"""
    lat_deg_per_km = 1 / 111.0
    lon_deg_per_km = 1 / (111.0 * math.cos(math.radians(lat)))
    half_size = size_km / 2.0
    return [
        lon - (half_size * lon_deg_per_km),
        lat - (half_size * lat_deg_per_km),
        lon + (half_size * lon_deg_per_km),
        lat + (half_size * lat_deg_per_km)
    ]


def compute_union_bbox(segment_coords_list: list, size_km: float) -> list:
    """모든 세그먼트 bbox의 합집합 [min_lon, min_lat, max_lon, max_lat]"""
    bboxes = [create_bbox_from_center(lat, lon, size_km) for _, (lat, lon) in segment_coords_list]
    return [
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    ]


def estimate_pixels_from_bounds(min_lon, min_lat, max_lon, max_lat, scale):
    """지리적 범위에서 픽셀 크기 추정"""
    center_lat = (min_lat + max_lat) / 2.0
    lon_m_per_deg = 111320.0 * max(0.0, math.cos(math.radians(center_lat)))
    lat_m_per_deg = 110574.0
    width_m = max(0.0, (max_lon - min_lon)) * lon_m_per_deg
    height_m = max(0.0, (max_lat - min_lat)) * lat_m_per_deg
    return max(1, int(math.ceil(width_m / scale))), max(1, int(math.ceil(height_m / scale)))


def save_thumbnail_png(tiff_path: str, png_path: str, max_size: int = 800):
    """TIFF를 PNG 썸네일로 저장"""
    try:
        with rasterio.open(tiff_path) as src:
            # 밴드 읽기 (최대 3밴드)
            bands_to_read = min(src.count, 3)
            data = src.read(list(range(1, bands_to_read + 1)))
            
            # 정규화 (히스토그램 스트레칭)
            # 원본 데이터 타입과 무관하게 float로 변환하여 처리
            normalized_data = np.zeros_like(data, dtype=np.uint8)
            
            for i in range(data.shape[0]):
                band = data[i].astype(float)
                # 유효 데이터(0 초과) 기준으로 2~98% 백분위수 계산
                valid_pixels = band[band > 0]
                if valid_pixels.size > 0:
                    p2, p98 = np.percentile(valid_pixels, [2, 98])
                else:
                    p2, p98 = 0, 1
                
                # 최소/최대값 제한 및 0~255 정규화
                if p98 > p2:
                    band_stretched = (band - p2) / (p98 - p2) * 255.0
                else:
                    band_stretched = band 
                
                band_stretched = np.clip(band_stretched, 0, 255)
                
                # 원본이 0인 부분(NoData)은 그대로 0 유지
                band_stretched[data[i] == 0] = 0
                
                normalized_data[i] = band_stretched.astype(np.uint8)
            
            data = normalized_data
            
            # 리사이즈
            h, w = data.shape[1], data.shape[2]
            scale = min(max_size / w, max_size / h, 1.0)
            new_w, new_h = int(w * scale), int(h * scale)
            
            if bands_to_read >= 3:
                img = np.transpose(data[:3], (1, 2, 0))  # (3, H, W) -> (H, W, 3)
            else:
                img = np.transpose(np.stack([data[0]] * 3), (1, 2, 0))
            
            img = cv2.resize(img, (new_w, new_h))
            cv2.imwrite(png_path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
            return True
    except Exception as e:
        Logger.warning(f"썸네일 생성 실패: {e}")
        return False





# =====================================================
# Sentinel-2 관련 함수
# =====================================================
def search_sentinel2(aoi: ee.Geometry, start_date: str, end_date: str, max_cloud: int):
    """Sentinel-2 컬렉션 검색 (L1C: Top-of-Atmosphere)"""
    return (
        ee.ImageCollection("COPERNICUS/S2_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
    )


def group_images_by_date(collection: ee.ImageCollection) -> dict:
    """컬렉션의 영상들을 날짜별로 그룹화"""
    count = collection.size().getInfo()
    ids = collection.aggregate_array('system:index').getInfo()
    timestamps = collection.aggregate_array('system:time_start').getInfo()
    
    date_groups = defaultdict(list)
    for img_id, ts in zip(ids, timestamps):
        img_date = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d')
        date_groups[img_date].append(img_id)
    return dict(date_groups)


def create_mosaic_for_date(date_str: str, aoi: ee.Geometry, image_ids: list = None) -> ee.Image:
    """특정 날짜의 모든 영상을 모자이킹
    
    Args:
        date_str: 날짜 문자열 (YYYY-MM-DD)
        aoi: 관심 영역
        image_ids: (선택) 사용할 영상 ID 리스트. 제공되면 이 ID들을 직접 사용, 없으면 날짜로 재검색
    """
    if image_ids:
        # ID 리스트가 제공된 경우, 직접 영상 로드
        images = [ee.Image(f"COPERNICUS/S2_HARMONIZED/{img_id}") for img_id in image_ids]
        col = ee.ImageCollection(images)
    else:
        # ID가 없으면 날짜로 재검색
        start = date_str
        end = (datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        col = ee.ImageCollection("COPERNICUS/S2_HARMONIZED").filterBounds(aoi).filterDate(start, end)
        col_size = col.size().getInfo()
        if col_size == 0:
            return None
    
    # 구름 적은 순으로 정렬 후 모자이킹 (가장 맑은 픽셀 우선)
    return col.sort('CLOUDY_PIXEL_PERCENTAGE').mosaic()


def compute_mosaic_metrics(mosaic: ee.Image, aoi: ee.Geometry, date_str: str, collection: ee.ImageCollection) -> dict:
    """모자이크 영상의 AOI 중첩률과 평균 구름량 계산"""
    try:
        aoi_area = aoi.area(1)
        valid_mask = mosaic.select('B4').mask()
        valid_area = valid_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=aoi, scale=100, maxPixels=1e9
        ).get('B4')
        
        start = date_str
        end = (datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        mean_cloud_expr = collection.filterDate(start, end).aggregate_mean('CLOUDY_PIXEL_PERCENTAGE')
        
        results = ee.Dictionary({'aoi_area': aoi_area, 'valid_area': valid_area, 'mean_cloud': mean_cloud_expr}).getInfo()
        aoi_val = results.get('aoi_area', 0)
        valid_val = results.get('valid_area', 0)
        mean_cloud = results.get('mean_cloud', 100)
        
        if valid_val is None: valid_val = 0
        if mean_cloud is None: mean_cloud = 100
        overlap_ratio = min(1.0, valid_val / aoi_val if aoi_val > 0 else 0)
    except Exception as e:
        # 디버깅을 위해 예외 출력
        import traceback
        Logger.warning(f"    Metrics 계산 실패 ({date_str}): {str(e)}")
        # traceback.print_exc()  # 필요시 주석 해제
        overlap_ratio, mean_cloud = 0, 100
    
    return {'date_str': date_str, 'overlap_ratio': overlap_ratio, 'cloud_cover': mean_cloud, 'mosaic': mosaic}


def select_best_date(candidates: list, target_date: datetime) -> dict:
    """최적 날짜 선택 (중첩률 > 구름량 > 날짜 근접)"""
    if not candidates: return None
    def score(c):
        overlap_score = c['overlap_ratio'] * 100
        cloud_score = (100 - c['cloud_cover'])
        date_diff = abs((datetime.strptime(c['date_str'], '%Y-%m-%d') - target_date).days)
        date_score = max(0, 100 - date_diff)
        return overlap_score * 0.40 + cloud_score * 0.50 + date_score * 0.10
    candidates.sort(key=score, reverse=True)
    return candidates[0]


def find_best_sentinel_mosaic(lat: float, lon: float, target_date: datetime, label: str, bbox: list = None):
    """주어진 좌표에서 최적의 Sentinel-2 모자이크 영상 찾기 (3단계 검색 + 최종 fallback)

    bbox가 주어지면 해당 영역으로 검색, 없으면 lat/lon 중심의 BOX_SIZE_KM 박스로 검색.
    """
    if bbox is None:
        bbox = create_bbox_from_center(lat, lon, BOX_SIZE_KM)
    aoi = ee.Geometry.Rectangle(bbox, proj=None, geodesic=False)
    
    Logger.info(f"{label} Sentinel-2 검색:")
    Logger.info(f"  좌표: ({lat}, {lon})")
    Logger.info(f"  BBox: {bbox}")
    Logger.info(f"  목표 날짜: {target_date.strftime('%Y-%m-%d')}")
    
    # 우선 조건을 만족하는 영상 리스트
    preferred_candidates = []
    # 모든 검색된 영상 리스트 (최종 fallback용)
    all_candidates = []
    
    # 병렬 평가 헬퍼 함수
    def _evaluate_dates_parallel(date_groups_items, target_col, overlap_threshold):
        _pref = []
        _all = []
        def process_date(d_str, i_ids):
            _mos = create_mosaic_for_date(d_str, aoi, image_ids=i_ids)
            if _mos:
                return compute_mosaic_metrics(_mos, aoi, d_str, target_col)
            return None
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(process_date, d_str, i_ids) for d_str, i_ids in date_groups_items]
            for future in concurrent.futures.as_completed(futures):
                try:
                    metrics = future.result()
                    if metrics and metrics.get('overlap_ratio', 0) > 0:
                        _all.append(metrics)
                        if metrics['overlap_ratio'] >= overlap_threshold:
                            _pref.append(metrics)
                            Logger.info(f"    ✓ {metrics['date_str']}: 중첩 {metrics['overlap_ratio']*100:.1f}%, 구름 {metrics['cloud_cover']:.1f}%")
                except Exception as e:
                    Logger.warning(f"  병렬 처리 오류: {e}")
        return _pref, _all
    
    # ===== 1차 검색: 목표 날짜 ± 30일 =====
    start_date = (target_date - timedelta(days=SEARCH_WINDOW_DAYS)).strftime('%Y-%m-%d')
    end_date = (target_date + timedelta(days=SEARCH_WINDOW_DAYS)).strftime('%Y-%m-%d')
    Logger.info(f"  1차 검색: {start_date} ~ {end_date}")
    
    col = search_sentinel2(aoi, start_date, end_date, MAX_CLOUD_PERCENTAGE)
    col_size = col.size().getInfo()
    Logger.info(f"  1차 검색 결과: {col_size}개 영상")
    
    if col_size > 0:
        date_groups = group_images_by_date(col)
        Logger.info(f"  날짜별 그룹: {len(date_groups)}개")
        sorted_dates = sorted(date_groups.items(), key=lambda x: len(x[1]), reverse=True)[:20]
        
        pref, all_c = _evaluate_dates_parallel(sorted_dates, col, 0.5)
        preferred_candidates.extend(pref)
        all_candidates.extend(all_c)
    
    # ===== 2차 검색: 1년 전 날짜 ± 60일 (1차에서 우선 영상 없을 때만) =====
    if not preferred_candidates:
        Logger.warning(f"  1차 검색 실패 → 2차 검색 시작")
        fb_date = target_date.replace(year=target_date.year - FALLBACK_YEAR_OFFSET)
        start_date = (fb_date - timedelta(days=FALLBACK_WINDOW_DAYS)).strftime('%Y-%m-%d')
        end_date = (fb_date + timedelta(days=FALLBACK_WINDOW_DAYS)).strftime('%Y-%m-%d')
        Logger.info(f"  2차 검색: {start_date} ~ {end_date}")
        
        col = search_sentinel2(aoi, start_date, end_date, MAX_CLOUD_PERCENTAGE)
        col_size = col.size().getInfo()
        Logger.info(f"  2차 검색 결과: {col_size}개 영상")
        
        if col_size > 0:
            date_groups = group_images_by_date(col)
            Logger.info(f"  날짜별 그룹: {len(date_groups)}개")
            sorted_dates = sorted(date_groups.items(), key=lambda x: len(x[1]), reverse=True)[:20]
            
            pref, all_c = _evaluate_dates_parallel(sorted_dates, col, 0.4)
            preferred_candidates.extend(pref)
            all_candidates.extend(all_c)
    
    # ===== 3차 검색: 계절 무관 (목표 날짜 ± 180일, 구름량 제약 완화) =====
    if not preferred_candidates:
        Logger.warning(f"  2차 검색 실패 → 3차 검색 시작 (계절 무관)")
        wide_start = (target_date - timedelta(days=180)).strftime('%Y-%m-%d')
        wide_end = (target_date + timedelta(days=180)).strftime('%Y-%m-%d')
        Logger.info(f"  3차 검색: {wide_start} ~ {wide_end} (구름량 제약 완화)")
        
        # 구름량 제약 100%로 완화 (모든 영상 검색)
        col_wide = search_sentinel2(aoi, wide_start, wide_end, 100)
        col_size = col_wide.size().getInfo()
        Logger.info(f"  3차 검색 결과: {col_size}개 영상")
        
        if col_size > 0:
            date_groups = group_images_by_date(col_wide)
            Logger.info(f"  날짜별 그룹: {len(date_groups)}개")
            sorted_dates = sorted(date_groups.items(), key=lambda x: len(x[1]), reverse=True)[:30]  # 더 많은 영상 검토
            
            pref, all_c = _evaluate_dates_parallel(sorted_dates, col_wide, 0.3)
            preferred_candidates.extend(pref)
            all_candidates.extend(all_c)
            Logger.info(f"  3차 검색: {len(all_c)}/{len(sorted_dates)}개 모자이킹 성공")
    
    # ===== 최종 선택 로직 =====
    if preferred_candidates:
        # 조건을 만족하는 영상이 있으면 그 중 최선 선택
        best = select_best_date(preferred_candidates, target_date)
        Logger.success(f"  ✓ 조건 만족 영상: {best['date_str']} (중첩 {best['overlap_ratio']*100:.1f}%, 구름 {best['cloud_cover']:.1f}%)")
        return best['mosaic'], aoi, best['date_str']
    elif all_candidates:
        # 조건 미달이지만 검색된 영상이 있으면 최선의 영상 선택
        best = select_best_date(all_candidates, target_date)
        Logger.warning(f"  ⚠️ 조건 미달, 최선 영상 선택: {best['date_str']} (중첩 {best['overlap_ratio']*100:.1f}%, 구름 {best['cloud_cover']:.1f}%)")
        return best['mosaic'], aoi, best['date_str']
    else:
        # 검색된 영상이 전혀 없음
        Logger.error(f"  ✗ 검색된 영상이 전혀 없습니다")
        return None, None, None


# =====================================================
# 타일 다운로드 로직
# =====================================================
def _download_tiled(img, bands, aoi, scale, out_path, dtype, nodata):
    """타일 단위로 이미지 다운로드 (대용량 처리)"""
    bounds = aoi.bounds().getInfo()['coordinates'][0]
    min_lon, min_lat, max_lon, max_lat = bounds[0][0], bounds[0][1], bounds[2][0], bounds[2][1]
    px_w, px_h = estimate_pixels_from_bounds(min_lon, min_lat, max_lon, max_lat, scale)
    b_per_s = 2
    est_bytes = px_w * px_h * len(bands) * b_per_s

    def download_single_tile(target_img, target_bands, target_geom):
        for attempt in range(3):
            try:
                selected = target_img.select(target_bands).unmask(nodata)
                selected = selected.toUint16() if dtype == 'uint16' else selected.toInt16()
                url = selected.getDownloadURL({"region": target_geom, "scale": scale, "format": "GEO_TIFF"})
                r = HTTP_SESSION.get(url, timeout=600)
                r.raise_for_status()
                content = r.content
                if content[:4] in (b'II*\x00', b'MM\x00*'): return content
                if content[:2] == b'PK':
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        tifs = [n for n in zf.namelist() if n.lower().endswith(('.tif', '.tiff'))]
                        if tifs: return zf.read(tifs[0])
                raise RuntimeError("Format error")
            except Exception as e:
                if attempt == 2: raise
                import time; time.sleep((attempt+1)*2)

    if est_bytes <= GEE_DL_MAX_BYTES * GEE_DL_SAFETY:
        blob = download_single_tile(img, bands, aoi)
        with open(out_path, 'wb') as f: f.write(blob)
        return

    # 타일 분할 로직
    target_side = int(math.sqrt(GEE_DL_MAX_BYTES * GEE_DL_SAFETY / (len(bands) * b_per_s)))
    target_side = max(512, min(target_side, MAX_TILE_PX))
    ncols, nrows = max(1, int(math.ceil(px_w / target_side))), max(1, int(math.ceil(px_h / target_side)))
    lon_step, lat_step = (max_lon - min_lon) / ncols, (max_lat - min_lat) / nrows

    with tempfile.TemporaryDirectory() as temp_dir:
        downloaded_files = []
        list_lock = threading.Lock()
        q = _queue.Queue()
        
        for r in range(nrows):
            for c in range(ncols):
                q.put((min_lon + c*lon_step, min_lat + r*lat_step, min_lon + (c+1)*lon_step, min_lat + (r+1)*lat_step, r, c))
                
        total_tiles = nrows * ncols
        completed_tiles = 0
        Logger.info(f"  타일 다운로드 시작: 총 {total_tiles}개 (12 스레드)")

        def worker():
            nonlocal completed_tiles
            while not q.empty():
                 try: b = q.get_nowait()
                 except: break
                 try:
                     r_idx, c_idx = b[4], b[5]
                     geom = ee.Geometry.Rectangle([b[0], b[1], b[2], b[3]], proj=None, geodesic=False)
                     blob = download_single_tile(img, bands, geom)
                     if blob:
                         tile_path = os.path.join(temp_dir, f"tile_{r_idx}_{c_idx}.tif")
                         with open(tile_path, 'wb') as f:
                             f.write(blob)
                         with list_lock:
                             downloaded_files.append(tile_path)
                             completed_tiles += 1
                             Logger.progress(completed_tiles, total_tiles, f"Downloading tile {r_idx},{c_idx}")
                 except Exception as e:
                     Logger.warning(f"  타일 다운로드 오류: {e}")
                 finally:
                     q.task_done()

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(PARALLEL_TILE_WORKERS)]
        for t in threads: t.start()
        q.join()

        if downloaded_files:
            list_txt = os.path.join(temp_dir, "tile_list.txt")
            with open(list_txt, "w") as f:
                for tf in downloaded_files:
                    f.write(tf + "\n")
            
            vrt_path = os.path.join(temp_dir, "mosaic.vrt")
            nodata_str = " ".join([str(nodata)] * len(bands))
            
            cmd_vrt = [
                "gdalbuildvrt",
                "-input_file_list", list_txt,
                "-srcnodata", nodata_str,
                "-vrtnodata", nodata_str,
                vrt_path
            ]
            
            cmd_tif = [
                "gdal_translate",
                vrt_path, out_path,
                "-co", "COMPRESS=LZW",
                "-co", "TILED=YES",
                "-co", "BIGTIFF=IF_SAFER"
            ]
            
            try:
                subprocess.run(cmd_vrt, check=True, capture_output=True)
                subprocess.run(cmd_tif, check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                Logger.error(f"GDAL 모자이킹 실패: {e.stderr.decode('utf-8', errors='ignore')}")
                raise


# =====================================================
# 단계별 처리 함수
# =====================================================
def run_step_0_split_image(config: PipelineConfig, segment_base_dir: str, segment_label: str, segment_coords: tuple):
    """Step 0: 해당 세그먼트 영상 추출 및 저장"""
    
    save_dir = os.path.join(segment_base_dir, "00_Divided_image")
    os.makedirs(save_dir, exist_ok=True)
    
    lat, lon = segment_coords
    
    # 원본 TIFF 로드
    with rasterio.open(config.input_path) as src:
        data = src.read()  # (C, H, W)
        h, w = data.shape[1], data.shape[2]
    
    # 세그먼트별 분할
    if config.num_segments == 1:
        segment_data = data
    elif config.num_segments == 2:
        mid = h // 2
        overlap = 1000
        if segment_label.lower() == "upper":
            segment_data = data[:, 0:mid + (overlap // 2), :]
        else:  # lower
            segment_data = data[:, mid - (overlap // 2):h, :]
    else:  # 3
        half_ch, overlap = 3000, 1000
        mid = h // 2
        c_start = max(0, mid - half_ch)
        c_end = min(h, c_start + 6000)
        t_end = min(c_start + overlap, h)
        b_start = max(c_end - overlap, 0)
        
        if segment_label.lower() == "top":
            segment_data = data[:, 0:t_end, :]
        elif segment_label.lower() == "center":
            segment_data = data[:, c_start:c_end, :]
        else:  # bottom
            segment_data = data[:, b_start:h, :]
    
    # RGB 밴드 추출 (인덱스 확인용 - 실제 저장은 원본 전체 밴드 수행)
    rgb_indices = get_rgb_band_indices(config.band_count)
    
    # 저장 (모든 밴드 포함)
    merged_path = os.path.join(save_dir, f"merged_{segment_label.lower()}.tif")
    with rasterio.open(
        merged_path, 'w',
        driver='GTiff',
        height=segment_data.shape[1],
        width=segment_data.shape[2],
        count=segment_data.shape[0],
        dtype=segment_data.dtype,
    ) as dst:
        dst.write(segment_data)
    
    # 좌표 저장
    coord_path = os.path.join(save_dir, "divided_coordinates.txt")
    with open(coord_path, 'w') as f:
        f.write(f"{lat} {lon} {segment_label.lower()}\n")
    
    # 썸네일 저장 (savve_intermediate가 True일 때만)
    if config.save_intermediate:
        png_path = os.path.join(save_dir, "Raw_data.png")
        save_thumbnail_png(merged_path, png_path)
    
    Logger.success(f"{segment_label} 영상 분할 완료 → {os.path.basename(merged_path)}")
    
    return merged_path, coord_path, rgb_indices


def download_shared_sentinel(config: PipelineConfig, shared_dir: str,
                              segment_coords_list: list, target_date: datetime):
    """모든 세그먼트를 커버하는 영역의 Sentinel-2를 한 번에 다운로드"""
    # 기존 파일 재사용 (S2_mosaic_{date}.tif)
    existing = sorted(glob.glob(os.path.join(shared_dir, "S2_mosaic_*.tif")))
    if existing:
        path = existing[0]
        date_str = os.path.splitext(os.path.basename(path))[0].replace("S2_mosaic_", "")
        Logger.info(f"공유 Sentinel-2 기존 파일 재사용: {os.path.basename(path)} ({date_str})")
        return path, date_str

    bbox = compute_union_bbox(segment_coords_list, S2_BOX_SIZE_KM)
    center_lat = (bbox[1] + bbox[3]) / 2
    center_lon = (bbox[0] + bbox[2]) / 2

    mosaic, aoi, date_str = find_best_sentinel_mosaic(
        center_lat, center_lon, target_date, "Shared", bbox=bbox
    )
    if mosaic is None:
        Logger.warning("공유 Sentinel-2 영상을 찾을 수 없습니다")
        return None, None

    os.makedirs(shared_dir, exist_ok=True)
    output_path = os.path.join(shared_dir, f"S2_mosaic_{date_str}.tif")
    _download_tiled(mosaic.clip(aoi), S2_BANDS, aoi, 10, output_path, 'uint16', 0)

    if config.save_intermediate:
        save_thumbnail_png(output_path, os.path.join(shared_dir, "Sentinel2.png"))

    Logger.success(f"공유 Sentinel-2 다운로드 완료 ({date_str})")
    return output_path, date_str


def download_shared_dem(config: PipelineConfig, shared_dir: str, segment_coords_list: list) -> str:
    """모든 세그먼트를 커버하는 영역의 DEM을 한 번에 다운로드"""
    dem_filename = "SRTM_DEM.tif" if DEM_TYPE == "SRTM" else "Copernicus_DEM.tif"
    output_path = os.path.join(shared_dir, dem_filename)

    # 기존 파일 재사용
    if os.path.exists(output_path):
        Logger.info(f"공유 DEM 기존 파일 재사용: {dem_filename}")
        return output_path

    bbox = compute_union_bbox(segment_coords_list, BOX_SIZE_KM)
    aoi = ee.Geometry.Rectangle(bbox, proj=None, geodesic=False)

    os.makedirs(shared_dir, exist_ok=True)

    if DEM_TYPE == "SRTM":
        dem = ee.Image("USGS/SRTMGL1_003").select('elevation')
        _download_tiled(dem.clip(aoi), ['elevation'], aoi, DEM_SCALE, output_path, 'int16', -9999)
    elif DEM_TYPE == "Copernicus":
        dem = ee.ImageCollection("COPERNICUS/DEM/GLO30").select('DEM').mosaic()
        _download_tiled(dem.clip(aoi), ['DEM'], aoi, DEM_SCALE, output_path, 'int16', 0)
    else:
        raise ValueError(f"Invalid DEM type: {DEM_TYPE}")

    Logger.success(f"공유 DEM 다운로드 완료")
    return output_path


def download_shared_geoid(config: PipelineConfig, shared_dir: str, segment_coords_list: list) -> str:
    """모든 세그먼트를 커버하는 영역의 Geoid을 한 번에 다운로드"""
    output_path = os.path.join(shared_dir, "Geoid.tif")

    # 기존 파일 재사용
    if os.path.exists(output_path):
        Logger.info(f"공유 Geoid 기존 파일 재사용: Geoid.tif")
        return output_path

    url = "https://grid-partner-share.s3.amazonaws.com/egm2008/us_nga_egm2008_1.tif"
    bbox = compute_union_bbox(segment_coords_list, BOX_SIZE_KM + 50)
    min_lon, min_lat, max_lon, max_lat = bbox

    os.makedirs(shared_dir, exist_ok=True)

    with rasterio.open(url) as src:
        window = from_bounds(min_lon, min_lat, max_lon, max_lat, src.transform)
        subset_data = src.read(1, window=window)
        new_transform = src.window_transform(window)

        profile = src.profile
        profile.update({
            'height': subset_data.shape[0],
            'width': subset_data.shape[1],
            'transform': new_transform,
            'compress': 'lzw',
            'crs': 'EPSG:4326',
        })

        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(subset_data, 1)

    Logger.success(f"공유 Geoid 다운로드 완료")
    return output_path


def _link_shared_to_segment(shared_path: str, seg_open_dir: str, target_filename: str) -> str:
    """공유 파일을 세그먼트 폴더에 심볼릭 링크 (실패 시 복사 fallback)"""
    os.makedirs(seg_open_dir, exist_ok=True)
    dst = os.path.join(seg_open_dir, target_filename)
    if os.path.lexists(dst):
        return dst
    src_abs = os.path.abspath(shared_path)
    try:
        os.symlink(src_abs, dst)
    except (OSError, NotImplementedError) as e:
        Logger.warning(f"심볼릭 링크 생성 실패, 복사로 대체: {e}")
        shutil.copy2(src_abs, dst)
    return dst


def run_step_3_geometric_correction(config: PipelineConfig, segment_base_dir: str, segment_label: str,
                                    segment_coords: tuple, target_path: str, reference_path: str,
                                    dem_path: str, geoid_path: str, rgb_indices: list,
                                    gcp_chips_dir: str = None, gcp_chip_resolution: float = None):
    """Step 3: 기하보정 실행"""

    lat, lon = segment_coords

    geo_script_path = os.path.join(SCRIPT_DIR, "03.geometric_correction", "geometric_correction.py")
    output_dir = segment_base_dir  # 각 세그먼트 폴더에 직접 저장

    cmd = [
        sys.executable,
        geo_script_path,
        "--dem", os.path.abspath(dem_path),
        "--geoid", os.path.abspath(geoid_path),
        "--ref", os.path.abspath(reference_path),
        "--target", os.path.abspath(target_path),
        "--output", os.path.abspath(output_dir),
        "--lat", str(lat),
        "--lon", str(lon),
        "--res", str(config.target_resolution),
        "--bands"
    ] + [str(i) for i in rgb_indices]

    if gcp_chips_dir:
        cmd += ["--gcp_chips", os.path.abspath(gcp_chips_dir)]
        cmd += ["--gcp_chip_res", str(gcp_chip_resolution if gcp_chip_resolution else 1.2)]
    
    try:
        cwd_path = os.path.join(SCRIPT_DIR, "03.geometric_correction")
        env = os.environ.copy()
        # rpcfit, lightglue 등이 있는 SCRIPT_DIR(Code)도 PYTHONPATH에 추가
        env["PYTHONPATH"] = f"{SCRIPT_DIR}:{cwd_path}:{env.get('PYTHONPATH', '')}"
        
        subprocess.check_call(cmd, cwd=cwd_path, env=env)
        Logger.success(f"{segment_label} 기하보정 완료")
        return True
    except subprocess.CalledProcessError as e:
        Logger.error(f"{segment_label} 기하보정 실패 (Exit Code: {e.returncode})")
        return False
    except Exception as e:
        Logger.error(f"{segment_label} 실행 오류: {e}")
        return False



def parse_date_time_from_config(config: PipelineConfig) -> tuple:
    """설정에서 날짜와 시간 추출"""
    return config.date, config.time


def get_band_count_str(config: PipelineConfig) -> str:
    """밴드 수 문자열 반환 (예: 8band)"""
    return f"{config.band_count}band"


def run_step_4_mosaic(config: PipelineConfig, output_base_dir: str, segment_dirs: list):
    """Step 4: GDAL 기반 결과물 모자이킹"""
    
    yyyymmdd, HHMMSS = parse_date_time_from_config(config)
    band_str = get_band_count_str(config)
    
    # 각 세그먼트의 07_Final_results에서 TIFF 수집
    tif_list = []
    for seg_dir in segment_dirs:
        final_dir = os.path.join(seg_dir, "07_Final_results")
        if os.path.exists(final_dir):
            tifs = glob.glob(os.path.join(final_dir, f"bb_l1c_{yyyymmdd}_{HHMMSS}_{band_str}_*.tiff"))
            tif_list.extend(tifs)
    
    if not tif_list:
        Logger.warning("모자이킹할 TIFF 파일을 찾을 수 없습니다")
        return None
    
    Logger.info(f"모자이킹 대상: {len(tif_list)}개 파일")
    
    # VRT 생성을 위한 임시 파일 리스트
    list_txt = os.path.join(output_base_dir, "_temp_tif_list.txt")
    with open(list_txt, "w", encoding="utf-8") as f:
        for p in tif_list:
            f.write(p + "\n")
    
    # 밴드 수 확인
    with rasterio.open(tif_list[0]) as ds:
        band_count = ds.count
    
    nodata_str = " ".join(["0"] * band_count)
    
    # VRT 생성
    vrt_path = os.path.join(output_base_dir, "_temp_mosaic.vrt")
    cmd_vrt = [
        "gdalbuildvrt",
        "-input_file_list", list_txt,
        "-srcnodata", nodata_str,
        "-vrtnodata", nodata_str,
        vrt_path
    ]
    
    # 최종 출력 파일명
    output_filename = f"bb_l1c_{yyyymmdd}_{HHMMSS}_{band_str}.tiff"
    output_path = os.path.join(output_base_dir, output_filename)
    
    # VRT → GeoTIFF
    cmd_tif = [
        "gdal_translate",
        vrt_path, output_path,
        "-co", "COMPRESS=LZW",
        "-co", "TILED=YES",
        "-co", "BIGTIFF=IF_SAFER"
    ]
    
    try:
        subprocess.run(cmd_vrt, check=True, capture_output=True)
        subprocess.run(cmd_tif, check=True, capture_output=True)
        Logger.success(f"모자이킹 완료 → {output_filename}")
        
        # 임시 파일 정리
        os.remove(list_txt)
        os.remove(vrt_path)
        
        return output_path
    except subprocess.CalledProcessError as e:
        Logger.error(f"모자이킹 실패: {e}")
        return None


def write_center_coordinates(mosaic_path: str, processing_time_sec: float = None,
                             correction_status: dict = None):
    """기하보정된 영상의 중심점 좌표를 txt + xlsx 파일로 저장

    Args:
        mosaic_path: 모자이킹된 GeoTIFF 파일 경로
        processing_time_sec: Step 3 처리 시간 (초)
        correction_status: 각 세그먼트의 보정 방식 정보 딕셔너리
            예: {'Top': 'normal', 'Center': 'normal', 'Bottom': 'extrapolated'}
            None이면 기록하지 않음.

    Returns:
        (txt_path, lon, lat) — 실패 시 (None, None, None)
    """
    if not mosaic_path or not os.path.exists(mosaic_path):
        Logger.warning("중심점 좌표 저장 실패: 파일이 존재하지 않습니다")
        return None, None, None

    try:
        with rasterio.open(mosaic_path) as src:
            width = src.width
            height = src.height
            center_col = width / 2.0
            center_row = height / 2.0
            crs = src.crs
            transform = src.transform
            center_x, center_y = transform * (center_col, center_row)
            lons, lats = warp_transform_xy(crs, "EPSG:4326", [center_x], [center_y])

        output_dir = os.path.dirname(mosaic_path)
        base_name = os.path.splitext(os.path.basename(mosaic_path))[0]
        txt_path = os.path.join(output_dir, f"{base_name}_center_coordinates.txt")

        # ── txt 저장 ─────────────────────────────────────────────────────────
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("=" * 50 + "\n")
            f.write("기하보정된 영상 중심점 좌표 정보\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"파일명: {os.path.basename(mosaic_path)}\n\n")
            f.write(f"중심점 좌표:\n")
            f.write(f"  경도 (Longitude): {lons[0]:.8f}\n")
            f.write(f"  위도 (Latitude): {lats[0]:.8f}\n\n")
            f.write(f"좌표계 (CRS): {crs}\n\n")
            f.write(f"이미지 크기:\n")
            f.write(f"  너비 (Width): {width} pixels\n")
            f.write(f"  높이 (Height): {height} pixels\n\n")
            if processing_time_sec is not None:
                f.write(f"기하보정 처리 시간 (Step 3): {processing_time_sec:.2f} 초\n")

            if correction_status:
                f.write("\n" + "=" * 50 + "\n")
                f.write("세그먼트별 기하보정 방식\n")
                f.write("=" * 50 + "\n")
                all_normal = all(v == 'normal' for v in correction_status.values())
                for seg, method in correction_status.items():
                    if method == 'normal':
                        icon = "✅"
                        desc = "정상 기하보정 (RPC 기반)"
                    elif method == 'extrapolated':
                        icon = "⚠️"
                        desc = "외삽 기하보정 (RPC 생성 실패 → Strip_correction_3D 외삽)"
                    else:
                        icon = "ℹ️"
                        desc = method
                    f.write(f"  {icon} {seg:<10}: {desc}\n")
                f.write("\n")
                if all_normal:
                    f.write("결과 품질: 모든 세그먼트 정상 기하보정 완료\n")
                else:
                    failed = [k for k, v in correction_status.items() if v == 'extrapolated']
                    f.write(f"결과 품질: 일부 세그먼트 외삽 적용됨 ({', '.join(failed)})\n")
                    f.write("  → 외삽 영역은 중첩 영역 GCP 기반 다항식 외삽이므로\n")
                    f.write("    정상 기하보정 대비 정확도가 낮을 수 있습니다.\n")

        Logger.success(f"중심점 좌표 저장 완료 → {os.path.basename(txt_path)}")

        # ── xlsx 저장 ─────────────────────────────────────────────────────────
        try:
            import openpyxl
            from openpyxl.styles import Font, Alignment, PatternFill
            from openpyxl.utils import get_column_letter

            xlsx_path = os.path.join(output_dir, f"{base_name}_center_coordinates.xlsx")
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Center Coordinates"

            header_fill = PatternFill("solid", fgColor="4472C4")
            header_font = Font(bold=True, color="FFFFFF")

            headers = [
                "파일명", "경도 (Longitude)", "위도 (Latitude)",
                "좌표계 (CRS)", "너비 (pixels)", "높이 (pixels)",
                "처리 시간 (초)"
            ]
            for col_idx, h in enumerate(headers, start=1):
                cell = ws.cell(row=1, column=col_idx, value=h)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

            seg_quality = ""
            if correction_status:
                if all(v == 'normal' for v in correction_status.values()):
                    seg_quality = "정상"
                else:
                    failed = [k for k, v in correction_status.items() if v == 'extrapolated']
                    seg_quality = f"외삽 포함 ({', '.join(failed)})"

            row_data = [
                os.path.basename(mosaic_path),
                round(lons[0], 8),
                round(lats[0], 8),
                str(crs),
                width,
                height,
                round(processing_time_sec, 2) if processing_time_sec is not None else "",
            ]
            for col_idx, val in enumerate(row_data, start=1):
                ws.cell(row=2, column=col_idx, value=val)

            # 열 너비 자동 조정
            col_widths = [45, 20, 18, 15, 14, 14, 16]
            for i, w in enumerate(col_widths, start=1):
                ws.column_dimensions[get_column_letter(i)].width = w

            wb.save(xlsx_path)
            Logger.success(f"중심점 좌표 Excel 저장 완료 → {os.path.basename(xlsx_path)}")
        except Exception as e:
            Logger.warning(f"Excel 저장 실패: {e}")

        return txt_path, lons[0], lats[0]

    except Exception as e:
        Logger.error(f"중심점 좌표 저장 실패: {e}")
        return None, None, None


def _update_main_sheet_with_coords(config: PipelineConfig, mosaic_path: str):
    """처리 완료 후 BlueBON_Geometric_Correction.csv 의 Actual Latitude/Longitude 컬럼 업데이트.

    config.date (yyyymmdd) + config.time (HHMMSS) 로 Capture Start Time 컬럼을 매칭.
    CSV와 xlsx 모두 지원하며, 파일이 없으면 조용히 스킵한다.
    """
    import csv as _csv

    # Dataset 폴더 위치 추정: input_path 기준으로 두 단계 위
    dataset_dir = os.path.dirname(os.path.dirname(config.input_path))
    candidates = [
        os.path.join(dataset_dir, "BlueBON_Geometric_Correction.csv"),
        os.path.join(dataset_dir, "BlueBON_Geometric_Correction.xlsx"),
    ]
    sheet_path = next((p for p in candidates if os.path.exists(p)), None)
    if not sheet_path:
        return

    # 모자이킹 파일에서 실제 중심 좌표 추출
    try:
        with rasterio.open(mosaic_path) as src:
            cx, cy = src.transform * (src.width / 2.0, src.height / 2.0)
            lons, lats = warp_transform_xy(src.crs, "EPSG:4326", [cx], [cy])
        actual_lon, actual_lat = round(lons[0], 8), round(lats[0], 8)
    except Exception as e:
        Logger.warning(f"좌표 추출 실패 (시트 업데이트 스킵): {e}")
        return

    # 매칭 키: config.date(yyyymmdd) + config.time(HHMMSS) → 앞 4자리(HHMM)만 사용
    date_str = getattr(config, 'date', None)
    time_str = getattr(config, 'time', None)
    if not date_str or not time_str or date_str == 'unknown':
        return
    # Capture Start Time 패턴: 2026-04-19T10:03:38
    match_dt_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}T{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"

    ext = os.path.splitext(sheet_path)[1].lower()

    if ext == ".csv":
        try:
            with open(sheet_path, 'r', encoding='utf-8', newline='') as f:
                rows = list(_csv.reader(f))
            if not rows:
                return
            header = rows[0]

            lat_col = lon_col = None
            for i, name in enumerate(header):
                n = name.strip().lower().replace('\n', ' ')
                if 'actual' in n and 'lat' in n:
                    lat_col = i
                if 'actual' in n and 'lon' in n:
                    lon_col = i
            if lat_col is None:
                lat_col = len(header)
                header.append("Actual\nLatitude")
                rows[0] = header
            if lon_col is None:
                lon_col = len(header)
                header.append("Actual\nLongitude")
                rows[0] = header

            updated = False
            for row in rows[1:]:
                if not row:
                    continue
                capture_time = row[4] if len(row) > 4 else ""
                if match_dt_str in str(capture_time):
                    while len(row) <= max(lat_col, lon_col):
                        row.append('')
                    row[lat_col] = str(actual_lat)
                    row[lon_col] = str(actual_lon)
                    updated = True
                    break

            if updated:
                with open(sheet_path, 'w', encoding='utf-8', newline='') as f:
                    _csv.writer(f).writerows(rows)
                Logger.success(f"시트 업데이트 완료 → {os.path.basename(sheet_path)} "
                               f"(lat={actual_lat}, lon={actual_lon})")
            else:
                Logger.warning(f"시트에서 매칭 행을 찾지 못했습니다 ({match_dt_str})")
        except Exception as e:
            Logger.warning(f"CSV 시트 업데이트 실패: {e}")

    elif ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(sheet_path)
            ws = wb.active
            header = [c.value for c in ws[1]]

            lat_col = lon_col = None
            for i, name in enumerate(header, start=1):
                n = str(name or '').lower()
                if 'actual' in n and 'lat' in n:
                    lat_col = i
                if 'actual' in n and 'lon' in n:
                    lon_col = i
            if lat_col is None:
                lat_col = len(header) + 1
                ws.cell(row=1, column=lat_col, value="Actual\nLatitude")
            if lon_col is None:
                lon_col = len(header) + 2 if lat_col == len(header) + 1 else len(header) + 1
                ws.cell(row=1, column=lon_col, value="Actual\nLongitude")

            updated = False
            for row in ws.iter_rows(min_row=2):
                capture_time = str(row[4].value or "")
                if match_dt_str in capture_time:
                    ws.cell(row=row[0].row, column=lat_col, value=actual_lat)
                    ws.cell(row=row[0].row, column=lon_col, value=actual_lon)
                    updated = True
                    break

            wb.save(sheet_path)
            wb.close()
            if updated:
                Logger.success(f"시트 업데이트 완료 → {os.path.basename(sheet_path)} "
                               f"(lat={actual_lat}, lon={actual_lon})")
            else:
                Logger.warning(f"시트에서 매칭 행을 찾지 못했습니다 ({match_dt_str})")
        except Exception as e:
            Logger.warning(f"Excel 시트 업데이트 실패: {e}")


def reorganize_geometric_correction_outputs(config: PipelineConfig, segment_base_dir: str, segment_label: str):
    """geometric_correction.py 실행 후 결과물 재정리
    
    이 함수는 geometric_correction.py가 생성한 파일들을 사용자가 원하는 폴더 구조로 재정리합니다.
    RPC 연산 로직은 전혀 수정하지 않고, 파일 복사/이동/이름변경만 수행합니다.
    """
    yyyymmdd, HHMMSS = parse_date_time_from_config(config)
    band_str = get_band_count_str(config)
    location = segment_label.lower()
    
    Logger.info(f"{segment_label} 결과물 재정리 시작...")

    # 5. 07_Final_results 파일 이름 변경 (항상 수행해야 함)
    final_dir = os.path.join(segment_base_dir, "07_Final_results")
    if os.path.exists(final_dir):
        # {base_name}_final_rpcm.tif → bb_{level}_{yyyymmdd}_{HHMMSS}_{band}_{location}.tiff
        renamed_count = 0
        # 모든 tiff 파일 검색 (bb_ 로 시작하는 이미 변경된 파일 제외)
        for tif_file in glob.glob(os.path.join(final_dir, "*.tif*")):
            base_name = os.path.basename(tif_file)
            if base_name.startswith("bb_"):
                continue
                
            if tif_file.endswith(('.tif', '.tiff')):
                # 사용자 요청 포맷: bb_{level}_{yyyymmdd}_{HHMMSS}_{band}_{location}.tiff
                new_name = f"bb_l1c_{yyyymmdd}_{HHMMSS}_{band_str}_{location}.tiff"
                new_path = os.path.join(final_dir, new_name)
                
                # 원본이 merged_{location}.tif 이거나 _final_rpcm.tif 인 경우 모두 처리
                if f"merged_{location}" in base_name.lower() or "_final_rpcm" in base_name or "final" in base_name:
                    if os.path.exists(tif_file) and not os.path.exists(new_path):
                        shutil.move(tif_file, new_path)
                        renamed_count += 1
                        Logger.info(f"  ✓ 07: {base_name} → {new_name}")
        
        # RPC 파일들도 이름 변경 (RPB or rpb)
        for rpb_file in glob.glob(os.path.join(final_dir, "*.*")):
             if rpb_file.lower().endswith('.rpb'):
                 base_name = os.path.basename(rpb_file)
                 if f"merged_{location}" in base_name.lower() or "_final_rpcm" in base_name or "final" in base_name:
                    new_name = f"bb_l1c_{yyyymmdd}_{HHMMSS}_{band_str}_{location}.RPB"
                    new_path = os.path.join(final_dir, new_name)
                    if os.path.exists(rpb_file) and not os.path.exists(new_path):
                        shutil.move(rpb_file, new_path)
                        renamed_count += 1
        
        if renamed_count > 0:
            Logger.info(f"  ✓ 07: {renamed_count}개 파일 이름 변경")

    # gcp_chips → 06_GCPs 이름 변경 (save_intermediate 여부와 무관하게 항상 수행)
    gcp_src = os.path.join(segment_base_dir, "gcp_chips")
    gcp_dst = os.path.join(segment_base_dir, "06_GCPs")
    Logger.info(f"  🔍 06_GCPs 확인: gcp_chips={os.path.exists(gcp_src)}, 06_GCPs={os.path.exists(gcp_dst)}")
    if os.path.exists(gcp_src) and not os.path.exists(gcp_dst):
        shutil.move(gcp_src, gcp_dst)
        Logger.info(f"  ✓ 06: gcp_chips → 06_GCPs 이름 변경 완료")
    elif os.path.exists(gcp_src) and os.path.exists(gcp_dst):
        # 이미 06_GCPs가 있으면 새 gcp_chips 내용을 합쳐 넣고 제거
        for item in os.listdir(gcp_src):
            s = os.path.join(gcp_src, item)
            d = os.path.join(gcp_dst, item)
            if not os.path.exists(d):
                shutil.move(s, d)
        shutil.rmtree(gcp_src)
        Logger.info(f"  ✓ 06: gcp_chips 내용 06_GCPs에 병합 완료")
    elif not os.path.exists(gcp_src) and not os.path.exists(gcp_dst):
        # gcp_chips가 없으면 빈 06_GCPs 생성 (STEP15/16 실패 시 폴더 자체가 안 만들어지는 케이스)
        os.makedirs(gcp_dst, exist_ok=True)
        Logger.warning(f"  ⚠️ gcp_chips 없음 → 빈 06_GCPs 생성 (STEP15/16 chip 추출 실패로 추정)")
    else:
        Logger.info(f"  ✓ 06: 06_GCPs 이미 존재 (유지)")

    if not config.save_intermediate:
        # 삭제 후 리턴
        delete_folders = [
            "01_preprocessing", "step14_visualizations", "step15_rpc",
             "step15_rpc_eval", "step11_5_depth", "raw_target",
            "03_Initial_correction", "04_patches", "05_LOFTR_result", "05_SATLOFTR_result",
            "05_SuperPoint_results", "05_ROMAV2_result", "05_SIFT_result",
            "step16_final_corrected"
        ]
        deleted_count = 0
        for folder in delete_folders:
            folder_path = os.path.join(segment_base_dir, folder)
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                deleted_count += 1
        if deleted_count > 0:
            Logger.info(f"  ✓ {deleted_count}개 중간 결과물 폴더 삭제")
        Logger.success(f"{segment_label} 결과물 재정리 완료")
        return

    # 중간 결과물 저장이 켜져 있을 경우 기존 재정리 로직 실행
    # 1. 03_Initial_correction 파일 이름 변경
    initial_dir = os.path.join(segment_base_dir, "03_Initial_correction")
    if os.path.exists(initial_dir):
        # target_initial_AFFINE_corrected.tif -> bb_l1b_{yyyymmdd}_{HHMMSS}_{band}.tiff
        for old_name in ["target_initial_AFFINE_corrected.tif", "target_initial_AFFINE_corrected.tiff"]:
            old_tif = os.path.join(initial_dir, old_name)
            if os.path.exists(old_tif):
                new_tif = os.path.join(initial_dir, f"bb_l1b_{yyyymmdd}_{HHMMSS}_{band_str}.tiff")
                shutil.move(old_tif, new_tif)
                Logger.info(f"  ✓ 03: {old_name} → bb_l1b_{yyyymmdd}_{HHMMSS}_{band_str}.tiff")
                break
        
        # mask 파일도 변경
        old_mask = os.path.join(initial_dir, "target_initial_AFFINE_corrected_mask.png")
        if os.path.exists(old_mask):
            new_mask = os.path.join(initial_dir, f"bb_l1b_{yyyymmdd}_{HHMMSS}_{band_str}_mask.png")
            shutil.move(old_mask, new_mask)
            Logger.info(f"  ✓ 03: mask 파일 이름 변경")
    
    # 2. 04_patches 폴더 정리 (features_NMS.csv, BlueBON_features_NMS.png만 남김)
    patches_dir = os.path.join(segment_base_dir, "04_patches")
    if os.path.exists(patches_dir):
        keep_files = ["features_NMS.csv", "BlueBON_features_NMS.png"]
        hidden_count = 0
        for item in os.listdir(patches_dir):
            if item not in keep_files and not item.startswith('.'):
                old_path = os.path.join(patches_dir, item)
                new_path = os.path.join(patches_dir, f".hidden_{item}")
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    shutil.move(old_path, new_path)
                    hidden_count += 1
        if hidden_count > 0:
            Logger.info(f"  ✓ 04: {hidden_count}개 파일 숨김 처리")
    
    # 3. 05_{algorithm}_result 폴더 정리
    superpoint_results_dir = os.path.join(segment_base_dir, "05_SuperPoint_results")
    if os.path.exists(superpoint_results_dir):
        step14_vis = os.path.join(superpoint_results_dir, "step14_visualizations")
        
        algorithm_result_dir = None
        for item in os.listdir(segment_base_dir):
            if item.startswith("05_") and item.endswith("_result") and item != "05_SuperPoint_results":
                algorithm_result_dir = os.path.join(segment_base_dir, item)
                break
        
        if os.path.exists(step14_vis) and algorithm_result_dir:
            for item in os.listdir(step14_vis):
                src = os.path.join(step14_vis, item)
                dst = os.path.join(algorithm_result_dir, item)
                if os.path.exists(src):
                    if os.path.isdir(src):
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
            Logger.info(f"  ✓ 05: step14_visualizations → {os.path.basename(algorithm_result_dir)} 이동")
        
        if os.path.exists(superpoint_results_dir):
            shutil.rmtree(superpoint_results_dir)
            Logger.info(f"  ✓ 05: 05_SuperPoint_results 폴더 삭제")
    
    # 4. 06_GCPs: 위에서 이미 이름 변경 완료 (중복 처리 불필요)
    
    # 6. 불필요한 폴더 삭제
    delete_folders = [
        "01_preprocessing", "step14_visualizations", "step15_rpc",
         "step15_rpc_eval", "step11_5_depth", "raw_target","step16_final_corrected"
    ]
    deleted_count = 0
    for folder in delete_folders:
        folder_path = os.path.join(segment_base_dir, folder)
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
            deleted_count += 1
    if deleted_count > 0:
        Logger.info(f"  ✓ {deleted_count}개 불필요 폴더 삭제")
    
    Logger.success(f"{segment_label} 결과물 재정리 완료")



def calculate_segment_coordinates(config: PipelineConfig):
    """세그먼트별 중심 좌표 계산"""
    c_lat = config.center_lat
    c_lon = config.center_lon
    
    if config.num_segments == 1:
        return [("Full", (c_lat, c_lon))]
    elif config.num_segments == 2:
        off_y, off_x = DY * 0.75, DX * 0.75
        return [
            ("Upper", (c_lat + off_y, c_lon + off_x)),
            ("Lower", (c_lat - off_y, c_lon - off_x))
        ]
    else:  # 3
        return [
            ("Top", (c_lat + DY, c_lon + DX)),
            ("Center", (c_lat, c_lon)),
            ("Bottom", (c_lat - DY, c_lon - DX))
        ]


def _find_final_tiff(segment_base_dir: str) -> Optional[str]:
    """세그먼트 폴더의 07_Final_results에서 첫 번째 tiff 파일 경로 반환"""
    final_dir = os.path.join(segment_base_dir, "07_Final_results")
    if not os.path.exists(final_dir):
        return None
    for f in os.listdir(final_dir):
        if f.lower().endswith(('.tif', '.tiff')):
            return os.path.join(final_dir, f)
    return None


def run_step_4_with_extrapolation_fallback(
        config: PipelineConfig,
        output_base_dir: str,
        segment_dirs: list) -> tuple:
    """
    3분할 모드 전용 모자이킹:
    - top / bottom 07_Final_results 폴더에 RPB 파일이 모두 있으면 일반 모자이킹
    - 하나라도 없으면 Strip_correction_3D 외삽 로직으로 대체

    Returns:
        (mosaic_path, correction_status)
        correction_status: {'Top': 'normal'|'extrapolated',
                            'Center': 'normal',
                            'Bottom': 'normal'|'extrapolated'}
    """
    yyyymmdd, HHMMSS = parse_date_time_from_config(config)
    band_str = get_band_count_str(config)

    top_dir    = segment_dirs[0]   # Top
    center_dir = segment_dirs[1]   # Center
    bottom_dir = segment_dirs[2]   # Bottom

    def has_rpb(seg_dir: str) -> bool:
        final_dir = os.path.join(seg_dir, "07_Final_results")
        if not os.path.exists(final_dir):
            return False
        return any(f.upper().endswith('.RPB') for f in os.listdir(final_dir))

    top_ok    = has_rpb(top_dir)
    center_ok = has_rpb(center_dir)
    bottom_ok = has_rpb(bottom_dir)

    Logger.info(f"RPB 존재 여부:  Top={top_ok}  Center={center_ok}  Bottom={bottom_ok}")

    # 모두 정상이면 기존 모자이킹
    if top_ok and bottom_ok:
        mosaic_path = run_step_4_mosaic(config, output_base_dir, segment_dirs)
        return mosaic_path, {'Top': 'normal', 'Center': 'normal', 'Bottom': 'normal'}

    # ── 외삽 필요: Strip_correction_3D 함수 import ──────────────────────
    try:
        strip_script_dir = SCRIPT_DIR   # Full_processing_v2.py와 같은 Code/ 폴더
        sys.path.insert(0, strip_script_dir)
        from Strip_correction_3D import (
            calculate_ranges, parse_rpb, load_dem, load_geoid,
            process_top_segment, process_bottom_segment,
        )
        # create_mosaic_all은 Strip_correction_3D에 존재하므로 별도 import
        from Strip_correction_3D import create_mosaic_all as _sc3d_mosaic_all
        # 외삽 결과를 각 세그먼트 07_Final_results에 저장 (standalone --target all과 동일)
        from Strip_correction_3D import _publish_to_final_results as _sc3d_publish
    except ImportError as e:
        Logger.error(f"Strip_correction_3D import 실패: {e}  → 일반 모자이킹으로 대체")
        mosaic_path = run_step_4_mosaic(config, output_base_dir, segment_dirs)
        return mosaic_path, {'Top': 'normal', 'Center': 'normal', 'Bottom': 'normal'}

    # Center 결과 폴더
    center_final_dir = os.path.join(center_dir, "07_Final_results")
    try:
        center_rpb_file  = next(f for f in os.listdir(center_final_dir) if f.upper().endswith('.RPB'))
        center_tiff_file = next(f for f in os.listdir(center_final_dir) if f.lower().endswith(('.tif', '.tiff')))
    except StopIteration:
        Logger.error("Center RPB/TIFF를 찾을 수 없습니다. 일반 모자이킹으로 대체합니다.")
        mosaic_path = run_step_4_mosaic(config, output_base_dir, segment_dirs)
        return mosaic_path, {'Top': 'normal', 'Center': 'normal', 'Bottom': 'normal'}

    center_rpc = parse_rpb(os.path.join(center_final_dir, center_rpb_file))

    # Raw TIFF (분할 전 원본)
    raw_tiff = config.input_path
    with rasterio.open(raw_tiff) as src:
        total_height = src.height
        width        = src.width
    ranges = calculate_ranges(total_height)

    # DEM 경로 (SRTM/Copernicus 중 실제 존재하는 파일 반환)
    def _dem_path(seg_dir: str, label: str) -> str:
        open_dir = os.path.join(seg_dir, "01_Download_open_data")
        for prefix in ("SRTM", "Copernicus"):
            p = os.path.join(open_dir, f"{prefix}_DEM_{label.lower()}.tif")
            if os.path.exists(p):
                return p
        # 둘 다 없으면 현재 DEM_TYPE 기준 경로 반환 (이후 exists 체크에서 실패 처리)
        default_prefix = "SRTM" if DEM_TYPE == "SRTM" else "Copernicus"
        return os.path.join(open_dir, f"{default_prefix}_DEM_{label.lower()}.tif")

    def _geoid_path(seg_dir: str, label: str) -> str:
        return os.path.join(seg_dir, "01_Download_open_data", f"Geoid_{label.lower()}.tif")
    
    correction_status = {
        'Top':    'normal' if top_ok    else 'extrapolated',
        'Center': 'normal',
        'Bottom': 'normal' if bottom_ok else 'extrapolated',
    }

    # ── Top 처리 ─────────────────────────────────────────────────────────
    if not top_ok:
        Logger.warning("Top RPB 없음 → 외삽 기하보정 수행")
        dem_top_path = _dem_path(top_dir, 'top')
        geoid_top_path = _geoid_path(top_dir, 'top')
        if not os.path.exists(dem_top_path) or not os.path.exists(geoid_top_path):
            Logger.error(f"Top DEM 또는 Geoid을 찾을 수 없습니다: {dem_top_path} 또는 {geoid_top_path}")
            top_corrected = None
        else:
            try:
                dem_top = load_dem(dem_top_path)
                geoid_top = load_geoid(geoid_top_path)
                top_corrected, _, _ = process_top_segment(
                    output_base_dir, raw_tiff, ranges,
                    center_rpc, center_final_dir, dem_top, dem_top_path, geoid_top, geoid_top_path,
                    center_tiff_file, width, save_intermediate=False
                )
                Logger.success("Top 외삽 완료")
            except Exception as e:
                Logger.error(f"Top 외삽 실패: {e}")
                top_corrected = None
    else:
        top_corrected = _find_final_tiff(top_dir)

    # ── Bottom 처리 ──────────────────────────────────────────────────────
    if not bottom_ok:
        Logger.warning("Bottom RPB 없음 → 외삽 기하보정 수행")
        dem_bottom_path = _dem_path(bottom_dir, 'bottom')
        geoid_bottom_path = _geoid_path(bottom_dir, 'bottom')
        if not os.path.exists(dem_bottom_path) or not os.path.exists(geoid_bottom_path):
            Logger.error(f"Bottom DEM 또는 Geoid을 찾을 수 없습니다: {dem_bottom_path} 또는 {geoid_bottom_path}")
            bottom_corrected = None
        else:
            try:
                dem_bottom = load_dem(dem_bottom_path)
                geoid_bottom = load_geoid(geoid_bottom_path)
                bottom_corrected, _, _ = process_bottom_segment(
                    output_base_dir, raw_tiff, ranges,
                    center_rpc, center_final_dir, dem_bottom, dem_bottom_path, geoid_bottom, geoid_bottom_path,
                    center_tiff_file, width, save_intermediate=False
                )
                Logger.success("Bottom 외삽 완료")
            except Exception as e:
                Logger.error(f"Bottom 외삽 실패: {e}")
                bottom_corrected = None
    else:
        bottom_corrected = _find_final_tiff(bottom_dir)

    # ── 외삽 결과를 각 세그먼트 07_Final_results에 저장 (standalone --target all과 동일) ──
    data_name = os.path.basename(output_base_dir)  # bb_l1a_..._8band
    if not top_ok and top_corrected:
        try:
            _sc3d_publish("top", output_base_dir, center_tiff_file, data_name,
                          top_corrected,
                          os.path.join(output_base_dir, "analysis_steps", "step05_3d_rpc_top"))
            Logger.success("Top 외삽 결과 → Top/07_Final_results 저장")
        except Exception as e:
            Logger.warning(f"Top 외삽 결과 07_Final_results 저장 실패: {e}")
    if not bottom_ok and bottom_corrected:
        try:
            _sc3d_publish("bottom", output_base_dir, center_tiff_file, data_name,
                          bottom_corrected,
                          os.path.join(output_base_dir, "analysis_steps", "step05_3d_rpc_bottom"))
            Logger.success("Bottom 외삽 결과 → Bottom/07_Final_results 저장")
        except Exception as e:
            Logger.warning(f"Bottom 외삽 결과 07_Final_results 저장 실패: {e}")

    # ── 최종 모자이킹 ────────────────────────────────────────────────────
    output_filename = f"bb_l1c_{yyyymmdd}_{HHMMSS}_{band_str}.tiff"
    output_path = os.path.join(output_base_dir, output_filename)

    # 하나라도 외삽 결과가 있으면 create_mosaic_all 사용
    if top_corrected and bottom_corrected:
        try:
            _sc3d_mosaic_all(output_base_dir, center_final_dir,
                             top_corrected, bottom_corrected, output_path)
            Logger.success(f"외삽 포함 모자이킹 완료 → {output_filename}")
        except Exception as e:
            Logger.error(f"모자이킹 실패: {e}  → 일반 모자이킹 시도")
            output_path = run_step_4_mosaic(config, output_base_dir, segment_dirs)
    else:
        # 부분 실패: 가용한 파일만으로 일반 모자이킹 수행
        Logger.warning("일부 세그먼트 외삽 실패 → 가용 파일로 일반 모자이킹 수행")
        output_path = run_step_4_mosaic(config, output_base_dir, segment_dirs)

    return output_path, correction_status


# =====================================================
# 메인 실행부
# =====================================================
def main(config: PipelineConfig = None):
    Logger.header("🛰️ BlueBON 기하보정 파이프라인 v2")
    
    # GUI를 통한 설정 입력
    if config is None:
        config = get_pipeline_config()
        
    if config is None:
        Logger.info("사용자에 의해 취소되었습니다.")
        return
    
    # 설정 출력
    Logger.info(f"입력 파일: {os.path.basename(config.input_path)}")
    Logger.info(f"중심 좌표: ({config.center_lat}, {config.center_lon})")
    Logger.info(f"밴드 수: {config.band_count}")
    Logger.info(f"분할 개수: {config.num_segments} ({', '.join(get_segment_names(config.num_segments))})")
    Logger.info(f"중간 결과물 저장: {'예' if config.save_intermediate else '아니오'}")
    
    # 출력 디렉토리 생성
    input_dir = os.path.dirname(config.input_path)
    output_folder_name = f'level-1C'
    output_base_dir = os.path.join(input_dir, output_folder_name)
    os.makedirs(output_base_dir, exist_ok=True)
    
    Logger.info(f"출력 폴더: {output_folder_name}")
    
    try:
        import time
        total_step3_time = 0.0
        # Earth Engine 초기화
        init_earth_engine()
        
        # 날짜 추출
        target_date = parse_date_from_config(config)
        
        # 세그먼트별 좌표 계산
        segment_coords_list = calculate_segment_coordinates(config)
        segment_dirs = []

        # 공유 다운로드 (전체 union 영역을 한 번에)
        shared_dir = os.path.join(output_base_dir, "_shared")
        dem_prefix = "SRTM" if DEM_TYPE == "SRTM" else "Copernicus"

        Logger.step(1, "공유 Sentinel-2 다운로드")
        shared_s2_path, s2_date_str = download_shared_sentinel(
            config, shared_dir, segment_coords_list, target_date
        )

        Logger.step(2, "공유 DEM 다운로드")
        shared_dem_path = download_shared_dem(config, shared_dir, segment_coords_list)

        Logger.step("2.1", "공유 Geoid 다운로드")
        shared_geoid_path = download_shared_geoid(config, shared_dir, segment_coords_list)

        # 각 세그먼트 처리
        for segment_idx, (segment_label, segment_coords) in enumerate(segment_coords_list):
            Logger.step(0, f"{segment_label} 영상 분할")

            # 세그먼트 디렉토리 생성
            segment_base_dir = os.path.join(output_base_dir, segment_label)
            os.makedirs(segment_base_dir, exist_ok=True)
            segment_dirs.append(segment_base_dir)

            # Step 0: 영상 분할
            target_path, coord_path, rgb_indices = run_step_0_split_image(
                config, segment_base_dir, segment_label, segment_coords
            )

            # 공유 다운로드 파일을 세그먼트 폴더에 링크 (기존 파일명 규약 유지)
            seg_open_dir = os.path.join(segment_base_dir, "01_Download_open_data")
            reference_path = _link_shared_to_segment(
                shared_s2_path, seg_open_dir, f"S2_mosaic_{s2_date_str}.tif"
            ) if shared_s2_path else None
            dem_path = _link_shared_to_segment(
                shared_dem_path, seg_open_dir, f"{dem_prefix}_DEM_{segment_label.lower()}.tif"
            ) if shared_dem_path else None
            geoid_path = _link_shared_to_segment(
                shared_geoid_path, seg_open_dir, f"Geoid_{segment_label.lower()}.tif"
            ) if shared_geoid_path else None

            # Step 3: 기하보정
            if reference_path and dem_path:
                Logger.step(3, f"{segment_label} 기하보정")
                start_time = time.time()
                success = run_step_3_geometric_correction(
                    config, segment_base_dir, segment_label, segment_coords,
                    target_path, reference_path, dem_path, geoid_path, rgb_indices,
                    gcp_chips_dir=config.gcp_chips_dir,
                    gcp_chip_resolution=config.gcp_chip_resolution,
                )
                end_time = time.time()
                total_step3_time += (end_time - start_time)

                # 기하보정 성공 시 결과물 재정리
                if success:
                    reorganize_geometric_correction_outputs(config, segment_base_dir, segment_label)
        
        # Step 4: 모자이킹 (3분할 모드는 외삽 폴백 포함)
        Logger.step(4, "결과물 모자이킹")
        correction_status = None
        if config.num_segments == 3:
            mosaic_path, correction_status = run_step_4_with_extrapolation_fallback(
                config, output_base_dir, segment_dirs
            )
        else:
            mosaic_path = run_step_4_mosaic(config, output_base_dir, segment_dirs)

        # Step 5: 중심점 좌표 저장
        if mosaic_path:
            Logger.step(5, "중심점 좌표 저장")
            write_center_coordinates(
                mosaic_path,
                processing_time_sec=total_step3_time,
                correction_status=correction_status
            )
            _update_main_sheet_with_coords(config, mosaic_path)
        
        # 완료 메시지
        Logger.header("✅ 처리 완료")
        if mosaic_path:
            Logger.success(f"최종 결과물: {mosaic_path}")
        Logger.info(f"출력 폴더: {output_base_dir}")
        
    except Exception as e:
        Logger.error(f"처리 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()


def _build_pipeline_config_from_cli(args: argparse.Namespace) -> PipelineConfig:
    input_path = os.path.abspath(args.input_path)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"입력 파일이 존재하지 않습니다: {input_path}")

    if args.center_lat is None or args.center_lon is None:
        raise ValueError("--center-lat, --center-lon은 --input-path와 함께 지정해야 합니다.")

    file_info = None
    if input_path:
        file_info = parse_filename(os.path.basename(input_path))





    return PipelineConfig(
        input_path=input_path,
        center_lat=float(args.center_lat),
        center_lon=float(args.center_lon),
        num_segments=int(args.num_segments),
        save_intermediate=bool(args.save_intermediate),
        target_resolution=float(args.res),
    )


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BlueBON 기하보정 파이프라인 v2 (CLI 지원)")

    # GUI 모드 전환: --input-path를 주면 CLI, 없으면 기존 GUI로 동작
    parser.add_argument(
        "--input",
        "-i",
        dest="input_path",
        default=None,
        help="처리할 입력 TIFF 경로 (bb_{level}_{yyyymmdd}_{HHMMSS}_{N}band.tiff 권장)",
    )
    parser.add_argument("--center-lat", type=float, default=None, help="중심 위도")
    parser.add_argument("--center-lon", type=float, default=None, help="중심 경도")
    parser.add_argument("--segment", type=int, choices=[1, 2, 3], default=3, help="영상 분할 개수")
    parser.add_argument("--save-intermediate", action="store_true", help="중간 결과물(썸네일 등) 저장")

    parser.add_argument("--res", type=float, default=4.8, help="기하보정 target resolution (기본: 4.8)")
    return parser.parse_args()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='BlueBON 기하보정 처리')
    parser.add_argument('--input', type=str, default=None,
                        help='처리할 입력 TIFF 경로 (bb_{level}_{yyyymmdd}_{HHMMSS}_{N}band 형식으로 입력)')
    parser.add_argument('--lat', type=float, default=None, help='중심 위도')
    parser.add_argument('--lon', type=float, default=None, help='중심 경도')
    parser.add_argument('--segment', type=int, choices=[1, 2, 3], default=3, help='영상 분할 개수')
    parser.add_argument('--intermediate', action='store_true', help='중간 결과물(썸네일 등) 저장')
    parser.add_argument('--res', type=float, default=4.8, help='기하보정 target resolution (기본: 4.8)')

    args = parser.parse_args()

    # --input이 없으면 GUI 방식으로 실행
    if not args.input:
        main()
    else:
        def parse_metadata(filename: str) -> dict:
            basename = os.path.basename(filename)
            pattern = r'bb_([a-zA-Z0-9]+)_(\d{8})_(\d{6})_(\d+)band(?:_.*)?\.[a-zA-Z0-9]+$'
            match = re.match(pattern, basename, re.IGNORECASE)

            if match:
                return {
                    'level': match.group(1),
                    'date': match.group(2),
                    'time': match.group(3),
                    'band_count': int(match.group(4))
                }
            return None

        metadata = parse_metadata(args.input)
        if metadata is None:
            raise ValueError("입력 TIFF 파일명 형식을 인식할 수 없습니다. bb_{level}_{yyyymmdd}_{HHMMSS}_{N}band.tiff 형식을 따르세요.")

        config = PipelineConfig(
            input_path=args.input,
            level=metadata['level'],
            date=metadata['date'],
            time=metadata['time'],
            band_count=metadata['band_count'],
            center_lat=args.lat,
            center_lon=args.lon,
            num_segments=args.segment,
            save_intermediate=args.intermediate,  # 중간 결과물 저장
            target_resolution=args.res
        )

        main(config)
