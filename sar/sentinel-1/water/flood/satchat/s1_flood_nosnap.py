# =============================================================================
# Sentinel-1 전처리된 GeoTIFF 기반 자동 수체 탐지 & 홍수 탐지
# (snappy 전혀 사용 안 함, 인풋은 dB/TC 완료된 GeoTIFF)
# + Copernicus DEM 자동 다운로드 & Slope 자동 계산 기능 포함
#
# 파일명 예시: s1_processor7_nopreprocessing.py
# =============================================================================
#
# 사용 예시 (Windows, 줄바꿈은 ^)
#
# [1] 전처리된 dB GeoTIFF 1장 → DEM/Slope 자동 생성 + 수체 마스크
# python s1_processor7_nopreprocessing.py water ^
#   --input_tifs "D:\...\S1A_20250712_VV_sigma0_dB_tc.tif" ^
#   --output_dir "D:\...\water_test1" ^
#   --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection no --flood_stats no
#
# [2] 전처리된 dB GeoTIFF 2장 → DEM/Slope 자동 + 수체 마스크 + 홍수 탐지
# python s1_processor7_nopreprocessing.py water ^
#   --input_tifs ^
#     "D:\...\S1A_20250712_VV_sigma0_dB_tc.tif" ^
#     "D:\...\S1A_20250719_VV_sigma0_dB_tc.tif" ^
#   --output_dir "D:\...\water_test2" ^
#   --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection yes --flood_stats yes
#
# [3] DEM/경사도 직접 지정해서 사용
# python s1_processor7_nopreprocessing.py water ^
#   --input_tifs "D:\...\S1A_20250712_VV_sigma0_dB_tc.tif" ^
#   --output_dir "D:\...\water_test3" ^
#   --dem_path   "D:\...\00_dem_slope\auto_downloaded_dem_WGS84.tif" ^
#   --slope_path "D:\...\00_dem_slope\Full_Scene_auto_slope_WGS84.tif" ^
#   --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection no --flood_stats no
#
# [4] 이미 만들어둔 watermask 두 장 → 홍수 변화만 계산
# python s1_processor7_nopreprocessing.py detect-flood ^
#   --before_mask "D:\...\S1A_20250712_VV_watermask.tif" ^
#   --after_mask  "D:\...\S1A_20250719_VV_watermask.tif" ^
#   --output_dir "D:\...\flood_only" ^
#   --flood_stats yes
# =============================================================================

