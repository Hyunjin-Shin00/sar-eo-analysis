"""
OSI-SAF OSI-401-d Sea Ice Concentration
NC → GeoTIFF (EPSG:3995, Arctic Polar Stereographic) 변환

입력: <DATA_ROOT>/14_NSR/OSI_SAF/conc/*.nc
출력: 같은 폴더에 *_epsg3995.tif 저장

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
INPUT_DIR   = Path(r"<DATA_ROOT>/14_NSR/OSI_SAF/conc")
OUTPUT_DIR  = INPUT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_EPSG = 3995   # Arctic Polar Stereographic
VAR_NAME    = "ice_conc"

# ─────────────────────────────────────────────
# 단일 NC 파일 변환
# ─────────────────────────────────────────────
def convert_nc_to_tif(nc_path: Path):
    out_path = OUTPUT_DIR / (nc_path.stem + "_epsg3995.tif")
    print(f"\n{'='*60}")
    print(f"변환: {nc_path.name}")
    print(f"  → {out_path.name}")

    with nc.Dataset(nc_path, "r") as ds:

        # ── 1. 변수 읽기 ──
        var_key = VAR_NAME
        if var_key not in ds.variables:
            candidates = [v for v in ds.variables
                          if "conc" in v.lower() or "ice" in v.lower()]
            if not candidates:
                raise KeyError(f"변수 없음. 사용 가능: {list(ds.variables.keys())}")
            var_key = candidates[0]
            print(f"  변수 자동 선택: {var_key}")
        else:
            print(f"  변수: {var_key}")

        var  = ds.variables[var_key]
        data = var[:]

        if data.ndim == 3:
            data = data[0]
            print(f"  시간 차원 제거 → shape: {data.shape}")

        # 스케일/오프셋/FillValue
        scale  = float(getattr(var, "scale_factor", 1.0))
        offset = float(getattr(var, "add_offset",   0.0))
        fill   = getattr(var, "_FillValue", None)

        data_f = np.array(data, dtype=np.float32)
        mask   = np.ma.getmaskarray(data)
        if fill is not None:
            mask = mask | (data_f == float(fill))

        data_f = data_f * scale + offset
        data_f[mask] = np.nan
        print(f"  유효값 범위: {np.nanmin(data_f):.4f} ~ {np.nanmax(data_f):.4f}")

        # ── 2. CRS 읽기 ──
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
                    print(f"  CF 파싱 실패({e})")
                break

        if src_proj4 is None:
            # lat_0으로 남/북반구 구분
            lat_0 = -90 if "_sh_" in nc_path.name else 90
            lon_0 =   0 if lat_0 == -90 else -45
            lat_ts = lat_0
            src_proj4 = (
                f"+proj=stere +lat_0={lat_0} +lat_ts={lat_ts} +lon_0={lon_0} "
                f"+a=6378273 +b=6356889.44891 +units=m +no_defs"
            )
            print(f"  Fallback Proj4: {src_proj4}")

        # ── 3. x/y 좌표 → bounds 계산 ──
        x_arr = y_arr = None
        for xn in ["xc", "x"]:
            if xn in ds.variables:
                x_arr = np.array(ds.variables[xn][:], dtype=np.float64)
                x_units = getattr(ds.variables[xn], "units", "m")
                break
        for yn in ["yc", "y"]:
            if yn in ds.variables:
                y_arr = np.array(ds.variables[yn][:], dtype=np.float64)
                break

        if x_arr is None or y_arr is None:
            raise ValueError("x/y 좌표 변수를 찾을 수 없습니다.")

        # km → m 변환
        if "km" in str(x_units).lower():
            x_arr *= 1000.0
            y_arr *= 1000.0
            print("  좌표 단위 km → m 변환")

        dx = abs(float(x_arr[1] - x_arr[0]))
        dy = abs(float(y_arr[1] - y_arr[0]))

        # 픽셀 경계 bounds (중심좌표 ± 반픽셀)
        left   = float(x_arr.min()) - dx / 2
        right  = float(x_arr.max()) + dx / 2
        bottom = float(y_arr.min()) - dy / 2
        top    = float(y_arr.max()) + dy / 2

        nrows, ncols = data_f.shape

        # y축 방향: y_arr 오름차순이면 데이터는 남→북 → flipud
        if y_arr[0] < y_arr[-1]:
            data_f = np.flipud(data_f)
            print("  y축 오름차순 → flipud 적용")

        src_transform = from_origin(left, top, dx, dy)

    # ── 4. 재투영 ──
    src_crs = CRS.from_proj4(src_proj4)
    dst_crs = CRS.from_epsg(TARGET_EPSG)

    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs,
        ncols, nrows,
        left=left, bottom=bottom, right=right, top=top,
    )

    dst_data = np.full((dst_height, dst_width), np.nan, dtype=np.float32)

    reproject(
        source        = data_f,
        destination   = dst_data,
        src_transform = src_transform,
        src_crs       = src_crs,
        dst_transform = dst_transform,
        dst_crs       = dst_crs,
        resampling    = Resampling.nearest,
        src_nodata    = np.nan,
        dst_nodata    = np.nan,
    )

    # ── 5. GeoTIFF 저장 ──
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
        dst.write(dst_data, 1)
        dst.update_tags(
            source   = "OSI-SAF OSI-401-d Sea Ice Concentration",
            variable = var_key,
            epsg     = str(TARGET_EPSG),
        )

    tif_mb = out_path.stat().st_size / 1024**2
    print(f"  저장 완료: {out_path.name}  ({tif_mb:.2f} MB)")
    return out_path


# ─────────────────────────────────────────────
# 일괄 변환
# ─────────────────────────────────────────────
def main():
    nc_files = sorted(INPUT_DIR.glob("*_nh_*.nc"))
    if not nc_files:
        print(f"[오류] NC 파일 없음: {INPUT_DIR}")
        return

    print(f"총 {len(nc_files)}개 NC 파일 발견")
    success, failed = [], []

    for nc_path in nc_files:
        try:
            convert_nc_to_tif(nc_path)
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