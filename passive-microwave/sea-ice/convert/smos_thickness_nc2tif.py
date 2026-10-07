"""
SMOS L3C Sea Ice Thickness (v3.6)
NC → GeoTIFF (EPSG:3995, Arctic Polar Stereographic) 변환

- 원본 투영: EPSG:3413 (WGS84 NSIDC Polar Stereo North)
- 출력 투영: EPSG:3995
- 해상도: 12.5km × 12.5km
- 변수: sea_ice_thickness, uncertainty

입력: <DATA_ROOT>/14_NSR/SMOS/Thickness/SMOS_Icethickness_v3.6_north_*.nc
출력: 같은 폴더에 *_{변수명}_epsg3995.tif

필요 패키지:
    conda activate GFW
    pip install netCDF4 rasterio pyproj numpy  (이미 설치됨)
"""

import numpy as np
from pathlib import Path
import netCDF4 as nc
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject, Resampling

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
INPUT_DIR   = Path(r"<DATA_ROOT>/14_NSR/SMOS/Thickness")
OUTPUT_DIR  = INPUT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_EPSG = 3995   # Arctic Polar Stereographic (WGS84)

# 변환할 변수 목록
VAR_LIST = [
    "sea_ice_thickness",
    "ice_thickness_uncertainty",
]

