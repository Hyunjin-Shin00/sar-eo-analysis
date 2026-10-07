# -*- coding: utf-8 -*-
# file: s1_full_pipeline_optional_shp.py
# Sentinel-1 데이터의 다운로드, 전처리, 수역 분석을 모두 수행하는 통합 파이프라인
# AOI Shapefile 지정 여부에 따라 전체 Scene 또는 특정 영역 분석 가능

# =============================================================================
# --- 파이프라인 처리 순서 ---
# Part 1: Sentinel-1 원본 데이터 다운로드
# Part 0: 지형 데이터 자동 준비 (DEM/Slope)
# Part 2: Sentinel-1 데이터 전처리 (Snappy with GLO-30)
# Part 3: 수역 탐지 및 변화 분석 (Rasterio)

# --- 코드 실행 순서 ---
# conda activate snappy39
# python <DATA_ROOT>\etc\code\S1_down_prepro_flood_date3.py

# =============================================================================

# --- 1. 라이브러리 임포트 ---
import os
import sys
import gc
import re
import csv
import glob
import math
import shutil
import requests
import argparse
import subprocess
import numpy as np
import geopandas as gpd
import asf_search as asf
from shapely.geometry import Point, shape, box
from urllib.parse import urljoin
from tqdm.auto import tqdm
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

asf.constants.INTERNAL.CMR_TIMEOUT = 120

# Rasterio (Geospatial)
try:
    import rasterio
    from rasterio.mask import mask
    from rasterio.merge import merge
    from rasterio.enums import Resampling
    from rasterio.warp import calculate_default_transform, reproject, Resampling as WarpResampling
except ImportError:
    print("오류: rasterio, geopandas 라이브러리가 필요합니다. (pip install rasterio geopandas)")
    sys.exit(1)

# Snappy (ESA SNAP)
try:
    from esa_snappy import ProductIO, GPF, HashMap, jpy
except ImportError:
    print("오류: esa_snappy를 찾을 수 없습니다. snappy가 올바르게 설치 및 구성되었는지 확인해주세요.")
    sys.exit(1)

# --- 2. 사용자 설정 ---

# --- 폴더 경로 ---
BASE_DIR = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\S1_flood_detection"

# 각 단계별 폴더 이름
DOWNLOAD_DIR_NAME = "01_S1_download"
PREPROCESS_DIR_NAME = "02_preprocess"
DEM_DIR_NAME = "00_dem_slope"
ANALYSIS_DIR_NAME = "03_analysis"

# --- 데이터 검색 및 다운로드 설정 (ASF) ---
LAT, LON = 35.180386, 128.119025  # (lat, lon)  # 둘 다 None이면 AOI가 필요
START_DATE = "2025-07-11"        # None 가능
END_DATE = "2025-07-20"          # None 가능

# 기준일(홍수 이전) 날짜
BEFORE_DATE = None               # 예: "20250712" 또는 None

# --- 선택적 날짜 필터 ---------------------------------------------------------
# 모드:
#  - "all"          : 필터 사용 안 함(기본)
#  - "first_last"   : 기간 내 결과 중 시간순 '첫 장'과 '마지막 장'만 사용
#  - "include_only" : INCLUDE_DATES에 지정한 날짜(YYYYMMDD)만 사용
#  - "exclude"      : EXCLUDE_DATES에 지정한 날짜(YYYYMMDD)를 제외
DATE_FILTER_MODE = "all"         # None 가능

# 포함/제외 날짜 목록(둘 다 비워두면 영향 없음)
INCLUDE_DATES = []               # None 가능. 예: ["20250902", "2025-09-10"]
EXCLUDE_DATES = []               # None 가능. 예: ["2025-09-06", "20250908"]

# --- 분석 설정 (rasterio) ---
# ① AOI Shapefile 경로 (없으면 None / "" / "None" 모두 허용)
AOI_SHP_PATH = None

# 궤도 방향 설정 ('ASCENDING', 'DESCENDING' 또는 둘 다 받으려면 None)
FLIGHT_DIRECTION = "ASCENDING"   # None 가능

# ③ Earthdata ID/PW (ASF Datapool용)
EDL_USER = os.environ.get("EARTHDATA_USER", "")
EDL_PASS = os.environ.get("EARTHDATA_PASS", "")

# --- 전처리 설정 (snappy) ---
POLARIZATION = "VV"              # None이면 'VV'로 대체

# ② 수역 탐지 임계값
DB_THRESHOLD   = -15             # None이면 -15
SLOPE_THRESHOLD = 15             # None이면 15 (degree)

# -----------------------------------------------------------------------------

# =============================================================================
# --- 아래부터는 코드 본문. 특별한 경우가 아니면 수정할 필요 없음 ---
# =============================================================================