import os
os.environ.setdefault('PROJ_LIB', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'Library', 'share', 'proj'))
os.environ.setdefault('GDAL_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'Library', 'share', 'gdal'))
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

try:
    from pyproj import datadir
    datadir.set_data_dir(os.environ['PROJ_LIB'])
except Exception:
    pass

import sys
import re
import math
import shutil
import requests
import argparse
import numpy as np
from pathlib import Path
import subprocess
import datetime as dt

try:
    from shapely.geometry import Polygon, MultiPolygon, shape, box
    from shapely.ops import unary_union
    import geopandas as gpd
    import rasterio
    from rasterio.features import shapes
    from rasterio.mask import mask
    from rasterio.warp import (
        reproject,
        Resampling as WarpResampling,
        calculate_default_transform,
        transform_bounds,
    )
    from tqdm.auto import tqdm
    from affine import Affine
    from scipy.ndimage import binary_dilation, binary_erosion
except ImportError as e:
    sys.exit(f"오류: 필수 라이브러리가 필요합니다. 상세: {e}")

try:
    from skimage.filters import threshold_otsu
except ImportError as e:
    sys.exit(f"오류: scikit-image 관련 라이브러리가 필요합니다. 상세: {e}")


class S1LocalProcessor:
    def __init__(self, output_dir):
        self.base_dir = Path(output_dir)
        self.dem_dir = self.base_dir / "00_dem_slope"
        self.watermask_dir = self.base_dir / "02_water_masks"
        self.floodmask_dir = self.base_dir / "03_flood_mask"

    # ---------- 유틸 ----------
    def _ensure_parent(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)

    def _get_short_name_from_path(self, p: Path):
        """
        파일명에 S1A_YYYYMMDD 패턴이 있으면 그것을 축약 이름으로 사용.
        없으면 전체 stem.
        """
        fname = p.stem
        m = re.search(r'(S1[ABC])_.*?(\d{8})', fname)
        if m:
            sat, yyyymmdd = m.groups()
            return f"{sat}_{yyyymmdd}"
        return fname

    def _get_date_from_name(self, p: Path) -> dt.date:
        """파일명에서 YYYYMMDD를 찾아 datetime.date로 반환."""
        m = re.search(r'(\d{8})', p.stem)
        if not m:
            raise ValueError(f"날짜 패턴(YYYYMMDD)을 파일명에서 찾지 못했습니다: {p.name}")
        dstr = m.group(1)
        return dt.datetime.strptime(dstr, "%Y%m%d").date()

    def _select_chronological_indices_from_paths(self, path_list):
        """여러 파일 중 가장 이른 날짜 / 가장 늦은 날짜 인덱스를 반환."""
        dates = [self._get_date_from_name(Path(z)) for z in path_list]
        order = sorted(range(len(dates)), key=lambda i: dates[i])
        return order[0], order[-1], dates[order[0]], dates[order[-1]]

    # ---------- DEM 자동 준비 ----------
    def _prepare_dem_from_footprints(self, footprints: list, aoi_shp: str):
        """
        Copernicus DEM 30m 타일을 자동 다운로드하여
        전체 Bounding Box 기준으로 하나의 DEM을 생성.

        출력: self.dem_dir / "auto_downloaded_dem_WGS84.tif"
        """
        print("\n--- DEM 자동 준비 시작 (Total Bounding Box 기준) ---")
        self.dem_dir.mkdir(parents=True, exist_ok=True)

        # footprints는 EPSG:4326 (lon/lat) 가정
        if aoi_shp:
            aoi_gdf = gpd.read_file(aoi_shp).to_crs("EPSG:4326")
            footprints.append(aoi_gdf.union_all())
        combined_geom = gpd.GeoSeries(footprints, crs="EPSG:4326").union_all()
        lon_min, lat_min, lon_max, lat_max = combined_geom.bounds
        dem_path = self.dem_dir / "auto_downloaded_dem_WGS84.tif"
        if dem_path.exists():
            print(f"   - 이미 생성된 DEM 사용: {dem_path}")
            return str(dem_path)

        req_lons = range(math.floor(lon_min), math.ceil(lon_max))
        req_lats = range(math.floor(lat_min), math.ceil(lat_max))
        tile_urls = [
            (
                "https://copernicus-dem-30m.s3.amazonaws.com/"
                f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM/"
                f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
                f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM.tif"
            )
            for lat in req_lats
            for lon in req_lons
        ]

        downloaded = []
        for url in tqdm(tile_urls, desc="Downloading DEM tiles"):
            fname = self.dem_dir / Path(url).name
            if not fname.exists():
                try:
                    r = requests.get(url, stream=True, timeout=60)
                    r.raise_for_status()
                    with open(fname, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    downloaded.append(str(fname))
                except requests.exceptions.RequestException:
                    # 못 받는 타일은 스킵
                    pass
            else:
                downloaded.append(str(fname))
        if not downloaded:
            sys.exit("오류: DEM 타일을 다운로드할 수 없습니다.")

        print("\n   - 다운로드된 타일들을 VRT를 사용하여 병합 중...")
        vrt_path = self.dem_dir / "mosaic.vrt"
        tile_list_file = self.dem_dir / "tile_list.txt"
        with open(tile_list_file, 'w', encoding='utf-8') as f:
            for tile in downloaded:
                f.write(f"{tile}\n")

        try:
            gdalbuildvrt_exe = shutil.which("gdalbuildvrt")
            gdal_translate_exe = shutil.which("gdal_translate")
            if not gdalbuildvrt_exe or not gdal_translate_exe:
                raise RuntimeError("GDAL 실행 파일을 찾을 수 없습니다.")
            subprocess.run(
                [gdalbuildvrt_exe, '-input_file_list', str(tile_list_file), str(vrt_path)],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                [
                    gdal_translate_exe,
                    '-of', 'GTiff',
                    '-co', 'COMPRESS=LZW',
                    '-co', 'TILED=YES',
                    str(vrt_path),
                    str(dem_path),
                ],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            print("--- GDAL 오류 ---")
            print(e.stderr)
            sys.exit("GDAL 병합 실패")
        finally:
            if vrt_path.exists():
                vrt_path.unlink()
            if tile_list_file.exists():
                tile_list_file.unlink()

        print(f"   - DEM 생성 완료: {dem_path}")
        return str(dem_path)

    # ---------- Slope 자동 계산 ----------
    def _calculate_slope_from_dem(self, dem_wgs84_path, aoi_shp):
        """
        WGS84 DEM → (옵션 AOI 클립) → UTM 재투영 → gdaldem slope → 다시 WGS84로.
        출력 파일:
          - 00_dem_slope/Full_Scene_auto_slope_WGS84.tif   또는
          - 00_dem_slope/AOI_auto_slope_WGS84.tif
        """
        print("\n--- Slope 자동 계산 시작 ---")
        self.dem_dir.mkdir(parents=True, exist_ok=True)

        suffix = "AOI" if aoi_shp else "Full_Scene"
        slope_wgs84_path = self.dem_dir / f"{suffix}_auto_slope_WGS84.tif"
        if slope_wgs84_path.exists():
            print(f"   - 이미 생성된 Slope 사용: {slope_wgs84_path}")
            return str(slope_wgs84_path)

        dem_for_slope = dem_wgs84_path
        if aoi_shp:
            clipped_dem_path = self.dem_dir / f"{suffix}_clipped_dem_WGS84.tif"
            self._ensure_parent(clipped_dem_path)
            with rasterio.open(dem_wgs84_path) as src:
                aoi_gdf = gpd.read_file(aoi_shp).to_crs(src.crs)
                out_image, out_transform = mask(
                    dataset=src,
                    shapes=aoi_gdf.geometry,
                    crop=True,
                    nodata=-9999
                )
                out_meta = src.meta.copy()
                out_meta.update({
                    "height": out_image.shape[1],
                    "width": out_image.shape[2],
                    "transform": out_transform,
                })
                with rasterio.open(clipped_dem_path, "w", **out_meta) as dest:
                    dest.write(out_image)
            dem_for_slope = str(clipped_dem_path)

        dem_utm_path = self.dem_dir / f"{suffix}_dem_UTM.tif"
        self._ensure_parent(dem_utm_path)
        with rasterio.open(dem_for_slope) as src:
            lon_center = (src.bounds.left + src.bounds.right) / 2
            utm_zone = math.floor((lon_center + 180) / 6) + 1
            dst_crs = f'EPSG:326{utm_zone}'

            # UTM Zone Detection 로그
            print("[UTM Zone Detection]")
            print(f"    - Scene center lon: {lon_center:.2f}°")
            print(f"    - Computed UTM Zone: {utm_zone}N (EPSG:326{utm_zone})")

            transform, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds
            )
            kwargs = src.meta.copy()
            kwargs.update({
                'crs': dst_crs,
                'transform': transform,
                'width': width,
                'height': height,
            })
            with rasterio.open(dem_utm_path, 'w', **kwargs) as dst:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=WarpResampling.bilinear,
                )

        slope_utm_path = self.dem_dir / f"{suffix}_slope_UTM.tif"
        self._ensure_parent(slope_utm_path)
        try:
            gdaldem_exe = shutil.which("gdaldem")
            if not gdaldem_exe:
                raise RuntimeError("gdaldem not found")
            subprocess.run(
                [gdaldem_exe, 'slope', str(dem_utm_path), str(slope_utm_path), '-compute_edges'],
                check=True, capture_output=True, text=True
            )
        except Exception as e:
            print(f"   - gdaldem 실패({e}). numpy로 대체 계산")
            with rasterio.open(dem_utm_path) as src:
                dem = src.read(1).astype(np.float32)
                dem[dem == src.nodata] = np.nan
                dy, dx = np.gradient(dem, src.res[1], src.res[0])
                slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
                slope_deg = np.nan_to_num(slope_deg, nan=0.0)
                meta = src.meta.copy()
                meta.update({'dtype': 'float32', 'nodata': -9999})
                with rasterio.open(slope_utm_path, 'w', **meta) as dst:
                    dst.write(slope_deg.astype(np.float32), 1)

        # 다시 WGS84로
        self._ensure_parent(slope_wgs84_path)
        with rasterio.open(slope_utm_path) as src:
            dst_crs = "EPSG:4326"
            transform, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds
            )
            kwargs = src.meta.copy()
            kwargs.update({
                'crs': dst_crs,
                'transform': transform,
                'width': width,
                'height': height,
            })
            with rasterio.open(slope_wgs84_path, 'w', **kwargs) as dst:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=WarpResampling.bilinear,
                )
        print(f"   - Slope 생성 완료: {slope_wgs84_path}")
        return str(slope_wgs84_path)

    # ---------- 유효데이터 Footprint ----------
    def _get_valid_data_footprint(self, raster_path: str) -> MultiPolygon:
        print(f"   - '{Path(raster_path).name}'에서 유효 데이터 Footprint 추출 중...")
        with rasterio.open(raster_path) as src:
            image = src.read(1)
            nodata_val = src.nodata if src.nodata is not None else 0
            mask_array = (image != nodata_val) & (~np.isnan(image))
            results = (
                {'properties': {'raster_val': v}, 'geometry': s}
                for _, (s, v) in enumerate(
                    shapes(mask_array.astype('uint8'), mask=mask_array, transform=src.transform)
                )
            )
            geoms = [shape(r['geometry']) for r in results]
            if not geoms:
                return MultiPolygon()
            return unary_union(geoms)

    # ---------- 공통 영역 정렬 ----------
    def _align_two_to_intersection(self, tif1_path, tif2_path):
        """
        두 전처리된 GeoTIFF의 실제 유효 데이터 겹치는 영역만 잘라서
        동일한 extent로 맞춘 새로운 tif 2장을 생성.
        """
        print("\n--- 두 영상의 공통 중첩 영역으로 정렬 시작 ---")
        aligned_dir = self.base_dir / "01a_aligned_tifs"
        aligned_dir.mkdir(parents=True, exist_ok=True)

        footprint1 = self._get_valid_data_footprint(tif1_path)
        footprint2 = self._get_valid_data_footprint(tif2_path)
        inter = footprint1.intersection(footprint2)
        if inter.is_empty:
            sys.exit("오류: 두 파일의 실제 데이터 영역은 서로 중첩되지 않습니다.")
        print("   - 공통 영역 계산 완료.")

        # GeoJSON cutline 저장
        temp_cutline_path = aligned_dir / "temp_cutline.geojson"
        self._ensure_parent(temp_cutline_path)
        gdf = gpd.GeoDataFrame({'id': [0]}, geometry=[inter], crs="EPSG:4326")
        gdf.to_file(temp_cutline_path, driver='GeoJSON')

        out_paths = []
        try:
            gdalwarp_exe = shutil.which("gdalwarp")
            if not gdalwarp_exe:
                sys.exit("gdalwarp 실행파일을 찾을 수 없습니다.")

            for ip in [tif1_path, tif2_path]:
                ip = Path(ip)
                out_p = aligned_dir / f"{ip.stem}_aligned.tif"
                out_paths.append(str(out_p))
                if out_p.exists():
                    print(f"   - 이미 정렬된 파일: {out_p.name}")
                    continue
                print(f"   - 정렬 중: {ip.name} -> {out_p.name}")
                self._ensure_parent(out_p)
                cmd = [
                    gdalwarp_exe,
                    "-cutline", str(temp_cutline_path),
                    "-crop_to_cutline",
                    "-dstnodata", "0",
                    "-overwrite",
                    str(ip), str(out_p),
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print("--- GDAL 오류 ---")
            print(e.stderr)
            sys.exit("GDAL Warp 실패")
        finally:
            try:
                temp_cutline_path.unlink()
            except OSError:
                pass
        return out_paths

    # ---------- Edge-Otsu ----------
    def _edge_otsu_thresholding(self, image_data, initial_threshold, iterations):
        """
        초기 dB threshold 기반으로 거친 물 후보 → 경계 버퍼 → 그 주변에서 Otsu.
        """
        valid = ~np.isnan(image_data)
        if not np.any(valid):
            # 유효 픽셀이 없으면 전부 비물
            return np.zeros_like(image_data, dtype=bool), initial_threshold

        # 1) 초기 임계값 이진화 (물=True)
        water0 = np.zeros_like(image_data, dtype=bool)
        water0[valid] = image_data[valid] < initial_threshold

        # 2) 모폴로지 경계
        erode = binary_erosion(water0, iterations=1, border_value=0)
        dilate = binary_dilation(water0, iterations=1, border_value=0)
        edges = np.logical_and(dilate, ~erode)

        # 3) 경계 버퍼
        iters = max(1, int(iterations))
        buffered_edges = binary_dilation(edges, iterations=iters, border_value=0)

        # 4) 버퍼 영역(유효값만)에서 Otsu
        samples_mask = np.logical_and(buffered_edges, valid)
        if np.count_nonzero(samples_mask) == 0:
            final_threshold = threshold_otsu(image_data[valid].astype(np.float32))
        else:
            final_threshold = threshold_otsu(image_data[samples_mask].astype(np.float32))

        # 최종 마스크
        final_mask = np.zeros_like(water0, dtype=bool)
        final_mask[valid] = image_data[valid] < final_threshold
        return final_mask, float(final_threshold)

    # ---------- 수체 탐지 ----------
    def _detect_water_body_single(self, tif_path, output_dir, aoi_shp, slope_path,
                                  initial_db_thresh, slope_thresh, edge_buffer):
        """
        전처리(dB, TC 완료) GeoTIFF 1장에서 수체 마스크(0/1) 생성.
        """
        base_name = Path(tif_path).stem.replace('_processed', '').replace('_aligned', '')
        output_path = Path(output_dir) / f"{base_name}_watermask.tif"
        self._ensure_parent(output_path)
        if output_path.exists():
            print(f"   - 이미 생성된 마스크: {output_path.name}")
            return str(output_path)

        with rasterio.open(tif_path) as src:
            if aoi_shp:
                aoi_gdf = gpd.read_file(aoi_shp).to_crs(src.crs)
                try:
                    db_data, out_transform = mask(src, aoi_gdf.geometry, crop=True, nodata=np.nan)
                except ValueError:
                    print("   - 경고: AOI가 래스터와 겹치지 않아 생략")
                    return None
                db_data = db_data.squeeze()
                meta = src.meta.copy()
                meta.update({
                    "driver": "GTiff",
                    "height": db_data.shape[0],
                    "width": db_data.shape[1],
                    "transform": out_transform,
                    "nodata": 0,
                })
            else:
                db_data = src.read(1)
                meta = src.meta.copy()
                meta.update({"driver": "GTiff", "nodata": 0})

                db_data = db_data.astype(np.float32, copy=False)
                if src.nodata is not None:
                    db_data[db_data == src.nodata] = np.nan
                db_data[db_data == 0] = np.nan
                db_data[~np.isfinite(db_data)] = np.nan
                db_data[db_data <= -9999.0] = np.nan
                db_data[(~np.isnan(db_data)) & (db_data < -80.0)] = np.nan

            # Edge-Otsu
            water_mask, final_thresh = self._edge_otsu_thresholding(
                db_data, initial_db_thresh, edge_buffer
            )
            print(f"   - Edge Otsu 최종 임계값: {final_thresh:.4f} dB")

            # 경사도 기반 필터 (slope_path 있으면)
            if slope_path:
                with rasterio.open(slope_path) as slope_src:
                    slope_resampled = np.empty(db_data.shape, dtype=np.float32)
                    reproject(
                        source=rasterio.band(slope_src, 1),
                        destination=slope_resampled,
                        src_transform=slope_src.transform,
                        src_crs=slope_src.crs,
                        dst_transform=meta['transform'],
                        dst_crs=meta['crs'],
                        resampling=WarpResampling.bilinear,
                    )
                    steep = (slope_resampled >= slope_thresh)
                    water_mask[steep] = False

            final_mask = water_mask.astype(np.uint8)
            with rasterio.open(output_path, 'w', **meta) as dst:
                dst.write(final_mask, 1)

        print(f"   - 수체 마스크 생성 완료: {output_path.name}")
        return str(output_path)

    # ---------- 픽셀 면적 추정 ----------
    def _estimate_pixel_area_sqm(self, src):
        """CRS가 미터면 transform 기반, 경위도면 중심위도 이용한 근사."""
        transform: Affine = src.transform
        if src.crs and src.crs.is_projected:
            return abs(transform.a * transform.e)  # m²
        lat_center = (src.bounds.top + src.bounds.bottom) / 2.0
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_center))
        px_w_deg = abs(transform.a)
        px_h_deg = abs(transform.e)
        return (px_w_deg * m_per_deg_lon) * (px_h_deg * m_per_deg_lat)

    # ---------- 홍수 탐지: 단일 클래스 GeoTIFF (0/1/2) ----------
    def detect_flood_gain_loss(self, before_mask_path: Path, after_mask_path: Path, emit_stats: bool):
        """
        두 수체마스크를 비교하여 단일 GeoTIFF로 저장:
          0 = UNCHANGED (변화없음)
          1 = GAIN      (새로 잠김)
          2 = LOSS      (물이 빠짐)
        """
        print("\n--- 홍수 탐지 시작 (단일 클래스 GeoTIFF) ---")
        before_path, after_path = Path(before_mask_path), Path(after_mask_path)

        with rasterio.open(after_path) as after_src:
            after_arr = after_src.read(1)
            meta = after_src.profile

        with rasterio.open(before_path) as before_src:
            same_grid = (
                before_src.crs == meta['crs'] and
                before_src.transform == meta['transform'] and
                before_src.width == meta['width'] and
                before_src.height == meta['height']
            )
            if not same_grid:
                print("   - 경고: 'before'와 'after' 격자가 달라 보정합니다.")
                before_arr = np.zeros((meta['height'], meta['width']), dtype=np.uint8)
                reproject(
                    source=rasterio.band(before_src, 1),
                    destination=before_arr,
                    src_transform=before_src.transform,
                    src_crs=before_src.crs,
                    dst_transform=meta['transform'],
                    dst_crs=meta['crs'],
                    resampling=WarpResampling.nearest,
                )
            else:
                before_arr = before_src.read(1)

        before_bin = (before_arr >= 1)
        after_bin  = (after_arr  >= 1)

        class_arr = np.zeros(after_bin.shape, dtype=np.uint8)
        class_arr[np.logical_and(after_bin, np.logical_not(before_bin))] = 1  # GAIN
        class_arr[np.logical_and(before_bin, np.logical_not(after_bin))] = 2  # LOSS

        meta_out = meta.copy()
        meta_out.update({'dtype': 'uint8', 'nodata': 0})

        def _date_tag(p: Path):
            m = re.search(r'(\d{8})', p.stem)
            return m.group(1) if m else "unknown"

        date_before = _date_tag(before_path)
        date_after  = _date_tag(after_path)

        out_path = self.floodmask_dir / f"flood_change_{date_before}_{date_after}.tif"
        self._ensure_parent(out_path)
        with rasterio.open(out_path, 'w', **meta_out) as dst:
            dst.write(class_arr, 1)
            try:
                dst.write_colormap(1, {
                    0: (200, 200, 200, 255),  # unchanged - gray
                    1: (  0, 255, 255, 255),  # gain - cyan
                    2: (255, 180,   0, 255),  # loss - yellow-orange
                })
            except Exception:
                pass

        print(f"저장: {out_path}")

        if emit_stats:
            with rasterio.open(after_path) as src_for_area:
                px_area = self._estimate_pixel_area_sqm(src_for_area)

            gain_cnt = int((class_arr == 1).sum())
            loss_cnt = int((class_arr == 2).sum())
            gain_area = gain_cnt * px_area
            loss_area = loss_cnt * px_area

            print(f"[GAIN (새로 잠김)] pixels={gain_cnt:,}  approx_area_m2={gain_area:,.2f}")
            print(f"[LOSS (물이 빠짐)]  pixels={loss_cnt:,}  approx_area_m2={loss_area:,.2f}")

            stats_path = self.floodmask_dir / f"flood_stats_summary_{date_before}_{date_after}.txt"
            self._ensure_parent(stats_path)
            with open(stats_path, "w", encoding="utf-8") as f:
                f.write(f"Flood Change Statistics ({date_before} → {date_after})\n")
                f.write(f"Pixel size (approx): {px_area:.4f} m²\n\n")
                f.write(f"[GAIN (새로 잠김)] pixels={gain_cnt:,}  approx_area_m2={gain_area:,.2f}\n")
                f.write(f"[LOSS (물이 빠짐)]  pixels={loss_cnt:,}  approx_area_m2={loss_area:,.2f}\n")
            print(f" 통계 저장: {stats_path}")

        return [str(out_path)]

    # ---------- detect-flood 모드 ----------
    def run_detect_flood_mode(self, args):
        emit_stats = (args.flood_stats or "no").lower() == "yes"
        # output_dir는 floodmask_dir 생성 기준으로 사용
        _ = S1LocalProcessor(args.output_dir)
        self.detect_flood_gain_loss(Path(args.before_mask), Path(args.after_mask), emit_stats)

    # ---------- water 모드 (전처리된 TIF 기반) ----------
    def run_water_mode(self, args):
        print(f"\n--- 'water' 모드 시작: 전처리된 GeoTIFF {len(args.input_tifs)}개 ---")

        preprocessed_tifs = [str(Path(p)) for p in args.input_tifs]

        # ===== DEM & Slope 처리 =====
        dem_path = args.dem_path
        if not dem_path:
            # input_tifs의 공간범위 기반으로 DEM 영역 결정
            print("\n--- DEM 경로 미지정: input_tifs Footprint 기반 자동 다운로드 ---")
            footprints = []
            for tif in preprocessed_tifs:
                with rasterio.open(tif) as src:
                    if src.crs and src.crs.to_string() != "EPSG:4326":
                        # 경위도 아닌 경우 EPSG:4326으로 bounds 변환
                        left, bottom, right, top = transform_bounds(
                            src.crs, "EPSG:4326",
                            src.bounds.left, src.bounds.bottom,
                            src.bounds.right, src.bounds.top,
                            densify_pts=21
                        )
                    else:
                        left, bottom, right, top = (
                            src.bounds.left, src.bounds.bottom,
                            src.bounds.right, src.bounds.top
                        )
                    footprints.append(box(left, bottom, right, top))
            dem_path = self._prepare_dem_from_footprints(footprints, args.aoi_shp)
        else:
            print(f"\n--- 사용자 DEM 사용: {dem_path} ---")

        slope_path = args.slope_path
        if not slope_path:
            slope_path = self._calculate_slope_from_dem(dem_path, args.aoi_shp)
        else:
            print(f"--- 사용자 Slope 사용: {slope_path} ---")

        # ===== 수체 탐지 =====
        water_masks = []
        if args.aoi_shp:
            print("\n--- AOI 기준 수체 탐지 ---")
            for tif_path in preprocessed_tifs:
                wm = self._detect_water_body_single(
                    tif_path,
                    self.watermask_dir,
                    args.aoi_shp,
                    slope_path,
                    args.initial_db_threshold,
                    args.slope_threshold,
                    args.edge_buffer,
                )
                if wm:
                    water_masks.append(wm)
        else:
            if len(preprocessed_tifs) == 1:
                print("\n--- AOI 없음·단일 영상: 전체 장면 수체 탐지 ---")
                wm = self._detect_water_body_single(
                    preprocessed_tifs[0],
                    self.watermask_dir,
                    None,
                    slope_path,
                    args.initial_db_threshold,
                    args.slope_threshold,
                    args.edge_buffer,
                )
                if wm:
                    water_masks.append(wm)
            else:
                print("\n--- AOI 없음·다중 영상: 공통 교집합 정렬 + 수체 탐지 ---")
                t1, t2 = preprocessed_tifs[:2]
                aligned = self._align_two_to_intersection(t1, t2)
                for p in aligned:
                    wm = self._detect_water_body_single(
                        p,
                        self.watermask_dir,
                        None,
                        slope_path,
                        args.initial_db_threshold,
                        args.slope_threshold,
                        args.edge_buffer,
                    )
                    if wm:
                        water_masks.append(wm)

        # ===== 홍수탐지 토글 =====
        do_flood = (args.flood_detection or "no").lower() == "yes"
        do_stats = (args.flood_stats or "no").lower() == "yes"
        if do_flood and len(water_masks) >= 2:
            # 입력 tif 파일명 기준으로 시계열 정렬
            idx_earlier, idx_later, d1, d2 = self._select_chronological_indices_from_paths(
                preprocessed_tifs
            )
            try:
                before_mask = water_masks[idx_earlier]
                after_mask = water_masks[idx_later]
            except IndexError:
                # water_masks 순서가 달라졌을 경우 파일명 날짜 기반 재매칭
                def date_from_mask_path(p):
                    m = re.search(r'(\d{8})', Path(p).stem)
                    return dt.datetime.strptime(m.group(1), "%Y%m%d").date() if m else None
                wm_sorted = sorted(water_masks, key=date_from_mask_path)
                before_mask, after_mask = wm_sorted[0], wm_sorted[-1]
            self.detect_flood_gain_loss(Path(before_mask), Path(after_mask), do_stats)

        print("\n✅ 'water' 모드 작업 완료.")


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description="전처리된 Sentinel-1 GeoTIFF 기반 수체/홍수 탐지 스크립트 (snappy 미사용, DEM 자동다운 가능)"
    )
    subparsers = parser.add_subparsers(dest='mode', required=True)

    # water 모드: 전처리된 GeoTIFF → DEM/Slope 자동 + watermask (+ optional flood)
    p_water = subparsers.add_parser(
        'water',
        help="전처리(dB, TC 완료) GeoTIFF에서 DEM/Slope 자동 준비 후 수체 탐지(+옵션: 자동 홍수탐지)"
    )
    p_water.add_argument('--input_tifs', required=True, nargs='+',
                         help="전처리된 S1 dB GeoTIFF 경로(1개 이상)")
    p_water.add_argument('--output_dir', required=True, help="산출물 기본 폴더")
    p_water.add_argument('--aoi_shp', help="AOI Shapefile 경로(없으면 AOI 미사용)")
    p_water.add_argument('--dem_path', help="외부 DEM GeoTIFF 경로(없으면 자동 다운로드)")
    p_water.add_argument('--slope_path', help="외부 Slope GeoTIFF 경로(없으면 자동 계산)")
    p_water.add_argument('--initial_db_threshold', type=float, default=-20.0,
                         help="Edge Otsu 초기 임계값(dB)")
    p_water.add_argument('--slope_threshold', type=float, default=5.0,
                         help="경사 임계값(도)")
    p_water.add_argument('--edge_buffer', type=int, default=5,
                         help="Edge 감지 후 버퍼링 횟수")
    p_water.add_argument('--flood_detection', choices=['yes', 'no'], default='no',
                         help="두 시점 수체마스크로 홍수탐지 수행 여부")
    p_water.add_argument('--flood_stats', choices=['yes', 'no'], default='no',
                         help="홍수 결과 픽셀/면적 통계 로그 출력")

    # detect-flood 모드: 이미 만들어진 watermask 두 장 비교
    p_flood = subparsers.add_parser(
        'detect-flood',
        help="두 수체 마스크를 비교하여 홍수탐지 (gain/loss)"
    )
    p_flood.add_argument('--before_mask', required=True, help="이전 시점 수체 마스크 경로")
    p_flood.add_argument('--after_mask', required=True, help="이후 시점 수체 마스크 경로")
    p_flood.add_argument('--output_dir', required=True,
                         help="산출물 폴더(내부적으로 flood_mask 폴더 사용)")
    p_flood.add_argument('--flood_stats', choices=['yes', 'no'], default='no',
                         help="픽셀/면적 통계 로그 출력")

    args = parser.parse_args()
    processor = S1LocalProcessor(args.output_dir)

    if args.mode == 'water':
        processor.run_water_mode(args)
    elif args.mode == 'detect-flood':
        processor.run_detect_flood_mode(args)


if __name__ == "__main__":
    main()
