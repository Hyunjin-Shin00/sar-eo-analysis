import os
import rasterio
from rasterio.mask import mask
import geopandas as gpd
import glob
import numpy as np
from rasterio.enums import Resampling
from rasterio.warp import reproject, Resampling as WarpResampling
import re
from datetime import datetime
from pathlib import Path

def clip_tiff(tif_list, aoi_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    # -----------------------------------

    # AOI 읽기
    aoi = gpd.read_file(aoi_path)
    aoi = aoi.to_crs("EPSG:4326")  # AOI 좌표계를 WGS84로 변환 (tif와 동일해야 함)

    # 각 tif 파일 클립 수행
    for tif_path in tif_list:
        with rasterio.open(tif_path) as src:
            # 좌표계 맞추기
            if aoi.crs.to_string() != src.crs.to_string():
                aoi = aoi.to_crs(src.crs)

            # AOI 영역으로 마스크
            out_image, out_transform = mask(dataset=src, shapes=aoi.geometry, crop=True)
            out_meta = src.meta.copy()
            out_meta.update({
                "driver": "GTiff",
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform
            })

            # 저장 경로
            out_name = os.path.basename(tif_path).replace(".tif", "_clipped.tif")
            out_path = os.path.join(output_dir, out_name)

            # 저장
            with rasterio.open(out_path, "w", **out_meta) as dest:
                dest.write(out_image)

            print(f"✔ 클립 완료: {out_path}")

def waterbody_detection(db_path, slope_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    # ---------------- 필터 조건 ----------------
    SLOPE_THRESHOLD = 15  # 15도 이상인 곳 지우기
    DB_THRESHOLD = -15    # -15 db 이하인 곳 지우기

    # ---------------- 출력 파일명 생성 ----------------
    # 예: S1A_IW_GRDH_1SDV_20250719_Orb_... → S1A, 20250719 추출
    basename = os.path.basename(db_path)
    match = re.search(r'(S1[ABC])_.*?_(\d{8})_', basename)
    if match:
        satellite = match.group(1)
        date = match.group(2)
        out_filename = f"{satellite}_{date}_slopeFiltered_binaryMask.tif"
    else:
        out_filename = "slopeFiltered_binaryMask.tif"  # fallback

    output_path = os.path.join(output_dir, out_filename)

    # ---------------- Sentinel-1 dB 영상 불러오기 ----------------
    with rasterio.open(db_path) as db_src:
        db_data = db_src.read(1)
        db_meta = db_src.meta
        db_crs = db_src.crs
        db_transform = db_src.transform
        db_height = db_src.height
        db_width = db_src.width

    # ---------------- slope.tif 재투영 및 리샘플 ----------------
    with rasterio.open(slope_path) as slope_src:
        slope_data_resampled = np.empty((db_height, db_width), dtype=np.float32)

        reproject(
            source=rasterio.band(slope_src, 1),
            destination=slope_data_resampled,
            src_transform=slope_src.transform,
            src_crs=slope_src.crs,
            dst_transform=db_transform,
            dst_crs=db_crs,
            dst_resolution=(db_transform.a, -db_transform.e),
            resampling=WarpResampling.bilinear
        )

    # ---------------- 조건 마스크 생성 ----------------
    mask = ((slope_data_resampled < SLOPE_THRESHOLD) & (db_data < DB_THRESHOLD)).astype("uint8")

    # ---------------- 저장 ----------------
    db_meta.update({
        "dtype": "uint8",
        "nodata": 0,
        "count": 1
    })

    with rasterio.open(output_path, 'w', **db_meta) as dst:
        dst.write(mask, 1)

    print(f"✔ 저장 완료: {output_path}")


def diff_waterbody(binary_after_path, binary_before_path,output_path):
    # 1. 두 마스크 파일 읽기
    with rasterio.open(binary_after_path) as after_src, rasterio.open(binary_before_path) as before_src:
        after = after_src.read(1).astype(np.int8)
        before = before_src.read(1).astype(np.int8)
        meta = after_src.meta

    # 2. 차분: after - before
    diff = after - before

    # 3. 홍수 발생한 지역만 추출: 1 (새롭게 생긴 수체), 나머지 0
    flood_mask = (diff == 1).astype("uint8")

    # 4. 저장 메타 설정
    meta.update({
        "dtype": "uint8",
        "count": 1,
        "nodata": 0
    })

    # 5. 결과 저장
    after_time=os.path.basename(binary_after_path).split("_")[1]
    before_time=os.path.basename(binary_before_path).split("_")[1]
    output_filename=rf"{output_path}\{before_time}_{after_time}_diff_binary.tif"
    with rasterio.open(output_filename, 'w', **meta) as dst:
        dst.write(flood_mask, 1)

    print(f"✔ 홍수 발생 영역 추출 완료: {output_filename}")


if __name__ == "__main__":
    # ---------- 사용자 입력 ----------
    tif_list = [
        r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\process\S1A_IW_GRDH_1SDV_20250719_Orb_NR_Cal_Spk_TC_dB.tif",
        r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\process\S1C_IW_GRDH_1SDV_20250712_Orb_NR_Cal_Spk_TC_dB.tif",
        r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\process\S1C_IW_GRDH_1SDV_20250718_Orb_NR_Cal_Spk_TC_dB.tif",
        r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\dem\output_hh.tif"
    ]

    aoi_path = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\shp\AOI.shp"  # AOI shapefile 경로
    output_dir = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\test"    # 출력 경로

    clip_tiff(tif_list,aoi_path,output_dir)

    db_path = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\test"
    slope_path = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\dem\slope.tif"
    output_dir = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\test"

    db_file_list = glob.glob(rf"{db_path}\S1*dB_clipped.tif")

    for db_file in db_file_list:
        waterbody_detection(db_file, slope_path, output_dir)

    binary_path = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\test"   # 홍수 이후
    binary_before_path = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\test\S1C_20250712_slopeFiltered_binaryMask.tif" # 홍수 이전
    output_path = r"<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\test" 

    binary_file_list = sorted(glob.glob(rf"{binary_path}\S1*_slopeFiltered_binaryMask.tif"),
    key=lambda x: datetime.strptime(Path(x).stem.split("_")[1], "%Y%m%d"))

    for i in range(len(binary_file_list) - 1):
        diff_waterbody(binary_file_list[i+1],binary_file_list[0], output_path)