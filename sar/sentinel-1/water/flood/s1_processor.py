# =============================================================================
# Sentinel-1 자동 수체 탐지 및 홍수 탐지 통합 파이프라인
# 파일명: s1_processor7.py (전처리 전에 인셋: 자동 NaN행 기반 트리밍)
# =============================================================================

# 코드 사용법 (Windows, 줄바꿈은 ^)

# [1] 단일 ZIP, AOI 없음 → 전체 장면 수체 탐지
# python <DATA_ROOT>\etc\code\s1_processor7.py preprocess ^
#   --input_zips "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250712T093124_20250712T093154_060049_0775E2_5D79.SAFE.zip" ^
#   --output_dir "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\ppre_final_test1" ^
#   --dem_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\auto_downloaded_dem_WGS84.tif" ^
#   --slope_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\Full_Scene_auto_slope_WGS84.tif" ^
#   --polarization VV --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection no --flood_stats no


# # [2] 단일 ZIP, AOI 지정 → AOI 영역만 수체 탐지
# python <DATA_ROOT>\etc\code\s1_processor7.py preprocess ^
#   --input_zips "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250712T093124_20250712T093154_060049_0775E2_5D79.SAFE.zip" ^
#   --output_dir "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\ppre_final_test2" ^
#   --aoi_shp "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\shp\AOI.shp" ^
#   --dem_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\auto_downloaded_dem_WGS84.tif" ^
#   --slope_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\Full_Scene_auto_slope_WGS84.tif" ^
#   --polarization VV --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection no --flood_stats no


# # [3] 다중 ZIP, AOI 없음 → 교집합 정렬 후 수체 탐지
# python <DATA_ROOT>\etc\code\s1_processor7.py preprocess ^
#   --input_zips ^
#   "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250712T093124_20250712T093154_060049_0775E2_5D79.SAFE.zip" ^
#   "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250719T092320_20250719T092350_060151_07795E_0ABD.SAFE.zip" ^
#   --output_dir "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\ppre_final_test3" ^
#   --dem_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\auto_downloaded_dem_WGS84.tif" ^
#   --slope_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\Full_Scene_auto_slope_WGS84.tif" ^
#   --polarization VV --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection no --flood_stats no


# # [4] 다중 ZIP + AOI 지정 → AOI 영역 수체 탐지
# python <DATA_ROOT>\etc\code\s1_processor7.py preprocess ^
#   --input_zips ^
#   "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250712T093124_20250712T093154_060049_0775E2_5D79.SAFE.zip" ^
#   "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250719T092320_20250719T092350_060151_07795E_0ABD.SAFE.zip" ^
#   --output_dir "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\ppre_final_test4" ^
#   --aoi_shp "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\shp\AOI.shp" ^
#   --dem_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\auto_downloaded_dem_WGS84.tif" ^
#   --slope_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\Full_Scene_auto_slope_WGS84.tif" ^
#   --polarization VV --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection no --flood_stats no


# # [5] 다중 ZIP → 자동 홍수 탐지까지 수행
# python <DATA_ROOT>\etc\code\s1_processor7.py preprocess ^
#   --input_zips ^
#   "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250712T093124_20250712T093154_060049_0775E2_5D79.SAFE.zip" ^
#   "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250719T092320_20250719T092350_060151_07795E_0ABD.SAFE.zip" ^
#   --output_dir "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\ppre_final_test5" ^
#   --dem_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\auto_downloaded_dem_WGS84.tif" ^
#   --slope_path "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\00_dem_slope\Full_Scene_auto_slope_WGS84.tif" ^
#   --polarization VV --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 ^
#   --flood_detection yes --flood_stats yes


# # [6] 기존 수체마스크 두 장으로 홍수 탐지만 수행
# python <DATA_ROOT>\etc\code\s1_processor7.py detect-flood ^
#   --before_mask "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\02_water_masks\S1A_20250712_VV_watermask.tif" ^
#   --after_mask  "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\TEST2\02_water_masks\S1A_20250719_VV_watermask.tif" ^
#   --output_dir "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\ppre_final_test6" ^
#   --flood_stats yes




import os
os.environ['PROJ_LIB'] = r'C:\Users\user\anaconda3\envs\snappy39\Library\share\proj'
os.environ['GDAL_DATA'] = r'C:\Users\user\anaconda3\envs\snappy39\Library\share\gdal'
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

