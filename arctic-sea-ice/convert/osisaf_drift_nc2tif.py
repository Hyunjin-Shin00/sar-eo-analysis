"""
OSI-SAF OSI-405-d Sea Ice Drift
NC → GeoTIFF (EPSG:3995, Arctic Polar Stereographic) 변환

- 북반구(_nh_) 파일만 처리
- 출력: 2-band GeoTIFF (Band 1 = dX, Band 2 = dY), 단위: km/2days
- 저장 경로: <DATA_ROOT>/14_NSR/OSI_SAF/sea ice drift/ (원본과 같은 폴더)

필요 패키지:
    conda activate GFW
    pip install netCDF4 rasterio pyproj numpy  (이미 설치되어 있으면 생략)
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
INPUT_DIR   = Path(r"<DATA_ROOT>/14_NSR/OSI_SAF/sea ice drift")
OUTPUT_DIR  = INPUT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_EPSG = 3995   # Arctic Polar Stereographic

# drift 변수명 (OSI-405 계열)
DX_NAMES = ["dX", "dx", "drift_x", "u"]   # x 방향 변위 후보
DY_NAMES = ["dY", "dy", "drift_y", "v"]   # y 방향 변위 후보

# ─────────────────────────────────────────────
# 단일 NC 파일 변환
# ─────────────────────────────────────────────
def convert_drift_nc_to_tif(nc_path: Path):
    out_path = OUTPUT_DIR / (nc_path.stem + "_epsg3995.tif")
    print(f"\n{'='*60}")
    print(f"변환: {nc_path.name}")
    print(f"  → {out_path.name}")

    with nc.Dataset(nc_path, "r") as ds:

        # ── 1. 변수 목록 출력 (디버그용) ──
        all_vars = list(ds.variables.keys())

        # ── 2. dX, dY 변수 탐색 ──
        dx_key = dy_key = None
        for name in DX_NAMES:
            if name in ds.variables:
                dx_key = name
                break
        for name in DY_NAMES:
            if name in ds.variables:
                dy_key = name
                break

        if dx_key is None or dy_key is None:
            raise KeyError(
                f"dX/dY 변수를 찾을 수 없습니다.\n"
                f"  사용 가능한 변수: {all_vars}"
            )
        print(f"  변수: {dx_key} (dX), {dy_key} (dY)")

        def read_var(vname):
            v    = ds.variables[vname]
            data = v[:]
            # time 차원 제거
            if data.ndim == 3:
                data = data[0]
            scale  = float(getattr(v, "scale_factor", 1.0))
            offset = float(getattr(v, "add_offset",   0.0))
            fill   = getattr(v, "_FillValue", None)

            arr  = np.array(data, dtype=np.float32)
            mask = np.ma.getmaskarray(data)
            if fill is not None:
                # NaN fill (OSI-405-d) 또는 정수 fill 모두 처리
                if not np.isnan(float(fill)):
                    mask = mask | (arr == float(fill))
            arr = arr * scale + offset
            arr[mask] = np.nan
            return arr

        dx_data = read_var(dx_key)
        dy_data = read_var(dy_key)
        print(f"  shape: {dx_data.shape}")
        print(f"  dX 범위: {np.nanmin(dx_data):.3f} ~ {np.nanmax(dx_data):.3f} km")
        print(f"  dY 범위: {np.nanmin(dy_data):.3f} ~ {np.nanmax(dy_data):.3f} km")

        # ── 3. CRS 읽기 ──
        src_proj4 = None
        for vname in ds.variables:
            v = ds.variables[vname]
            if hasattr(v, "grid_mapping_name"):
                print(f"  CRS 변수: {vname} ({v.grid_mapping_name})")
                try:
                    from pyproj import CRS as ProjCRS
                    attrs = {k: getattr(v, k) for k in v.ncattrs()}
                    src_proj4 = ProjCRS.from_cf(attrs).to_proj4()
                    print(f"  Proj4: {src_proj4}")
                except Exception as e:
                    print(f"  CF 파싱 실패({e}), fallback 사용")
                break

        if src_proj4 is None:
            # OSI-405 북반구 기본값 (62.5km 격자)
            src_proj4 = (
                "+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 "
                "+a=6378273 +b=6356889.44891 +units=m +no_defs"
            )
            print(f"  Fallback Proj4: {src_proj4}")

        # ── 4. x/y 좌표 → bounds 계산 ──
        x_arr = y_arr = None
        for xn in ["xc", "x"]:
            if xn in ds.variables:
                x_arr   = np.array(ds.variables[xn][:], dtype=np.float64)
                x_units = getattr(ds.variables[xn], "units", "m")
                break
        for yn in ["yc", "y"]:
            if yn in ds.variables:
                y_arr = np.array(ds.variables[yn][:], dtype=np.float64)
                break

        if x_arr is None or y_arr is None:
            raise ValueError("x/y 좌표 변수를 찾을 수 없습니다.")

        if "km" in str(x_units).lower():
            x_arr *= 1000.0
            y_arr *= 1000.0
            print("  좌표 단위 km → m 변환")

    dx_val = abs(float(x_arr[1] - x_arr[0]))
    dy_val = abs(float(y_arr[1] - y_arr[0]))

    left   = float(x_arr.min()) - dx_val / 2
    right  = float(x_arr.max()) + dx_val / 2
    bottom = float(y_arr.min()) - dy_val / 2
    top    = float(y_arr.max()) + dy_val / 2

    nrows, ncols = dx_data.shape

    # y축 방향 보정
    if y_arr[0] < y_arr[-1]:
        dx_data = np.flipud(dx_data)
        dy_data = np.flipud(dy_data)
        print("  y축 오름차순 → flipud 적용")

    src_transform = from_origin(left, top, dx_val, dy_val)

    # ── 5. EPSG:3995 재투영 ──
    src_crs = CRS.from_proj4(src_proj4)
    dst_crs = CRS.from_epsg(TARGET_EPSG)

    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs,
        ncols, nrows,
        left=left, bottom=bottom, right=right, top=top,
    )

    dst_dx = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
    dst_dy = np.full((dst_height, dst_width), np.nan, dtype=np.float32)

    for src_band, dst_band in [(dx_data, dst_dx), (dy_data, dst_dy)]:
        reproject(
            source        = src_band,
            destination   = dst_band,
            src_transform = src_transform,
            src_crs       = src_crs,
            dst_transform = dst_transform,
            dst_crs       = dst_crs,
            resampling    = Resampling.nearest,
            src_nodata    = np.nan,
            dst_nodata    = np.nan,
        )

    # ── 6. 2-band GeoTIFF 저장 ──
    with rasterio.open(
        out_path, "w",
        driver    = "GTiff",
        height    = dst_height,
        width     = dst_width,
        count     = 2,           # Band 1: dX, Band 2: dY
        dtype     = "float32",
        crs       = dst_crs,
        transform = dst_transform,
        nodata    = np.nan,
        compress  = "lzw",
    ) as dst:
        dst.write(dst_dx, 1)
        dst.write(dst_dy, 2)
        dst.update_tags(
            source  = "OSI-SAF OSI-405-d Sea Ice Drift",
            band1   = f"{dx_key}: x-direction displacement (km/2days)",
            band2   = f"{dy_key}: y-direction displacement (km/2days)",
            epsg    = str(TARGET_EPSG),
        )
        # 밴드별 설명 태그
        dst.update_tags(1, name=dx_key, description="x-direction drift (km/2days)")
        dst.update_tags(2, name=dy_key, description="y-direction drift (km/2days)")

    tif_mb = out_path.stat().st_size / 1024**2
    print(f"  저장 완료: {out_path.name}  ({tif_mb:.2f} MB)")
    return out_path


# ─────────────────────────────────────────────
# 일괄 변환 (북반구만)
# ─────────────────────────────────────────────
def main():
    nc_files = sorted(INPUT_DIR.glob("*_nh_*.nc"))

    if not nc_files:
        # _nh_ 패턴이 없으면 전체 nc 시도 (파일명 구조 확인용)
        all_nc = sorted(INPUT_DIR.glob("*.nc"))
        if not all_nc:
            print(f"[오류] NC 파일 없음: {INPUT_DIR}")
            return
        print(f"[참고] '_nh_' 패턴 파일 없음. 전체 NC 파일 목록:")
        for f in all_nc:
            print(f"  {f.name}")
        print("\n파일명을 확인 후 glob 패턴을 수정하세요.")
        return

    print(f"총 {len(nc_files)}개 NC 파일 발견 (북반구)")
    success, failed = [], []

    for nc_path in nc_files:
        try:
            convert_drift_nc_to_tif(nc_path)
            success.append(nc_path.name)
        except Exception as e:
            print(f"  [실패] {nc_path.name}: {e}")
            failed.append(nc_path.name)

    print(f"\n{'='*60}")
    print(f"완료: {len(success)}개 성공 / {len(failed)}개 실패")
    if failed:
        print("실패 파일:")
        for f in failed:
            print(f"  - {f}")

if __name__ == "__main__":
    main()