# -------- 공통 유틸 --------
def _is_blank_or_none(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip().lower() in {"", "none", "null", "na", "n/a"}:
        return True
    return False

def _optional_path(path_like):
    """문자열 'None' / '' / None / 존재하지 않는 경로는 모두 무시하고, 유효하면 Path 반환."""
    if _is_blank_or_none(path_like):
        return None
    p = Path(str(path_like).strip())
    if not p.exists():
        print(f"경고: 지정한 AOI 경로가 존재하지 않아 무시합니다 -> {p}")
        return None
    return p

def _as_yyyymmdd(s: str) -> str:
    """'YYYYMMDD' 또는 'YYYY-MM-DD' 문자열을 'YYYYMMDD'로 표준화."""
    s = str(s).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    # sceneName에서 날짜 추출 시도
    m = re.search(r'_(\d{8})T', s)
    if m:
        return m.group(1)
    raise ValueError(f"날짜 포맷 인식 실패: {s}")

def _result_date_yyyymmdd(product) -> str:
    """asf_search 결과에서 장면의 시작 날짜를 'YYYYMMDD'로 반환."""
    st = product.properties.get("startTime")  # 예: '2025-09-10T21:31:33.000Z'
    if st:
        try:
            dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
            return dt.strftime("%Y%m%d")
        except Exception:
            pass
    scene = product.properties.get("sceneName", "")
    m = re.search(r'_(\d{8})T', scene)
    if m:
        return m.group(1)
    fname = product.properties.get("fileName", "")
    m2 = re.search(r'_(\d{8})T', fname)
    if m2:
        return m2.group(1)
    # 최후 수단: UTC 오늘
    return datetime.now(timezone.utc).strftime("%Y%m%d")

def _filter_results_by_date(results, mode="all", include_dates=None, exclude_dates=None):
    """검색 결과(asf_search 결과 리스트)를 날짜 규칙으로 필터링."""
    mode = (mode or "all").strip().lower()

    include_set = set()
    exclude_set = set()
    if include_dates:
        include_set = { _as_yyyymmdd(x) for x in include_dates }
    if exclude_dates:
        exclude_set = { _as_yyyymmdd(x) for x in exclude_dates }

    # 날짜태그 추가
    enriched = []
    for r in results:
        ymd = _result_date_yyyymmdd(r)
        enriched.append((r, ymd))
    # 기본 정렬(시각 오름차순)
    enriched.sort(key=lambda x: x[1])

    if mode == "include_only" and include_set:
        filtered = [r for r, ymd in enriched if ymd in include_set]
        print(f"[DATE] include_only: {sorted(include_set)} → {len(filtered)}개 유지")
        return filtered

    if mode == "exclude" and exclude_set:
        filtered = [r for r, ymd in enriched if ymd not in exclude_set]
        print(f"[DATE] exclude: {sorted(exclude_set)} → {len(filtered)}개 유지")
        return filtered

    if mode == "first_last":
        if not enriched:
            return []
        if len(enriched) == 1:
            only = [enriched[0][0]]
            print(f"[DATE] first_last: 단 1장만 존재 → 1개 유지")
            return only
        first_r = enriched[0][0]
        last_r  = enriched[-1][0]
        print(f"[DATE] first_last: {enriched[0][1]} & {enriched[-1][1]} → 2개 유지")
        return [first_r, last_r]

    # 기본(all)
    filtered = []
    for r, ymd in enriched:
        if include_set and ymd not in include_set:
            continue
        if exclude_set and ymd in exclude_set:
            continue
        filtered.append(r)
    print(f"[DATE] all: include={sorted(include_set) if include_set else 'None'}, exclude={sorted(exclude_set) if exclude_set else 'None'} → {len(filtered)}개 유지")
    return filtered

# --- 입력 로깅 유틸 ---
def _write_input_log(base_dir: str, inputs: Dict[str, Any]) -> str:
    """아이디/비번 제외한 런타임 입력값들을 BASE_DIR에 txt로 기록."""
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(base_dir) / f"_run_inputs_{ts}.txt"

    def _fmt(v):
        if isinstance(v, (list, tuple, set)):
            return ", ".join(map(str, v))
        return str(v)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("# Sentinel-1 flood pipeline run inputs (credentials omitted)\n")
        f.write(f"# Script : {Path(sys.argv[0]).name}\n")
        f.write(f"# Time   : {datetime.now().isoformat(timespec='seconds')}\n\n")
        for k in sorted(inputs.keys()):
            f.write(f"{k} = { _fmt(inputs[k]) }\n")
    return str(log_path)

class S1Pipeline:
    def __init__(self, base_dir):
        # 클래스 초기화 시 기본 경로와 하위 폴더 경로들을 설정
        self.base_dir = Path(base_dir)
        self.download_dir = self.base_dir / DOWNLOAD_DIR_NAME
        self.preprocess_dir = self.base_dir / PREPROCESS_DIR_NAME
        self.dem_dir = self.base_dir / DEM_DIR_NAME
        self.analysis_dir = self.base_dir / ANALYSIS_DIR_NAME
        self.clipped_dir = self.analysis_dir / "clipped"
        self.watermask_dir = self.analysis_dir / "water_mask"
        self.aligned_dir = self.analysis_dir / "aligned"
        self.diff_dir = self.analysis_dir / "difference"
        self._create_dirs()

    def _create_dirs(self):
        """워크플로우에 필요한 모든 출력 폴더를 생성합니다."""
        for d in [self.download_dir, self.preprocess_dir, self.dem_dir, self.analysis_dir,
                  self.clipped_dir, self.watermask_dir, self.aligned_dir, self.diff_dir]:
            d.mkdir(parents=True, exist_ok=True)
            
    def search_and_download(self, aoi_shp_path, lat, lon, start_date, end_date,
                            user, password, flight_direction=None,
                            date_filter_mode="all", include_dates=None, exclude_dates=None):
        """--- Part 1: S1 데이터 검색 및 다운로드 (+날짜 필터) ---"""
        print("\n--- 파트 1: 데이터 검색 및 다운로드 시작 ---")

        # 기본값 강제
        pol_fallback = (POLARIZATION or "VV").upper()
        db_th = DB_THRESHOLD if DB_THRESHOLD is not None else -15
        sl_th = SLOPE_THRESHOLD if SLOPE_THRESHOLD is not None else 15
        # (위 두 변수는 여기선 쓰지 않지만, None이어도 전체 파이프라인이 안전하게 돈다는 의도 확인용)

        # 검색 옵션 구성 (None이면 키 자체 생략)
        search_opts = {'platform': "Sentinel-1", 'beamMode': "IW", 'processingLevel': "GRD"}
        if not _is_blank_or_none(start_date):
            search_opts['start'] = start_date
        if not _is_blank_or_none(end_date):
            search_opts['end'] = end_date
        if not _is_blank_or_none(flight_direction):
            search_opts['flightDirection'] = flight_direction
            print(f"궤도 방향 필터링: {flight_direction}")

        # AOI / 포인트 결정
        aoi_path = _optional_path(aoi_shp_path)
        if aoi_path:
            print(f"AOI Shapefile('{aoi_path.name}') 기준으로 검색합니다.")
            aoi_gdf = gpd.read_file(str(aoi_path)).to_crs(epsg=4326)
            search_opts['intersectsWith'] = aoi_gdf.geometry.union_all().wkt
        else:
            if lat is None or lon is None:
                sys.exit("오류: AOI도 없고 LAT/LON도 없습니다. AOI_SHP_PATH 또는 LAT/LON 중 하나는 지정해야 합니다.")
            print(f"AOI 없음 → 포인트({lat}, {lon}) 기준으로 검색합니다.")
            search_opts['intersectsWith'] = f"POINT({lon} {lat})"

        # asf_search API를 통해 데이터 검색
        raw_results = asf.geo_search(**search_opts)

        # 중복된 Scene 제거
        unique = {r.properties.get("sceneName"): r for r in raw_results if r.properties.get("sceneName")}
        grd_items_all = [r for r in unique.values() if '_GRD' in r.properties.get("sceneName", "")]

        print(f"검색 결과(중복 제거 후): {len(grd_items_all)} 개")

        # --- 날짜 필터 적용 (다운로드 전) ---
        grd_items = _filter_results_by_date(
            grd_items_all,
            mode=(date_filter_mode or "all"),
            include_dates=include_dates or [],
            exclude_dates=exclude_dates or []
        )

        if not grd_items:
            print("조건에 맞는 GRD 데이터를 찾지 못했습니다. (날짜 필터 결과 0개)")
            return [], []
        print(f"다운로드 대상 최종: {len(grd_items)} 개")

        # Earthdata 계정으로 세션 인증 및 파일 다운로드
        session = asf.ASFSession().auth_with_creds(user, password)
        downloaded_files = []
        for product in tqdm(grd_items, desc="Downloading S1 files"):
            fname = product.properties["fileName"]
            dst = self.download_dir / fname
            if not dst.exists():
                try:
                    with session.get(product.properties['url'], stream=True) as r:
                        r.raise_for_status()
                        with open(dst, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                    downloaded_files.append(str(dst))
                except Exception as e: 
                    print(f"다운로드 실패: {fname} - {e}")
            else:
                downloaded_files.append(str(dst))
        print("--- 파트 1: 데이터 다운로드 완료 ---\n")
        return downloaded_files, grd_items

    def prepare_dem_and_slope(self, s1_results, aoi_shp_path=None):
        """
        --- Part 0: DEM 및 Slope 준비 ---
        순서: 4326 DEM -> 32652 DEM -> 32652 Slope -> 4326 Slope(재투영)
        반환: (dem_wgs84_path, dem_utm_path, slope_utm_path, slope_wgs84_path)
        """
        print("\n--- 파트 0: DEM 및 Slope 준비 시작 ---")
        
        if not s1_results:
            sys.exit("S1 데이터가 없어 DEM 범위를 계산할 수 없습니다.")
        geometries = [shape(r.geometry) for r in s1_results]
        s1_gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")
        bounds = s1_gdf.total_bounds
        
        # 1) 전처리/다운로드용 전체 4326 DEM
        full_scene_dem_wgs84 = self.dem_dir / "Full_Scene_DEM_GLO30_WGS84.tif"
        if not full_scene_dem_wgs84.exists():
            print("S1 Scene 전체 영역에 대한 DEM(4326)을 생성합니다.")
            lon_min, lat_min, lon_max, lat_max = bounds
            req_lons = range(math.floor(lon_min), math.ceil(lon_max))
            req_lats = range(math.floor(lat_min), math.ceil(lat_max))
            tile_urls = [
                f"https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM/Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM.tif"
                for lat in req_lats for lon in req_lons
            ]
            downloaded_tiles = []
            for url in tqdm(tile_urls, desc="Downloading DEM tiles"):
                fname = self.dem_dir / Path(url).name
                if not fname.exists():
                    try:
                        r = requests.get(url, stream=True); r.raise_for_status()
                        with open(fname, 'wb') as f: f.write(r.content)
                        downloaded_tiles.append(str(fname))
                    except requests.exceptions.RequestException:
                        pass
                else:
                    downloaded_tiles.append(str(fname))
            if not downloaded_tiles:
                sys.exit("DEM 파일을 다운로드할 수 없습니다.")
            src_files_to_mosaic = [rasterio.open(f) for f in downloaded_tiles]
            mosaic_data, out_trans = merge(src_files_to_mosaic)
            out_meta = src_files_to_mosaic[0].meta.copy()
            out_meta.update({"driver": "GTiff", "height": mosaic_data.shape[1], "width": mosaic_data.shape[2],
                             "transform": out_trans, "nodata": -9999})
            with rasterio.open(full_scene_dem_wgs84, "w", **out_meta) as dest:
                dest.write(mosaic_data)
            for src in src_files_to_mosaic: src.close()

        # 필요 시 AOI로 잘라 분석용 4326 DEM 준비
        dem_for_slope_wgs84 = full_scene_dem_wgs84
        suffix = "Full_Scene"
        aoi_path = _optional_path(aoi_shp_path)
        if aoi_path:
            suffix = "AOI"
            dem_for_slope_wgs84 = self.dem_dir / f"{suffix}_DEM_GLO30_WGS84.tif"
            if not dem_for_slope_wgs84.exists():
                with rasterio.open(full_scene_dem_wgs84) as src:
                    aoi_gdf = gpd.read_file(str(aoi_path)).to_crs(src.crs)
                    out_image, out_transform = mask(dataset=src, shapes=aoi_gdf.geometry, crop=True, nodata=-9999)
                    out_meta = src.meta.copy()
                    out_meta.update({"height": out_image.shape[1], "width": out_image.shape[2],
                                     "transform": out_transform})
                    with rasterio.open(dem_for_slope_wgs84, "w", **out_meta) as dest:
                        dest.write(out_image)

        # 2) 32652 DEM (재투영)
        dem_utm_path = self.dem_dir / f"{suffix}_DEM_GLO30_EPSG32652.tif"
        if not dem_utm_path.exists():
            print("DEM을 EPSG:32652로 재투영합니다.")
            dst_crs = 'EPSG:32652'
            with rasterio.open(dem_for_slope_wgs84) as src:
                transform, width, height = calculate_default_transform(
                    src.crs, dst_crs, src.width, src.height, *src.bounds)
                kwargs = src.meta.copy()
                kwargs.update({'crs': dst_crs, 'transform': transform,
                               'width': width, 'height': height})
                with rasterio.open(dem_utm_path, 'w', **kwargs) as dst:
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=rasterio.band(dst, 1),
                        src_transform=src.transform, src_crs=src.crs,
                        dst_transform=transform, dst_crs=dst_crs,
                        resampling=Resampling.bilinear
                    )

        # 3) 32652 SLOPE
        slope_utm_path = self.dem_dir / f"{suffix}_SLOPE_GLO30_EPSG32652.tif"
        if not slope_utm_path.exists():
            print("32652 DEM에서 Slope(도) 계산 중...")
            try:
                # gdaldem slope (도 단위)
                os.system(f'gdaldem slope "{dem_utm_path}" "{slope_utm_path}" -compute_edges')
                if not slope_utm_path.exists():
                    raise RuntimeError("gdaldem slope 결과가 생성되지 않음")
            except Exception:
                # 수동 계산 (단위: degree)
                with rasterio.open(dem_utm_path) as src:
                    dem_data = src.read(1).astype(np.float32)
                    dem_data[dem_data == src.nodata] = np.nan
                    dy, dx = np.gradient(dem_data, src.res[1], src.res[0])  # meter 기반
                    slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
                    slope_deg = np.nan_to_num(slope_deg, nan=0.0, posinf=0.0, neginf=0.0)
                    meta = src.meta.copy()
                    meta.update({'dtype': 'float32', 'nodata': -9999})
                    with rasterio.open(slope_utm_path, 'w', **meta) as dst:
                        dst.write(slope_deg.astype(np.float32), 1)

        # 4) 4326 SLOPE (32652 SLOPE -> 4326으로 재투영)
        slope_wgs84_path = self.dem_dir / f"{suffix}_SLOPE_GLO30_WGS84.tif"
        if not slope_wgs84_path.exists():
            print("Slope를 EPSG:4326으로 재투영합니다.")
            with rasterio.open(slope_utm_path) as src:
                dst_crs = "EPSG:4326"
                transform, width, height = calculate_default_transform(
                    src.crs, dst_crs, src.width, src.height, *src.bounds)
                kwargs = src.meta.copy()
                kwargs.update({'crs': dst_crs, 'transform': transform,
                               'width': width, 'height': height})
                with rasterio.open(slope_wgs84_path, 'w', **kwargs) as dst:
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=rasterio.band(dst, 1),
                        src_transform=src.transform, src_crs=src.crs,
                        dst_transform=transform, dst_crs=dst_crs,
                        resampling=Resampling.bilinear
                    )

        print("DEM/Slope 산출물:")
        print(f" - 4326 DEM : {dem_for_slope_wgs84}")
        print(f" - 32652 DEM: {dem_utm_path}")
        print(f" - 32652 SLP: {slope_utm_path}")
        print(f" - 4326 SLP : {slope_wgs84_path}")

        # 4개 경로 반환
        return str(dem_for_slope_wgs84), str(dem_utm_path), str(slope_utm_path), str(slope_wgs84_path)

    def preprocess_s1_files(self, file_list, polarization, dem_path):
        """--- Part 2: 데이터 전처리 ---"""
        print("\n--- 파트 2: 데이터 전처리 시작 ---")
        # 기본값 보정
        polarization = (polarization or "VV").upper()
        if polarization not in {"VV", "VH"}:
            print(f"경고: 지원하지 않는 POLARIZATION '{polarization}' → 'VV'로 대체")
            polarization = "VV"

        processed_files = []
        for f in file_list:
            try:
                target_path = self._s1_grd_preprocessing_single(f, str(self.preprocess_dir), polarization, dem_path)
                if target_path: processed_files.append(target_path)
            except Exception:
                import traceback; traceback.print_exc()
        print("--- 파트 2: 데이터 전처리 완료 ---\n")
        return processed_files

    def _s1_grd_preprocessing_single(self, product_path, output_dir, polarization, dem_path):
        basename = Path(product_path).stem
        target_path = Path(output_dir) / f"{basename}_{polarization}_processed.tif"
        if target_path.exists(): return str(target_path)

        print(f"전처리 중: {Path(product_path).name}")
        product = ProductIO.readProduct(product_path)

        # 1. Apply-Orbit-File
        params = HashMap()
        params.put('Orbit State Vectors', 'Sentinel Precise (Auto Download)')
        params.put('Continue on Failure', 'true')
        product = GPF.createProduct('Apply-Orbit-File', params, product)

        # 2. ThermalNoiseRemoval
        params.clear()
        params.put('removeThermalNoise', True)
        product = GPF.createProduct('ThermalNoiseRemoval', params, product)
        
        # 3. Remove-GRD-Border-Noise
        params.clear()
        params.put('borderMargin', 500)
        product = GPF.createProduct('Remove-GRD-Border-Noise', params, product)

        # 4. Calibration
        params.clear()
        params.put('outputSigmaBand', True)
        params.put('selectedPolarisations', polarization)
        product = GPF.createProduct('Calibration', params, product)
        
        # 5. Speckle-Filter
        params.clear()
        params.put('filter', 'Lee Sigma')
        params.put('filterSizeX', '7')
        params.put('filterSizeY', '7')
        product = GPF.createProduct('Speckle-Filter', params, product)

        # 6. Terrain-Correction
        params.clear()
        params.put('externalDEMFile', dem_path)
        params.put('externalDEMNoDataValue', -9999.0)
        params.put('pixelSpacingInMeter', 10.0)
        params.put('outputCoordinateSystem', 'EPSG:4326') # 모든 결과물을 WGS84로 통일
        product = GPF.createProduct('Terrain-Correction', params, product)

        # 7. LinearToFromdB
        params.clear()
        band_name = next((b.getName() for b in product.getBands() if b.getName().startswith(f'Sigma0_{polarization}')), None)
        if not band_name: raise ValueError("TC 후 Sigma0 밴드를 찾을 수 없습니다.")
        params.put('sourceBands', band_name)
        product = GPF.createProduct('LinearToFromdB', params, product)

        # 결과 저장
        ProductIO.writeProduct(product, str(target_path), 'GeoTIFF-BigTIFF')
        product.closeIO(); gc.collect()
        print(f"전처리 완료: {target_path.name}")
        return str(target_path)

    # --- Part 3: Analysis ---

    def analyze_water_bodies(self, tif_list, s1_results, aoi_shp, slope_tif, db_thresh, slope_thresh, before_date=None):
        """--- Part 3: 수역 분석 및 변화 탐지 ---
        slope_tif는 EPSG:4326 경사 파일을 직접 사용 (정렬 과정에서 그리드 맞춤은 수행)
        """
        print("\n--- 파트 3: 수역 분석 시작 ---")
        
        # 기본값 보정
        db_thresh = db_thresh if db_thresh is not None else -15
        slope_thresh = slope_thresh if slope_thresh is not None else 15

        analysis_files = tif_list
        # --- 3a: (Optional) Clip to AOI ---
        aoi_path = _optional_path(aoi_shp)
        if aoi_path: 
            print("\n[3a] AOI로 클리핑 중...")
            analysis_files = self._clip_tiffs(tif_list, str(aoi_path), str(self.clipped_dir))
        
        # --- 3b: Align Rasters to Common Overlap ---
        print("\n[3b] 모든 영상을 공통 중첩 영역으로 정렬 중...")
        aligned_files = self._align_rasters(
            analysis_files, s1_results, str(self.aligned_dir),
            aoi_path=str(aoi_path) if aoi_path else None, original_tifs=tif_list
        )
        
        # --- 3c: Detect Waterbodies ---
        print("\n[3c] 정렬된 영상에서 수역 탐지 중...")
        watermask_files = self._detect_waterbodies(
            aligned_files, slope_tif, str(self.watermask_dir), db_thresh, slope_thresh
        )
        
        # --- 3d: Calculate Difference ---
        print("\n[3d] 변화 탐지 중...")
        self._calculate_difference(watermask_files, str(self.diff_dir), before_date)
        
        print("--- 파트 3: 수역 분석 완료 ---\n")

    def _clip_tiffs(self, tif_list, aoi_path, output_dir):
        aoi = gpd.read_file(aoi_path)
        clipped_files = []
        for tif_path in tif_list:
            out_path = Path(output_dir) / (Path(tif_path).stem + "_clipped.tif")
            if not out_path.exists():
                with rasterio.open(tif_path) as src:
                    aoi_proj = aoi.to_crs(src.crs)
                    out_image, out_transform = mask(dataset=src, shapes=aoi_proj.geometry, crop=True)
                    out_meta = src.meta.copy()
                    out_meta.update({"driver": "GTiff", "height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
                    with rasterio.open(out_path, "w", **out_meta) as dest: dest.write(out_image)
            clipped_files.append(str(out_path))
        return clipped_files

    def _detect_waterbodies(self, db_files, slope_path, output_dir, db_thresh, slope_thresh):
        """
        slope_path: EPSG:4326 경사 파일. 그리드가 다를 수 있어도 대상 래스터 그리드로 재샘플하여 사용.
        slope_path가 None이면 경사 조건 없이 dB 임계값만으로 마스킹.
        """
        watermask_files = []
        for db_path in db_files:
            out_filename = Path(db_path).stem.replace('_clipped', '').replace('_aligned', '') + "_watermask.tif"
            output_path = Path(output_dir) / out_filename
            if not output_path.exists():
                with rasterio.open(db_path) as db_src:
                    db_data, db_meta = db_src.read(1), db_src.meta
                    if slope_path and Path(slope_path).exists():
                        with rasterio.open(slope_path) as slope_src:
                            slope_resampled = np.empty_like(db_data, dtype=np.float32)
                            reproject(
                                source=rasterio.band(slope_src, 1),
                                destination=slope_resampled,
                                src_transform=slope_src.transform, src_crs=slope_src.crs,
                                dst_transform=db_meta['transform'], dst_crs=db_meta['crs'],
                                resampling=WarpResampling.bilinear
                            )
                        mask_data = ((slope_resampled < slope_thresh) & (db_data < db_thresh)).astype("uint8")
                    else:
                        mask_data = (db_data < db_thresh).astype("uint8")
                db_meta.update({"dtype": "uint8", "nodata": 0, "count": 1})
                with rasterio.open(output_path, 'w', **db_meta) as dst: dst.write(mask_data, 1)
            watermask_files.append(str(output_path))
        return watermask_files

    def _align_rasters(self, raster_list, s1_results, output_dir, aoi_path=None, original_tifs=None):
        """모든 래스터를 실제 촬영 영역(Footprint)의 공통 중첩 영역으로 잘라내고 정렬합니다."""
        if len(raster_list) < 2:
            print("경고: 영상이 하나만 있어 정렬(align)을 건너뜁니다.")
            return raster_list

        # --- 입력 소스 변경 여부 확인 로직 ---
        print("\n[3b-1] 입력 소스 변경 여부 확인...")
        
        scene_name_pattern = re.compile(r'(S1[ABC]_IW_GRDH_1S[DVH]{2}_\d{8}T\d{6}_\d{8}T\d{6}_\w{6}_\w{6}_\w{4})')
        current_scenes = sorted([match.group(1) for rp in raster_list if (match := scene_name_pattern.search(Path(rp).name))])
        
        source_tracker_file = self.aligned_dir / "_source_scenes.txt"

        previous_scenes = []
        if source_tracker_file.exists():
            with open(source_tracker_file, 'r') as f:
                previous_scenes = sorted([line.strip() for line in f])

        inputs_changed = (current_scenes != previous_scenes)

        if inputs_changed:
            print("=======================================================================")
            print("경고: 입력 영상 목록이 변경되었습니다! 기존 분석 결과를 삭제하고 다시 생성합니다.")
            print(f"이전 소스 개수: {len(previous_scenes)}, 현재 소스 개수: {len(current_scenes)}")
            print("=======================================================================")
            
            # clipped_dir는 절대 삭제하지 않음
            for dir_to_clean in [self.aligned_dir, self.watermask_dir, self.diff_dir]:
                if dir_to_clean.exists():
                    for item in dir_to_clean.iterdir():
                        if item.is_file(): item.unlink()
                        elif item.is_dir(): shutil.rmtree(item)
                dir_to_clean.mkdir(parents=True, exist_ok=True)
            
            with open(source_tracker_file, 'w') as f:
                f.write("\n".join(current_scenes))

            # 누락 시 재클리핑
            need_reclip = any(not Path(p).exists() for p in raster_list)
            if need_reclip and aoi_path and original_tifs:
                print(" - 클리핑 산출물이 일부/전부 누락되어 AOI 재클리핑을 수행합니다...")
                raster_list = self._clip_tiffs(original_tifs, aoi_path, str(self.clipped_dir))

        # 정렬 전 존재성 최종 점검
        missing = [p for p in raster_list if not Path(p).exists()]
        if missing:
            if aoi_path and original_tifs:
                print(" - 누락된 클리핑 산출물을 재생성합니다...")
                raster_list = self._clip_tiffs(original_tifs, aoi_path, str(self.clipped_dir))
                missing = [p for p in raster_list if not Path(p).exists()]
            if missing:
                raise FileNotFoundError(
                    "정렬 단계에 필요한 클리핑 산출물이 존재하지 않습니다.\n"
                    f"누락 파일 예시: {missing[0]}\n"
                    "→ analyze_water_bodies()의 클리핑 단계 결과가 정상 생성되었는지 확인해주세요."
                )
        
        gdalwarp_path = shutil.which("gdalwarp")
        if not gdalwarp_path:
            print("오류: gdalwarp 명령어를 찾을 수 없습니다. GDAL이 설치되어 있고 시스템 PATH에 등록되었는지 확인해주세요.")
            return []

        print("\n[3b-2] 실제 촬영 영역(Footprint)의 공통 중첩 영역 계산...")
        
        scene_name_to_geom = {r.properties['sceneName']: shape(r.geometry) for r in s1_results}
        
        geometries = []
        for rp in raster_list:
            match = scene_name_pattern.search(Path(rp).name)
            if match:
                scene_name = match.group(1)
                if scene_name in scene_name_to_geom:
                    geometries.append(scene_name_to_geom[scene_name])
        
        if not geometries:
            print("경고: 입력된 래스터에 해당하는 Footprint 정보를 찾을 수 없습니다.")
            return []

        buffer_distance_degrees = -0.0045
        buffered_geometries = [g.buffer(buffer_distance_degrees) for g in geometries]

        intersection_geom = buffered_geometries[0]
        for i in range(1, len(buffered_geometries)):
            intersection_geom = intersection_geom.intersection(buffered_geometries[i])

        if intersection_geom.is_empty:
            print("경고: 분석할 공통 중첩 영역이 없습니다. 영상들이 겹치지 않을 수 있습니다.")
            return []

        temp_cutline_path = self.aligned_dir / "intersection.geojson"
        gpd.GeoDataFrame({'id': [0]}, geometry=[intersection_geom], crs="EPSG:4326").to_file(str(temp_cutline_path), driver='GeoJSON')

        dst_bounds = intersection_geom.bounds
        print(f"  - 계산된 공통 영역 경계: ({dst_bounds[0]:.4f}, {dst_bounds[1]:.4f}, {dst_bounds[2]:.4f}, {dst_bounds[3]:.4f})")

        # 기준 해상도 획득 (첫 번째 파일)
        with rasterio.open(raster_list[0]) as src:
            target_res_x, target_res_y = src.res

        aligned_files = []
        for raster_path in raster_list:
            out_path = Path(output_dir) / (Path(raster_path).stem + "_aligned.tif")
            if not out_path.exists():
                command = [
                    gdalwarp_path, "-overwrite", "-cutline", str(temp_cutline_path),
                    "-crop_to_cutline", "-tr", str(target_res_x), str(abs(target_res_y)),
                    "-r", "near", "-dstnodata", "0", raster_path, str(out_path)
                ]
                try:
                    subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
                except subprocess.CalledProcessError as e:
                    print(f"  - 오류: {out_path.name} 생성 실패\n  - GDAL 오류: {e.stderr}")
                    continue
            
            if out_path.exists():
                aligned_files.append(str(out_path))
        
        if temp_cutline_path.exists():
            temp_cutline_path.unlink()

        return aligned_files

    def _calculate_difference(self, binary_files, output_dir, before_date_str):
        if len(binary_files) < 2:
            return

        # 파일명에서 기준 날짜 추출 함수
        def _ymd_from_name(p):
            m = re.search(r'(\d{8})T', Path(p).name)
            if m: 
                return datetime.strptime(m.group(1), "%Y%m%d")
            # 혹시 T가 없는 경우 보조 패턴
            m2 = re.search(r'(\d{8})', Path(p).name)
            return datetime.strptime(m2.group(1), "%Y%m%d") if m2 else datetime.max

        sorted_files = sorted(binary_files, key=_ymd_from_name)

        # BEFORE_DATE가 None/빈문자열이면 자동으로 "첫 장"을 기준으로
        before_file = None
        if isinstance(before_date_str, str) and before_date_str.strip():
            # 파일명에 포함되는지 검색
            for f in sorted_files:
                if before_date_str in Path(f).name:
                    before_file = f
                    break
        if before_file is None:
            before_file = sorted_files[0]

        with rasterio.open(before_file) as before_src:
            before_data = before_src.read(1).astype(np.int8)
            meta = before_src.meta

        for after_file in [f for f in sorted_files if f != before_file]:
            b_dt_m = re.search(r'(\d{8})', Path(before_file).name)
            a_dt_m = re.search(r'(\d{8})', Path(after_file).name)
            before_dt = b_dt_m.group(1) if b_dt_m else "base"
            after_dt = a_dt_m.group(1) if a_dt_m else "after"

            output_filename = Path(output_dir) / f"{before_dt}_{after_dt}_diff_binary.tif"
            if not output_filename.exists():
                with rasterio.open(after_file) as after_src:
                    after_data = after_src.read(1).astype(np.int8)
                flood_mask = ((after_data - before_data) == 1).astype("uint8")
                meta.update({"dtype": "uint8", "count": 1, "nodata": 0})
                with rasterio.open(output_filename, 'w', **meta) as dst:
                    dst.write(flood_mask, 1)

if __name__ == "__main__":
    # --- 메인 실행 블록 ---

    # 입력 파라미터 로그 저장 (EDL_USER/EDL_PASS 제외)
    _write_input_log(BASE_DIR, {
        "BASE_DIR": BASE_DIR,
        "DOWNLOAD_DIR_NAME": DOWNLOAD_DIR_NAME,
        "PREPROCESS_DIR_NAME": PREPROCESS_DIR_NAME,
        "DEM_DIR_NAME": DEM_DIR_NAME,
        "ANALYSIS_DIR_NAME": ANALYSIS_DIR_NAME,
        "LAT": LAT,
        "LON": LON,
        "START_DATE": START_DATE,
        "END_DATE": END_DATE,
        "BEFORE_DATE": BEFORE_DATE,
        "DATE_FILTER_MODE": DATE_FILTER_MODE,
        "INCLUDE_DATES": INCLUDE_DATES,
        "EXCLUDE_DATES": EXCLUDE_DATES,
        "AOI_SHP_PATH": AOI_SHP_PATH,
        "FLIGHT_DIRECTION": FLIGHT_DIRECTION,
        "POLARIZATION": POLARIZATION,
        "DB_THRESHOLD": DB_THRESHOLD,
        "SLOPE_THRESHOLD": SLOPE_THRESHOLD,
        # 주의: EDL_USER / EDL_PASS는 기록하지 않음
    })

    pipeline = S1Pipeline(BASE_DIR)
    
    # 1. 데이터 다운로드 (+날짜 필터)
    downloaded_zip_files, s1_results = pipeline.search_and_download(
        aoi_shp_path=AOI_SHP_PATH, lat=LAT, lon=LON, 
        start_date=START_DATE, end_date=END_DATE, 
        user=EDL_USER, password=EDL_PASS,
        flight_direction=FLIGHT_DIRECTION,
        date_filter_mode=DATE_FILTER_MODE,
        include_dates=INCLUDE_DATES,
        exclude_dates=EXCLUDE_DATES
    )
    if not downloaded_zip_files:
        sys.exit("다운로드된 파일이 없어 파이프라인을 종료합니다.")
    
    # 0. DEM 및 Slope 준비 (4개 경로 반환)
    dem_wgs84, dem_32652, slope_32652, slope_wgs84 = pipeline.prepare_dem_and_slope(s1_results, AOI_SHP_PATH)
    
    # 2. 데이터 전처리 (전처리용 DEM은 4326 DEM 사용)
    preprocessed_tif_files = pipeline.preprocess_s1_files(
        file_list=downloaded_zip_files, 
        polarization=(POLARIZATION or "VV"),
        dem_path=dem_wgs84
    )
    if not preprocessed_tif_files:
        sys.exit("전처리된 파일이 없어 파이프라인을 종료합니다.")
    
    # 3. 수역 분석 (수체 마스킹은 4326 SLOPE를 직접 사용)
    pipeline.analyze_water_bodies(
        tif_list=preprocessed_tif_files, 
        s1_results=s1_results,
        aoi_shp=AOI_SHP_PATH, 
        slope_tif=(slope_wgs84 if not _is_blank_or_none(slope_wgs84) else None),
        db_thresh=(DB_THRESHOLD if DB_THRESHOLD is not None else -15), 
        slope_thresh=(SLOPE_THRESHOLD if SLOPE_THRESHOLD is not None else 15), 
        before_date=BEFORE_DATE
    )
    print("\n모든 파이프라인 작업이 완료되었습니다.")