try:
    from pyproj import datadir
    datadir.set_data_dir(os.environ['PROJ_LIB'])
except Exception:
    pass

import sys
import gc
import re
import math
import shutil
import requests
import argparse
import numpy as np
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
import subprocess
import datetime as dt

try:
    from shapely.geometry import Polygon, MultiPolygon, shape
    from shapely.ops import unary_union
    import geopandas as gpd
    import rasterio
    from rasterio.features import shapes
    from rasterio.mask import mask
    from rasterio.warp import reproject, Resampling as WarpResampling, calculate_default_transform
    from tqdm.auto import tqdm
    from affine import Affine
    from scipy.ndimage import distance_transform_edt, binary_dilation, binary_erosion
except ImportError as e:
    sys.exit(f"오류: 필수 라이브러리가 필요합니다. 상세: {e}")

try:
    from skimage.filters import threshold_otsu
    from skimage.feature import canny
except ImportError as e:
    sys.exit(f"오류: scikit-image 관련 라이브러리가 필요합니다. 상세: {e}")

try:
    from esa_snappy import ProductIO, GPF, HashMap, jpy
except ImportError:
    sys.exit("오류: esa_snappy를 찾을 수 없습니다. ESA SNAP이 올바르게 설치 및 구성되어 있어야 합니다.")