# 원본 투영: EPSG:3413 (v3.3 이후 WGS84 기반)
SRC_PROJ4 = (
    "+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +k=1 "
    "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)

# ─────────────────────────────────────────────
# 변수 읽기
# ─────────────────────────────────────────────
def read_variable(ds, var_name):
    if var_name not in ds.variables:
        return None

    v    = ds.variables[var_name]
    data = v[:]

    if data.ndim == 3:
        data = data[0]

    scale  = float(getattr(v, "scale_factor", 1.0))
    offset = float(getattr(v, "add_offset",   0.0))
    fill   = getattr(v, "_FillValue", None)

    arr  = np.array(data, dtype=np.float32)
    mask = np.ma.getmaskarray(data)

    if fill is not None:
        try:
            if not np.isnan(float(fill)):
                mask = mask | (arr == float(fill))
        except (ValueError, TypeError):
            pass

    arr = arr * scale + offset
    arr[mask] = np.nan
    return arr


# ─────────────────────────────────────────────
# 좌표 추출 → bounds 계산
# ─────────────────────────────────────────────
def get_bounds_and_transform(ds):
    x_arr = y_arr = None
    x_units = "m"

    # x/y 좌표 변수 탐색
    for xn in ["x", "xc", "X"]:
        if xn in ds.variables:
            x_arr   = np.array(ds.variables[xn][:], dtype=np.float64).ravel()
            x_units = getattr(ds.variables[xn], "units", "m")
            break

    for yn in ["y", "yc", "Y"]:
        if yn in ds.variables:
            y_arr = np.array(ds.variables[yn][:], dtype=np.float64).ravel()
            break

    # x/y 없으면 lon/lat 2D 배열로 시도
    if x_arr is None or y_arr is None:
        if "longitude" in ds.variables and "latitude" in ds.variables:
            # 2D lon/lat → 투영 좌표 변환
            from pyproj import Transformer
            lons = np.array(ds.variables["longitude"][:], dtype=np.float64)
            lats = np.array(ds.variables["latitude"][:],  dtype=np.float64)
            transformer = Transformer.from_crs(4326, 3413, always_xy=True)
            xs, ys = transformer.transform(lons.ravel(), lats.ravel())
            xs = xs.reshape(lons.shape)
            ys = ys.reshape(lons.shape)
            x_arr = xs[0, :]          # 첫 행의 x 좌표
            y_arr = ys[:, 0]          # 첫 열의 y 좌표
            x_units = "m"
            print("  lon/lat → 투영 좌표 변환으로 x/y 생성")
        else:
            raise ValueError(
                f"x/y 또는 lon/lat 좌표 변수를 찾을 수 없습니다.\n"
                f"  사용 가능한 변수: {list(ds.variables.keys())}"
            )

    # km → m
    if "km" in str(x_units).lower():
        x_arr *= 1000.0
        y_arr *= 1000.0
        print("  좌표 단위 km → m 변환")

    dx = abs(float(x_arr[1] - x_arr[0]))
    dy = abs(float(y_arr[1] - y_arr[0]))

    left   = float(x_arr.min()) - dx / 2
    right  = float(x_arr.max()) + dx / 2
    bottom = float(y_arr.min()) - dy / 2
    top    = float(y_arr.max()) + dy / 2

    nrows = len(y_arr)
    ncols = len(x_arr)

    needs_flip    = (y_arr[0] < y_arr[-1])
    src_transform = from_origin(left, top, dx, dy)

    return left, bottom, right, top, nrows, ncols, needs_flip, src_transform


# ─────────────────────────────────────────────
# 단일 NC 파일 변환
# ─────────────────────────────────────────────
def convert_smos_nc_to_tif(nc_path: Path):
    print(f"\n{'='*60}")
    print(f"변환: {nc_path.name}")

    with nc.Dataset(nc_path, "r") as ds:

        # CRS 확인 (NC 내부에 명시돼 있으면 출력)
        for vname in ds.variables:
            v = ds.variables[vname]
            if hasattr(v, "grid_mapping_name") or hasattr(v, "epsg_code"):
                epsg_code = getattr(v, "epsg_code", "N/A")
                gmap      = getattr(v, "grid_mapping_name", "N/A")
                print(f"  CRS 변수: {vname} | grid_mapping: {gmap} | EPSG: {epsg_code}")
                break

        # 좌표/transform
        (left, bottom, right, top,
         nrows, ncols, needs_flip, src_transform) = get_bounds_and_transform(ds)

        print(f"  격자 크기: {nrows} x {ncols}")
        if needs_flip:
            print("  y축 오름차순 → flipud 적용")

        src_crs = CRS.from_proj4(SRC_PROJ4)
        dst_crs = CRS.from_epsg(TARGET_EPSG)

        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs,
            ncols, nrows,
            left=left, bottom=bottom, right=right, top=top,
        )

        saved = []
        for var_name in VAR_LIST:
            arr = read_variable(ds, var_name)
            if arr is None:
                print(f"  [{var_name}] 변수 없음 → 건너뜀")
                continue

            if needs_flip:
                arr = np.flipud(arr)

            valid_count = np.sum(np.isfinite(arr))
            if valid_count == 0:
                print(f"  [{var_name}] 유효 데이터 없음 → 건너뜀")
                continue

            print(f"  [{var_name}] "
                  f"범위: {np.nanmin(arr):.4f} ~ {np.nanmax(arr):.4f} m  "
                  f"유효 픽셀: {valid_count}")

            # 재투영
            dst_arr = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
            reproject(
                source        = arr,
                destination   = dst_arr,
                src_transform = src_transform,
                src_crs       = src_crs,
                dst_transform = dst_transform,
                dst_crs       = dst_crs,
                resampling    = Resampling.nearest,
                src_nodata    = np.nan,
                dst_nodata    = np.nan,
            )

            # 저장
            out_path = OUTPUT_DIR / f"{nc_path.stem}_{var_name}_epsg3995.tif"
            with rasterio.open(
                out_path, "w",
                driver    = "GTiff",
                height    = dst_height,
                width     = dst_width,
                count     = 1,
                dtype     = "float32",
                crs       = dst_crs,
                transform = dst_transform,
                nodata    = np.nan,
                compress  = "lzw",
            ) as dst:
                dst.write(dst_arr, 1)
                dst.update_tags(
                    source   = "ESA SMOS L3C Sea Ice Thickness (AWI)",
                    variable = var_name,
                    epsg     = str(TARGET_EPSG),
                )

            mb = out_path.stat().st_size / 1024**2
            print(f"    → {out_path.name}  ({mb:.2f} MB)")
            saved.append(out_path.name)

    return saved


# ─────────────────────────────────────────────
# 일괄 변환
# ─────────────────────────────────────────────
def main():
    nc_files = sorted(INPUT_DIR.glob("SMOS_Icethickness_*_north_*.nc"))

    if not nc_files:
        print(f"[오류] SMOS_Icethickness_*_north_*.nc 파일 없음: {INPUT_DIR}")
        return

    print(f"총 {len(nc_files)}개 NC 파일 발견")
    all_success, all_failed = [], []

    for nc_path in nc_files:
        try:
            saved = convert_smos_nc_to_tif(nc_path)
            all_success.extend(saved)
        except Exception as e:
            import traceback
            print(f"  [실패] {nc_path.name}: {e}")
            traceback.print_exc()
            all_failed.append(nc_path.name)

    print(f"\n{'='*60}")
    print(f"완료: TIF {len(all_success)}개 생성 / NC {len(all_failed)}개 실패")
    if all_failed:
        print("실패 파일:")
        for f in all_failed:
            print(f"  - {f}")

if __name__ == "__main__":
    main()