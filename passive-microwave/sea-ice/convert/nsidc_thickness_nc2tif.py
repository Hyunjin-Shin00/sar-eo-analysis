"""
NSIDC ICESat-2 L4 Monthly Gridded Sea Ice Thickness (IS2SITMOGR4)
NC → GeoTIFF (EPSG:3995, Arctic Polar Stereographic) 변환

- 원본 투영: EPSG:3411 (NSIDC Sea Ice Polar Stereographic North, Hughes 1980)
- 출력 투영: EPSG:3995 (Arctic Polar Stereographic, WGS84)
- 해상도: 25km × 25km
- 출력: 변수별 개별 GeoTIFF (멀티밴드 또는 단일밴드)

변환 대상 변수 (VAR_LIST로 조정 가능):
    ice_thickness         : 해빙 두께 (m)
    ice_thickness_int     : 보간된 해빙 두께 (m)
    ice_thickness_unc     : 해빙 두께 불확도 (m)
    freeboard             : 프리보드 (m)
    snow_depth            : 적설 깊이 (m)
    sea_ice_conc          : 해빙 농도 (0~1)

입력: <DATA_ROOT>/14_NSR/NSIDC/Thickness/*.nc
출력: 같은 폴더에 *_{변수명}_epsg3995.tif

필요 패키지:
    conda activate GFW
    pip install netCDF4 rasterio pyproj numpy
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
INPUT_DIR   = Path(r"<DATA_ROOT>/14_NSR/NSIDC/Thickness")
OUTPUT_DIR  = INPUT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_EPSG = 3995   # Arctic Polar Stereographic (WGS84)

# 변환할 변수 목록 (필요한 것만 남기거나 추가)
VAR_LIST = [
    "ice_thickness",
    "ice_thickness_int",
    "ice_thickness_unc",
    "freeboard",
    "snow_depth",
    "sea_ice_conc",
]

# EPSG:3411 (Hughes 1980 타원체 기반 NSIDC Polar Stereo North)
SRC_PROJ4 = (
    "+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +k=1 "
    "+x_0=0 +y_0=0 +a=6378273 +b=6356889.449 +units=m +no_defs"
)

# ─────────────────────────────────────────────
# 단일 변수 읽기
# ─────────────────────────────────────────────
def read_variable(ds, var_name):
    """변수 읽기 + scale/offset/fill 처리 → float32 배열 반환"""
    if var_name not in ds.variables:
        return None

    v    = ds.variables[var_name]
    data = v[:]

    # time 차원 제거
    if data.ndim == 3:
        data = data[0]

    scale  = float(getattr(v, "scale_factor", 1.0))
    offset = float(getattr(v, "add_offset",   0.0))
    fill   = getattr(v, "_FillValue", None)
    valid_min = getattr(v, "valid_min", None)
    valid_max = getattr(v, "valid_max", None)

    arr  = np.array(data, dtype=np.float32)
    mask = np.ma.getmaskarray(data)

    if fill is not None:
        try:
            if not np.isnan(float(fill)):
                mask = mask | (arr == float(fill))
        except (ValueError, TypeError):
            pass

    arr = arr * scale + offset

    # valid range 밖은 NaN 처리
    if valid_min is not None:
        mask = mask | (arr < float(valid_min) * scale + offset)
    if valid_max is not None:
        mask = mask | (arr > float(valid_max) * scale + offset)

    arr[mask] = np.nan
    return arr


# ─────────────────────────────────────────────
# x/y 좌표 → bounds 계산
# ─────────────────────────────────────────────
def get_bounds_and_transform(ds):
    # IS2SITMOGR4 v3 이후: 1D x, y 변수
    # v1~v2: 2D xgrid, ygrid 변수
    x_arr = y_arr = None
    x_units = "m"

    for xn in ["x", "xgrid"]:
        if xn in ds.variables:
            x_raw = ds.variables[xn][:]
            x_units = getattr(ds.variables[xn], "units", "m")
            if x_raw.ndim == 2:
                x_arr = x_raw[0, :]   # 1행 추출
            else:
                x_arr = np.array(x_raw, dtype=np.float64)
            break

    for yn in ["y", "ygrid"]:
        if yn in ds.variables:
            y_raw = ds.variables[yn][:]
            if y_raw.ndim == 2:
                y_arr = y_raw[:, 0]   # 1열 추출
            else:
                y_arr = np.array(y_raw, dtype=np.float64)
            break

    if x_arr is None or y_arr is None:
        raise ValueError(
            f"x/y 좌표 변수를 찾을 수 없습니다.\n"
            f"  사용 가능한 변수: {list(ds.variables.keys())}"
        )

    # km → m 변환
    if "km" in str(x_units).lower():
        x_arr = x_arr * 1000.0
        y_arr = y_arr * 1000.0
        print("  좌표 단위 km → m 변환")

    dx = abs(float(x_arr[1] - x_arr[0]))
    dy = abs(float(y_arr[1] - y_arr[0]))

    left   = float(x_arr.min()) - dx / 2
    right  = float(x_arr.max()) + dx / 2
    bottom = float(y_arr.min()) - dy / 2
    top    = float(y_arr.max()) + dy / 2

    nrows = len(y_arr)
    ncols = len(x_arr)

    # y 오름차순이면 flipud 필요
    needs_flip = (y_arr[0] < y_arr[-1])

    src_transform = from_origin(left, top, dx, dy)

    return left, bottom, right, top, nrows, ncols, needs_flip, src_transform


# ─────────────────────────────────────────────
# 단일 NC 파일 변환
# ─────────────────────────────────────────────
def convert_thickness_nc_to_tif(nc_path: Path):
    print(f"\n{'='*60}")
    print(f"변환: {nc_path.name}")

    with nc.Dataset(nc_path, "r") as ds:

        # ── 좌표/transform 추출 ──
        (left, bottom, right, top,
         nrows, ncols, needs_flip, src_transform) = get_bounds_and_transform(ds)

        print(f"  격자 크기: {nrows} x {ncols}")
        print(f"  범위(원본 투영): left={left:.0f}, right={right:.0f}, "
              f"bottom={bottom:.0f}, top={top:.0f}")
        if needs_flip:
            print("  y축 오름차순 → flipud 적용")

        src_crs = CRS.from_proj4(SRC_PROJ4)
        dst_crs = CRS.from_epsg(TARGET_EPSG)

        # 재투영 파라미터 (변수 공통)
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
                  f"범위: {np.nanmin(arr):.4f} ~ {np.nanmax(arr):.4f}  "
                  f"유효 픽셀: {valid_count}")

            # ── 재투영 ──
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

            # ── 저장 ──
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
                    source   = "NSIDC IS2SITMOGR4 ICESat-2 Sea Ice Thickness",
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
    nc_files = sorted(INPUT_DIR.glob("IS2SITMOGR4*.nc"))

    if not nc_files:
        print(f"[오류] IS2SITMOGR4*.nc 파일 없음: {INPUT_DIR}")
        return

    print(f"총 {len(nc_files)}개 NC 파일 발견")
    all_success, all_failed = [], []

    for nc_path in nc_files:
        try:
            saved = convert_thickness_nc_to_tif(nc_path)
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