class S1LocalProcessor:
    def __init__(self, output_dir):
        self.base_dir = Path(output_dir)
        self.preprocess_dir = self.base_dir / "01_preprocessed"
        self.aligned_dir = self.base_dir / "01a_aligned_tifs"
        self.watermask_dir = self.base_dir / "02_water_masks"
        self.floodmask_dir = self.base_dir / "03_flood_mask"
        self.dem_dir = self.base_dir / "00_dem_slope"
        self._pre_clip_pixels = 0 

    # ---------- 유틸 ----------
    def _ensure_parent(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)

    def _get_short_name_from_zip(self, zip_path: Path):
        fname = zip_path.stem
        m = re.search(r'(S1[ABC])_.*?_(\d{8})T', fname)
        if m:
            sat, yyyymmdd = m.groups()
            return f"{sat}_{yyyymmdd}"
        return fname

    def _get_date_from_zip(self, zip_path: Path) -> dt.date:
        m = re.search(r'_(\d{8})T', zip_path.stem)
        if not m:
            raise ValueError(f"날짜 패턴(YYYYMMDDT)을 파일명에서 찾지 못했습니다: {zip_path.name}")
        dstr = m.group(1)
        return dt.datetime.strptime(dstr, "%Y%m%d").date()

    def _select_chronological_indices(self, zip_list):
        dates = [self._get_date_from_zip(Path(z)) for z in zip_list]
        order = sorted(range(len(dates)), key=lambda i: dates[i])
        return order[0], order[-1], dates[order[0]], dates[order[-1]]

    # ---------- ZIP footprint ----------
    def _get_footprint_from_zip(self, zip_path: Path) -> Polygon:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            manifest_path = next((s for s in zf.namelist() if 'manifest.safe' in s.lower()), None)
            if not manifest_path:
                raise FileNotFoundError(f"manifest.safe 파일을 찾을 수 없습니다: {zip_path.name}")
            with zf.open(manifest_path) as mf:
                tree = ET.parse(mf)
                root = tree.getroot()
                ns = {'gml': 'http://www.opengis.net/gml'}
                coords_str_element = root.find('.//gml:coordinates', namespaces=ns)
                if coords_str_element is None:
                    raise ValueError(f"Footprint 좌표를 찾을 수 없습니다: {zip_path.name}")
                coords_text = coords_str_element.text
                lat_lon_pairs = [p.split(',') for p in coords_text.strip().split()]
                points = [(float(lon), float(lat)) for lat, lon in lat_lon_pairs]
                return Polygon(points)

    # ---------- DEM 준비 ----------
    def _prepare_dem_from_footprints(self, footprints: list, aoi_shp: str):
        print("\n--- DEM 자동 준비 시작 (Total Bounding Box 기준) ---")
        self.dem_dir.mkdir(parents=True, exist_ok=True)

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
            f"https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM/Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM.tif"
            for lat in req_lats for lon in req_lons
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
            subprocess.run([gdalbuildvrt_exe, '-input_file_list', str(tile_list_file), str(vrt_path)], check=True, capture_output=True, text=True)
            subprocess.run([gdal_translate_exe, '-of', 'GTiff', '-co', 'COMPRESS=LZW', '-co', 'TILED=YES', str(vrt_path), str(dem_path)], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print("--- GDAL 오류 ---"); print(e.stderr)
            sys.exit("GDAL 병합 실패")
        finally:
            if vrt_path.exists(): vrt_path.unlink()
            if tile_list_file.exists(): tile_list_file.unlink()

        print(f"   - DEM 생성 완료: {dem_path}")
        return str(dem_path)

    # ---------- Slope ----------
    def _calculate_slope_from_dem(self, dem_wgs84_path, aoi_shp):
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
                out_image, out_transform = mask(dataset=src, shapes=aoi_gdf.geometry, crop=True, nodata=-9999)
                out_meta = src.meta.copy()
                out_meta.update({"height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
                with rasterio.open(clipped_dem_path, "w", **out_meta) as dest:
                    dest.write(out_image)
            dem_for_slope = str(clipped_dem_path)

        dem_utm_path = self.dem_dir / f"{suffix}_dem_UTM.tif"
        self._ensure_parent(dem_utm_path)
        with rasterio.open(dem_for_slope) as src:
            lon_center = (src.bounds.left + src.bounds.right) / 2
            utm_zone = math.floor((lon_center + 180) / 6) + 1
            dst_crs = f'EPSG:326{utm_zone}'

            # 🔹 UTM Zone Detection 로그 출력
            print("[UTM Zone Detection]")
            print(f"    - Scene center lon: {lon_center:.2f}°")
            print(f"    - Computed UTM Zone: {utm_zone}N (EPSG:326{utm_zone})")

            transform, width, height = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)
            kwargs = src.meta.copy(); kwargs.update({'crs': dst_crs, 'transform': transform, 'width': width, 'height': height})
            with rasterio.open(dem_utm_path, 'w', **kwargs) as dst:
                reproject(source=rasterio.band(src, 1), destination=rasterio.band(dst, 1),
                          src_transform=src.transform, src_crs=src.crs,
                          dst_transform=transform, dst_crs=dst_crs,
                          resampling=WarpResampling.bilinear)

        slope_utm_path = self.dem_dir / f"{suffix}_slope_UTM.tif"
        self._ensure_parent(slope_utm_path)
        try:
            gdaldem_exe = shutil.which("gdaldem")
            if not gdaldem_exe: raise RuntimeError("gdaldem not found")
            subprocess.run([gdaldem_exe, 'slope', str(dem_utm_path), str(slope_utm_path), '-compute_edges'],
                           check=True, capture_output=True, text=True)
        except Exception as e:
            print(f"   - gdaldem 실패({e}). numpy로 대체 계산")
            with rasterio.open(dem_utm_path) as src:
                dem = src.read(1).astype(np.float32)
                dem[dem == src.nodata] = np.nan
                dy, dx = np.gradient(dem, src.res[1], src.res[0])
                slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
                slope_deg = np.nan_to_num(slope_deg, nan=0.0)
                meta = src.meta.copy(); meta.update({'dtype': 'float32', 'nodata': -9999})
                with rasterio.open(slope_utm_path, 'w', **meta) as dst:
                    dst.write(slope_deg.astype(np.float32), 1)

        self._ensure_parent(slope_wgs84_path)
        with rasterio.open(slope_utm_path) as src:
            dst_crs = "EPSG:4326"
            transform, width, height = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)
            kwargs = src.meta.copy(); kwargs.update({'crs': dst_crs, 'transform': transform, 'width': width, 'height': height})
            with rasterio.open(slope_wgs84_path, 'w', **kwargs) as dst:
                reproject(source=rasterio.band(src, 1), destination=rasterio.band(dst, 1),
                          src_transform=src.transform, src_crs=src.crs,
                          dst_transform=transform, dst_crs=dst_crs,
                          resampling=WarpResampling.bilinear)
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
                for _, (s, v) in enumerate(shapes(mask_array.astype('uint8'), mask=mask_array, transform=src.transform))
            )
            geoms = [shape(r['geometry']) for r in results]
            if not geoms:
                return MultiPolygon()
            return unary_union(geoms)

    # ---------- 공통 영역 정렬 ----------
    def _align_two_to_intersection(self, tif1_path, tif2_path):
        print("\n--- 두 영상의 공통 중첩 영역으로 정렬 시작 ---")
        self.aligned_dir.mkdir(parents=True, exist_ok=True)

        footprint1 = self._get_valid_data_footprint(tif1_path)
        footprint2 = self._get_valid_data_footprint(tif2_path)
        inter = footprint1.intersection(footprint2)
        if inter.is_empty:
            sys.exit("오류: 두 파일의 실제 데이터 영역은 서로 중첩되지 않습니다.")
        print("   - 공통 영역 계산 완료.")

        temp_cutline_path = self.aligned_dir / "temp_cutline.geojson"
        self._ensure_parent(temp_cutline_path)
        gdf = gpd.GeoDataFrame({'id':[0]}, geometry=[inter], crs="EPSG:4326")
        gdf.to_file(temp_cutline_path, driver='GeoJSON')

        out_paths = []
        try:
            for ip in [tif1_path, tif2_path]:
                ip = Path(ip)
                out_p = self.aligned_dir / f"{ip.stem}_aligned.tif"
                out_paths.append(str(out_p))
                if out_p.exists():
                    print(f"   - 이미 정렬된 파일: {out_p.name}")
                    continue
                print(f"   - 정렬 중: {ip.name} -> {out_p.name}")
                gdalwarp_exe = shutil.which("gdalwarp")
                if not gdalwarp_exe:
                    sys.exit("gdalwarp 실행파일을 찾을 수 없습니다.")
                self._ensure_parent(out_p)
                cmd = [gdalwarp_exe, "-cutline", str(temp_cutline_path), "-crop_to_cutline",
                       "-dstnodata", "0", "-overwrite", str(ip), str(out_p)]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print("--- GDAL 오류 ---"); print(e.stderr); sys.exit("GDAL Warp 실패")
        finally:
            try: temp_cutline_path.unlink()
            except OSError: pass
        return out_paths

    # ---------- 전처리 전 자동 테두리 트리밍 ----------
    def _pick_edge_check_band(self, product):
        """
        트리밍 검사용 밴드 선택:
        우선순위: Intensity_* → Amplitude_* → Sigma0_*
        """
        prios = ['Intensity_', 'Amplitude_', 'Sigma0_']
        names = [b.getName() for b in product.getBands()]
        for p in prios:
            for nm in names:
                if nm.startswith(p):
                    return product.getBand(nm)
        return product.getBandAt(0)  # 폴백

    
    def _auto_trim_top_bottom_by_nan(self, product):
        """
        최상단/최하단 1행만 검사:
        - NaN 또는 밴드 NoData가 하나라도 있으면
            해당 방향으로 (그 행 포함) 100픽셀 트리밍.
        (0.0 값은 이번 규칙에서 제외)
        """
        try:
            w = product.getSceneRasterWidth()
            h = product.getSceneRasterHeight()
            if h <= 200:
                return product  # 너무 작으면 스킵

            band = self._pick_edge_check_band(product)

            # jpy 원시 배열 생성
            row_top = jpy.array('float', w)
            row_bottom = jpy.array('float', w)

            band.readPixels(0, 0, w, 1, row_top)
            band.readPixels(0, h - 1, w, 1, row_bottom)

            top_np = np.asarray(row_top, dtype=np.float32)
            bot_np = np.asarray(row_bottom, dtype=np.float32)

            nd_val = band.getNoDataValue()  # NoData가 NaN일 수도 있음
            nd_is_nan = math.isnan(nd_val)

            has_nan_top = np.isnan(top_np).any()
            has_nan_bot = np.isnan(bot_np).any()
            # NoData 체크 (NaN NoData면 위의 has_nan_*로 커버)
            has_nd_top = has_nan_top if nd_is_nan else (top_np == nd_val).any()
            has_nd_bot = has_nan_bot if nd_is_nan else (bot_np == nd_val).any()

            # 0은 제외
            has_invalid_top = has_nan_top or has_nd_top
            has_invalid_bot = has_nan_bot or has_nd_bot

            print(f"   - 상단행 검사: NaN={has_nan_top}, NoDataHit={has_nd_top}")
            print(f"   - 하단행 검사: NaN={has_nan_bot}, NoDataHit={has_nd_bot}")

            top_trim = 100 if has_invalid_top else 0
            bottom_trim = 100 if has_invalid_bot else 0
            if top_trim == 0 and bottom_trim == 0:
                return product

            y = top_trim
            new_h = h - top_trim - bottom_trim
            if new_h <= 0:
                print("   - 경고: 자동 트리밍 결과 높이가 0 이하. 트리밍 생략")
                return product

            sub_params = HashMap()
            sub_params.put('region', f"0,{y},{w},{new_h}")
            sub_params.put('copyMetadata', True)
            product = GPF.createProduct('Subset', sub_params, product)
            print(f"   - 자동 트리밍 적용: top {top_trim}px, bottom {bottom_trim}px")
            return product

        except Exception as e:
            print(f"   - 자동 트리밍 단계 경고(무시하고 진행): {e}")
            return product

    # ---------- DEM=0m 기반 바다 마스킹 ----------
    def _mask_sea_with_dem_zero(self, sar_tif_path: Path, dem_wgs84_path: str):
        """
        GLO-30 DEM 기준:
        - DEM 값이 정확히 0.0m 인 픽셀을 '바다'로 간주.
        - 해당 위치의 SAR dB 값을 nodata(또는 0.0)로 설정해서,
          이후 단계에서 바다가 분석 대상에 포함되지 않도록 함.
        """
        sar_tif_path = Path(sar_tif_path)

        if not sar_tif_path.exists():
            print(f"   - 바다 마스크 스킵: SAR 파일 없음: {sar_tif_path}")
            return
        if not dem_wgs84_path or (not Path(dem_wgs84_path).exists()):
            print(f"   - 바다 마스크 스킵: DEM 파일 없음: {dem_wgs84_path}")
            return

        try:
            print(f"   - GLO30 DEM 기반 바다 마스크(DEM=0m) 적용: {sar_tif_path.name}")
            with rasterio.open(sar_tif_path, 'r+') as src:
                sar_data = src.read(1).astype(np.float32)
                meta = src.meta.copy()

                # DEM을 SAR 격자로 최근접 리샘플 (값 0 보존)
                with rasterio.open(dem_wgs84_path) as dem_src:
                    dem_resampled = np.empty((src.height, src.width), dtype=np.float32)
                    reproject(
                        source=rasterio.band(dem_src, 1),
                        destination=dem_resampled,
                        src_transform=dem_src.transform, src_crs=dem_src.crs,
                        dst_transform=src.transform, dst_crs=src.crs,
                        resampling=WarpResampling.nearest
                    )

                # DEM이 유효하고 값이 정확히 0.0인 픽셀 → 바다
                sea_mask = np.isfinite(dem_resampled) & (dem_resampled == 0.0)

                # nodata 설정 (없으면 0.0으로)
                nodata_val = meta.get('nodata', None)
                if nodata_val is None:
                    nodata_val = 0.0
                    meta['nodata'] = nodata_val
                    src.nodata = nodata_val

                sar_data[sea_mask] = nodata_val

                src.write(sar_data, 1)
                src.update_tags(sea_mask="DEM==0m_based",
                                dem_used=str(Path(dem_wgs84_path).name))
        except Exception as e:
            print(f"   - GLO30 DEM 바다 마스크(DEM=0m) 단계 경고(무시하고 진행): {e}")

    # ---------- Sentinel-1 전처리 ----------
    def _s1_grd_preprocessing_single(self, product_path, output_dir, polarization, dem_path):
        try:
            short_name = self._get_short_name_from_zip(product_path)
            target_path = Path(output_dir) / f"{short_name}_{polarization}_processed.tif"
            self._ensure_parent(target_path)
            if target_path.exists():
                print(f"   - 이미 처리된 파일: {target_path.name}")
                return target_path

            product = ProductIO.readProduct(str(product_path))

            # (신규) 자동 NaN행 기반 상/하단 트리밍
            product = self._auto_trim_top_bottom_by_nan(product)

            params = HashMap()
            ops = [
                ('Apply-Orbit-File', {'Orbit State Vectors': 'Sentinel Precise (Auto Download)', 'Continue on Failure': 'true'}),
                ('ThermalNoiseRemoval', {'removeThermalNoise': True}),
                ('Remove-GRD-Border-Noise', {'borderMargin': 500}),
                ('Calibration', {'outputSigmaBand': True, 'selectedPolarisations': polarization}),
                ('Speckle-Filter', {'filter': 'Lee Sigma', 'filterSizeX': '7', 'filterSizeY': '7'}),
                ('Terrain-Correction', {'externalDEMFile': dem_path, 'externalDEMNoDataValue': -9999.0, 'pixelSpacingInMeter': 10.0, 'outputCoordinateSystem': 'EPSG:4326'}),
            ]
            for op_name, op_params in ops:
                params.clear()
                for k, v in op_params.items():
                    params.put(k, v)
                product = GPF.createProduct(op_name, params, product)

            # dB 변환
            params.clear()
            band_name = next((b.getName() for b in product.getBands() if b.getName().startswith('Sigma0_')), None)
            if not band_name:
                raise ValueError("TC 후 Sigma0 밴드를 찾을 수 없습니다.")
            params.put('sourceBands', band_name)
            product = GPF.createProduct('LinearToFromdB', params, product)

            ProductIO.writeProduct(product, str(target_path), 'GeoTIFF-BigTIFF')
            product.closeIO(); gc.collect()

            # 🔹 GLO-30 DEM 기반 바다 마스킹: DEM 값이 정확히 0.0m 인 픽셀 제거
            self._mask_sea_with_dem_zero(target_path, dem_path)

            print(f"   - 전처리 완료: {target_path.name}")
            return target_path
        except Exception:
            import traceback; traceback.print_exc()
            return None

    # ---------- Edge-Otsu ----------
    def _edge_otsu_thresholding(self, image_data, initial_threshold, iterations):
       
        valid = ~np.isnan(image_data)
        if not np.any(valid):
            # 유효 픽셀이 없으면 전부 비물
            return np.zeros_like(image_data, dtype=bool), initial_threshold

        # 1) 초기 임계값 이진화 (물=True)
        water0 = np.zeros_like(image_data, dtype=bool)
        water0[valid] = image_data[valid] < initial_threshold

        # 2) 모폴로지 경계
        # edges ≈ morphological gradient
        erode = binary_erosion(water0, iterations=1, border_value=0)
        dilate = binary_dilation(water0, iterations=1, border_value=0)
        edges = np.logical_and(dilate, ~erode)

        # 3) 경계 버퍼
        iters = max(1, int(iterations))
        buffered_edges = binary_dilation(edges, iterations=iters, border_value=0)

        # 4) 버퍼 영역(유효값만)에서 Otsu
        samples_mask = np.logical_and(buffered_edges, valid)
        if np.count_nonzero(samples_mask) == 0:
            # 경계 샘플이 없다면 전체 유효 픽셀에서 Otsu
            from skimage.filters import threshold_otsu
            final_threshold = threshold_otsu(image_data[valid].astype(np.float32))
        else:
            from skimage.filters import threshold_otsu
            final_threshold = threshold_otsu(image_data[samples_mask].astype(np.float32))

        # 최종 마스크
        final_mask = np.zeros_like(water0, dtype=bool)
        final_mask[valid] = image_data[valid] < final_threshold
        return final_mask, float(final_threshold)


    # ---------- 수체 탐지 ----------
    def _detect_water_body_single(self, tif_path, output_dir, aoi_shp, slope_path,
                                  initial_db_thresh, slope_thresh, edge_buffer):
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
                    "nodata": 0
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

            water_mask, final_thresh = self._edge_otsu_thresholding(
                db_data, initial_db_thresh, edge_buffer
            )
            print(f"   - Edge Otsu 최종 임계값: {final_thresh:.4f} dB")

            if slope_path:
                with rasterio.open(slope_path) as slope_src:
                    slope_resampled = np.empty(db_data.shape, dtype=np.float32)
                    reproject(
                        source=rasterio.band(slope_src, 1),
                        destination=slope_resampled,
                        src_transform=slope_src.transform, src_crs=slope_src.crs,
                        dst_transform=meta['transform'], dst_crs=meta['crs'],
                        resampling=WarpResampling.bilinear
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
        """CRS가 미터면 transform 기반으로 정확 계산, 경위도면 중심위도 근사."""
        transform: Affine = src.transform
        if src.crs and src.crs.is_projected:
            return abs(transform.a * transform.e)  # m²
        # 경위도 → 근사(m) 환산
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
        컬러맵도 함께 기록.
        통계는 픽셀/면적을 GAIN/LOSS 기준으로 출력/저장.
        """
        print("\n--- 홍수 탐지 시작 (단일 클래스 GeoTIFF) ---")
        before_path, after_path = Path(before_mask_path), Path(after_mask_path)

        # after를 기준 메타로 사용
        with rasterio.open(after_path) as after_src:
            after_arr = after_src.read(1)
            meta = after_src.profile

        # before 격자 정렬(최근접)
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
                    src_transform=before_src.transform, src_crs=before_src.crs,
                    dst_transform=meta['transform'], dst_crs=meta['crs'],
                    resampling=WarpResampling.nearest
                )
            else:
                before_arr = before_src.read(1)

        # --- 0/1 이진화
        before_bin = (before_arr >= 1)
        after_bin  = (after_arr  >= 1)

        # --- 클래스 계산
        # 0 = unchanged, 1 = gain (0->1), 2 = loss (1->0)
        class_arr = np.zeros(after_bin.shape, dtype=np.uint8)
        class_arr[np.logical_and( after_bin, np.logical_not(before_bin) )] = 1  # GAIN
        class_arr[np.logical_and( before_bin, np.logical_not(after_bin) )] = 2  # LOSS

        # --- 출력 메타데이터
        meta_out = meta.copy()
        meta_out.update({'dtype': 'uint8', 'nodata': 0})

        # 파일명 태그
        # ----- 파일명 태그: YYYYMMDD만 추출 -----
        def _date_tag(p: Path):
            m = re.search(r'(\d{8})', p.stem)
            return m.group(1) if m else "unknown"

        date_before = _date_tag(before_path)
        date_after  = _date_tag(after_path)

        # ----- 출력 파일명: flood_change_YYYYMMDD_YYYYMMDD.tif -----
        out_path = self.floodmask_dir / f"flood_change_{date_before}_{date_after}.tif"
        self._ensure_parent(out_path)
        with rasterio.open(out_path, 'w', **meta_out) as dst:
            dst.write(class_arr, 1)
            # 컬러맵(0=회색, 1=cyan, 2=yellow-orange)
            try:
                dst.write_colormap(1, {
                    0: (200, 200, 200, 255),  # unchanged - gray
                    1: (  0, 255, 255, 255),  # gain - cyan
                    2: (255, 180,   0, 255),  # loss - yellow-orange
                })
            except Exception:
                pass

        print(f"✅ 저장: {out_path}")

        # --- 통계(옵션): 파일명과 헤더도 날짜만 사용 ---
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


        # 단일 산출물 경로를 리스트로 반환
        return [str(out_path)]

    # ---------- 두 장 비교 진입점 유지 ----------
    def run_detect_flood_mode(self, args):
        emit_stats = (args.flood_stats or "no").lower() == "yes"
        self.detect_flood_gain_loss(Path(args.before_mask), Path(args.after_mask), emit_stats)

    # ---------- preprocess 모드 ----------
    def run_preprocess_and_detect(self, args):
        print(f"\n--- 'preprocess' 모드 시작: 총 {len(args.input_zips)}개 파일 처리 ---")

        # DEM & Slope
        dem_path = args.dem_path
        if not dem_path:
            fps = [self._get_footprint_from_zip(Path(p)) for p in args.input_zips]
            dem_path = self._prepare_dem_from_footprints(fps, args.aoi_shp)
        else:
            print(f"\n--- 사용자 DEM 사용: {dem_path} ---")
        slope_path = args.slope_path
        if not slope_path:
            slope_path = self._calculate_slope_from_dem(dem_path, args.aoi_shp)
        else:
            print(f"--- 사용자 Slope 사용: {slope_path} ---")

        # 전처리
        preprocessed_tifs = []
        for zp in args.input_zips:
            print(f"\n[전처리] 파일: {Path(zp).name}")
            t = self._s1_grd_preprocessing_single(Path(zp), self.preprocess_dir, args.polarization, dem_path)
            if t: preprocessed_tifs.append(str(t))
        if not preprocessed_tifs:
            sys.exit("오류: 전처리 결과가 없습니다.")

        # 수체 탐지
        water_masks = []
        if args.aoi_shp:
            print("\n--- AOI 기준 수체 탐지 ---")
            for tif_path in preprocessed_tifs:
                wm = self._detect_water_body_single(tif_path, self.watermask_dir, args.aoi_shp, slope_path,
                                                    args.initial_db_threshold, args.slope_threshold, args.edge_buffer)
                if wm: water_masks.append(wm)
        else:
            if len(preprocessed_tifs) == 1:
                print("\n--- AOI 없음·단일 영상: 전체 장면 수체 탐지 ---")
                wm = self._detect_water_body_single(preprocessed_tifs[0], self.watermask_dir, None, slope_path,
                                                    args.initial_db_threshold, args.slope_threshold, args.edge_buffer)
                if wm: water_masks.append(wm)
            else:
                print("\n--- AOI 없음·다중 영상: 교집합 정렬 + 수체 탐지 ---")
                t1, t2 = preprocessed_tifs[:2]
                aligned = self._align_two_to_intersection(t1, t2)
                for p in aligned:
                    wm = self._detect_water_body_single(p, self.watermask_dir, None, slope_path,
                                                        args.initial_db_threshold, args.slope_threshold, args.edge_buffer)
                    if wm: water_masks.append(wm)

        # 홍수탐지 토글
        do_flood = (args.flood_detection or "no").lower() == "yes"
        do_stats = (args.flood_stats or "no").lower() == "yes"
        if do_flood and len(water_masks) >= 2:
            # 입력 ZIP 기준으로 시계열 정렬한 인덱스를 사용해 매칭
            idx_earlier, idx_later, d1, d2 = self._select_chronological_indices(args.input_zips)
            try:
                before_mask = water_masks[idx_earlier]
                after_mask = water_masks[idx_later]
            except IndexError:
                # 정렬/정합 단계에서 파일 순서가 달라졌을 가능성 → 파일명 날짜 기반 재매칭
                def date_from_mask_path(p):
                    m = re.search(r'(\d{8})', Path(p).stem)
                    return dt.datetime.strptime(m.group(1), "%Y%m%d").date() if m else None
                wm_sorted = sorted(water_masks, key=date_from_mask_path)
                before_mask, after_mask = wm_sorted[0], wm_sorted[-1]
            self.detect_flood_gain_loss(Path(before_mask), Path(after_mask), do_stats)

        print("\n✅ 'preprocess' 모드 작업 완료.")


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter,
                                     description="로컬 Sentinel-1 파일 처리 및 분석 스크립트")
    subparsers = parser.add_subparsers(dest='mode', required=True)

    # preprocess
    p_pre = subparsers.add_parser('preprocess', help="S1 ZIP 전처리 후 수체 탐지(+옵션: 자동 홍수탐지)")
    p_pre.add_argument('--input_zips', required=True, nargs='+', help="입력 S1 원본 ZIP 경로(1개 이상)")
    p_pre.add_argument('--output_dir', required=True, help="산출물 기본 폴더")
    p_pre.add_argument('--aoi_shp', help="AOI Shapefile 경로(없으면 AOI 미사용)")
    p_pre.add_argument('--dem_path', help="외부 DEM GeoTIFF 경로(없으면 자동 다운로드)")
    p_pre.add_argument('--slope_path', help="외부 Slope GeoTIFF 경로(없으면 자동 계산)")
    p_pre.add_argument('--polarization', default='VV', choices=['VV', 'VH'], help="편파 (기본: VV)")
    p_pre.add_argument('--initial_db_threshold', type=float, default=-20.0, help="Edge Otsu 초기 임계값(dB)")
    p_pre.add_argument('--slope_threshold', type=float, default=5.0, help="경사 임계값(도)")
    p_pre.add_argument('--edge_buffer', type=int, default=5, help="Edge 감지 후 버퍼링 횟수")
    # 홍수탐지/통계 토글
    p_pre.add_argument('--flood_detection', choices=['yes', 'no'], default='no', help="두 시점 수체마스크로 홍수탐지 수행 여부")
    p_pre.add_argument('--flood_stats', choices=['yes', 'no'], default='no', help="홍수 결과 픽셀/면적 통계 로그 출력")

    # detect-flood (기존 두 마스크 비교 모드, 결과는 gain/loss/affected로 확장)
    p_flood = subparsers.add_parser('detect-flood', help="두 수체 마스크를 비교하여 홍수탐지 (gain/loss/affected)")
    p_flood.add_argument('--before_mask', required=True, help="이전 시점 수체 마스크 경로")
    p_flood.add_argument('--after_mask', required=True, help="이후 시점 수체 마스크 경로")
    p_flood.add_argument('--output_dir', required=True, help="산출물 폴더(무시됨: 클래스 내부 폴더 사용)")
    p_flood.add_argument('--flood_stats', choices=['yes', 'no'], default='no', help="픽셀/면적 통계 로그 출력")

    args = parser.parse_args()
    processor = S1LocalProcessor(args.output_dir)

    if args.mode == 'preprocess':
        processor.run_preprocess_and_detect(args)
    elif args.mode == 'detect-flood':
        processor.run_detect_flood_mode(args)


if __name__ == "__main__":
    main()
