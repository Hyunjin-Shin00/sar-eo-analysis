"""
validate_bb_aod.py — MODIS MAIAC 기반 BlueBON/S2 AOD 검증 및 radiance_scale 보정

기능
----
1. MODIS MCD19A2 (MAIAC AOD) 자동 다운로드  (NASA Earthdata 계정 필요)
2. 타일 h28v05 → WGS84 재투영
3. BlueBON AOD vs MAIAC : Bias / RMSE / R² + scatter plot
4. S2 AOD vs MAIAC (optional, 날짜 다름 주의)
5. BlueBON radiance_scale 역산 — DDV 픽셀에서 최적 scale 추정
6. 개선된 파라미터로 bb_aod_calval.py 재실행 권장값 출력

NASA Earthdata 계정 설정 방법
------------------------------
방법 A. ~/.netrc 파일 생성
    machine urs.earthdata.nasa.gov
    login  YOUR_USERNAME
    password YOUR_PASSWORD

방법 B. 환경 변수
    export EARTHDATA_USERNAME=...
    export EARTHDATA_PASSWORD=...

방법 C. 스크립트 실행 시 --username / --password 인수

사용 예시
---------
python validate_bb_aod.py \\
    --bb-input  bb_l1c_20260220_025632_8band.tiff \\
    --bb-aod    bb_aod_output.tif \\
    --s2-aod    aod_final.tif \\
    --out-dir   ./validation \\
    --username  YOUR_EARTHDATA_USERNAME \\
    --password  YOUR_EARTHDATA_PASSWORD
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine, array_bounds
from rasterio.warp import reproject, Resampling
from pyproj import Transformer

# ---------------------------------------------------------------------------
# MODIS MAIAC 다운로드
# ---------------------------------------------------------------------------

def earthdata_login(username: Optional[str], password: Optional[str]):
    """earthaccess 로그인. 우선순위: 인수 → 환경변수 → .netrc → interactive."""
    import earthaccess

    if username and password:
        os.environ["EARTHDATA_USERNAME"] = username
        os.environ["EARTHDATA_PASSWORD"] = password

    for strategy in ("environment", "netrc"):
        try:
            auth = earthaccess.login(strategy=strategy)
            if auth.authenticated:
                print(f"NASA Earthdata login OK (strategy={strategy})")
                return auth
        except Exception:
            pass

    print("자동 로그인 실패 → 대화형 로그인 시도")
    return earthaccess.login(strategy="interactive", persist=True)


def download_maiac(date_str: str, bbox: Tuple[float, float, float, float],
                   out_dir: str,
                   username: Optional[str] = None,
                   password: Optional[str] = None) -> List[str]:
    """MCD19A2 (MAIAC) 단일 날짜 다운로드."""
    return download_maiac_range(date_str, date_str, bbox, out_dir, username, password)


def download_maiac_range(date_start: str, date_end: str,
                          bbox: Tuple[float, float, float, float],
                          out_dir: str,
                          username: Optional[str] = None,
                          password: Optional[str] = None) -> List[str]:
    """MCD19A2 (MAIAC) 날짜 범위 다운로드.

    Parameters
    ----------
    date_start / date_end : "YYYY-MM-DD"
    bbox     : (lon_min, lat_min, lon_max, lat_max)  WGS84
    out_dir  : 저장 디렉터리
    Returns  : 다운로드된 .hdf 파일 경로 리스트
    """
    import earthaccess

    os.makedirs(out_dir, exist_ok=True)
    earthdata_login(username, password)

    results = earthaccess.search_data(
        short_name="MCD19A2",
        version="061",
        temporal=(date_start, date_end),
        bounding_box=bbox,
    )
    if not results:
        raise RuntimeError(f"MAIAC 검색 결과 없음: {date_start}~{date_end}  bbox={bbox}")

    print(f"  MAIAC 검색: {len(results)} granule(s)  ({date_start} ~ {date_end})")
    files = earthaccess.download(results, local_path=out_dir)
    str_files = [str(f) for f in files]
    print(f"  다운로드 완료: {len(str_files)}개 파일")
    return str_files


def find_best_maiac_date(hdf_files: List[str],
                          focus_lat: float, focus_lon: float,
                          bbox: Tuple,
                          radius_deg: float = 0.10
                          ) -> Tuple[Optional[str], Optional[str], int]:
    """관심 지점 인근 유효 픽셀이 가장 많은 MAIAC 파일을 선택.

    Parameters
    ----------
    hdf_files   : HDF4 파일 경로 리스트
    focus_lat/lon : 관심 지점 (수원 경기도청 등)
    radius_deg  : 검색 반경 [도]  (0.10 ≈ 10km)

    Returns
    -------
    (best_hdf_path, date_str, n_pixels_near_focus)
    """
    import re as _re
    best_path: Optional[str] = None
    best_date: Optional[str] = None
    best_n = -1

    for hdf_path in sorted(hdf_files):
        m = _re.search(r"A(\d{7})", os.path.basename(str(hdf_path)))
        if not m:
            continue
        year = int(m.group(1)[:4])
        doy  = int(m.group(1)[4:])
        date_dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
        date_str = date_dt.strftime("%Y-%m-%d")

        try:
            lon_arr, lat_arr, aod_arr = read_maiac_aod(str(hdf_path), bbox)
            dist_sq = (lon_arr - focus_lon) ** 2 + (lat_arr - focus_lat) ** 2
            n_near = int((dist_sq <= radius_deg ** 2).sum())
            marker = " ★" if n_near > best_n else ""
            print(f"    {date_str}  {os.path.basename(str(hdf_path)[:40])} : "
                  f"전체={aod_arr.size:,}  Suwon 인근={n_near}{marker}")
            if n_near > best_n:
                best_n = n_near
                best_path = str(hdf_path)
                best_date = date_str
        except Exception as e:
            print(f"    {date_str}: 오류 → {e}")

    return best_path, best_date, best_n


# ---------------------------------------------------------------------------
# MODIS 사인 투영 (sinusoidal) 그리드 유틸
# ---------------------------------------------------------------------------

_R   = 6_371_007.181           # MODIS 구면 반지름 [m]
_T   = math.pi * _R / 18      # 타일 크기 = 1_111_950.5 m


def _tile_h_v_from_filename(hdf_path: str) -> Tuple[int, int]:
    """파일명에서 h, v 타일 번호 추출 (e.g. h28v05)."""
    name = os.path.basename(hdf_path)
    import re
    m = re.search(r"h(\d{2})v(\d{2})", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    raise ValueError(f"타일 번호를 파일명에서 읽을 수 없음: {name}")


def _maiac_pixel_lonlat(row: np.ndarray, col: np.ndarray,
                         h: int, v: int, nrows: int = 1200) -> Tuple[np.ndarray, np.ndarray]:
    """MAIAC 픽셀 (row, col) → (lon, lat) 변환 (sinusoidal → WGS84).

    pixel_size = _T / nrows  (약 926.625 m at 1 km)
    """
    ps = _T / nrows
    # 타일 좌상단 sinusoidal 좌표
    x_ul = (h - 18) * _T
    y_ul = (9 - v) * _T
    # 픽셀 중심
    x_c = x_ul + (col + 0.5) * ps
    y_c = y_ul - (row + 0.5) * ps

    lat_rad = y_c / _R
    lat = np.degrees(lat_rad)
    lon = np.degrees(x_c / (_R * np.cos(lat_rad)))
    return lon, lat


def read_maiac_aod(hdf_path: str,
                   bbox: Tuple[float, float, float, float],
                   sds_name: str = "Optical_Depth_055"
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MAIAC HDF4 파일에서 AOD 550 추출 (WGS84 lat/lon 배열 반환).

    Returns
    -------
    lon : 1D array  (유효 픽셀)
    lat : 1D array
    aod : 1D array  (음수/fill 제거)
    """
    from pyhdf.SD import SD, SDC

    lon_min, lat_min, lon_max, lat_max = bbox
    h, v = _tile_h_v_from_filename(hdf_path)
    nrows = 1200  # MCD19A2 1 km 해상도

    hdf = SD(str(hdf_path), SDC.READ)  # pyhdf는 str 필요 (Path 객체 불가)
    try:
        sds = hdf.select(sds_name)
        raw = sds[:].astype(np.float32)   # (n_time, nrows, nrows)
        attrs = sds.attributes()
    finally:
        hdf.end()

    scale  = attrs.get("scale_factor", 0.001)
    fill   = attrs.get("_FillValue",   -28672)

    # time 차원 처리: 모든 유효 관측값의 평균
    if raw.ndim == 3:
        raw_valid = raw.copy()
        raw_valid[raw_valid == fill] = np.nan
        aod_2d = np.nanmean(raw_valid * scale, axis=0).astype(np.float32)
    else:
        aod_2d = raw * scale
        aod_2d[aod_2d == fill * scale] = np.nan

    # 좌표 계산
    rr, cc = np.meshgrid(np.arange(nrows), np.arange(nrows), indexing="ij")
    lon_all, lat_all = _maiac_pixel_lonlat(rr, cc, h, v, nrows)

    # bbox 내부만 선택
    mask = (
        (lon_all >= lon_min) & (lon_all <= lon_max) &
        (lat_all >= lat_min) & (lat_all <= lat_max) &
        np.isfinite(aod_2d)
    )
    return lon_all[mask], lat_all[mask], aod_2d[mask]


def maiac_to_raster(lon: np.ndarray, lat: np.ndarray, aod: np.ndarray,
                    res_deg: float = 0.01) -> Tuple[np.ndarray, Affine]:
    """산점 MAIAC 데이터를 규칙 격자로 래스터화."""
    lon_min, lon_max = lon.min(), lon.max()
    lat_min, lat_max = lat.min(), lat.max()

    ncols = max(1, int(np.ceil((lon_max - lon_min) / res_deg))) + 1
    nrows = max(1, int(np.ceil((lat_max - lat_min) / res_deg))) + 1

    transform = Affine.translation(lon_min, lat_max) * Affine.scale(res_deg, -res_deg)

    grid = np.zeros((nrows, ncols), dtype=np.float64)   # NaN 아닌 0으로 초기화
    cnt  = np.zeros((nrows, ncols), dtype=np.int32)

    col_idx = np.clip(np.floor((lon - lon_min) / res_deg).astype(int), 0, ncols - 1)
    row_idx = np.clip(np.floor((lat_max - lat) / res_deg).astype(int), 0, nrows - 1)

    np.add.at(grid, (row_idx, col_idx), aod)
    np.add.at(cnt,  (row_idx, col_idx), 1)

    valid = cnt > 0
    out = np.full((nrows, ncols), np.nan, dtype=np.float32)
    out[valid] = (grid[valid] / cnt[valid]).astype(np.float32)
    return out, transform


# ---------------------------------------------------------------------------
# AOD 파일 로드 & 공통 격자로 재투영
# ---------------------------------------------------------------------------

def load_tif_aod(path: str) -> Tuple[np.ndarray, Affine, object]:
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        nd   = src.nodata
        if nd is not None:
            data[data == nd] = np.nan
        data[data < 0]  = np.nan
        data[data > 5]  = np.nan
        return data, src.transform, src.crs


def reproject_to_ref(src_data: np.ndarray, src_transform: Affine, src_crs,
                     ref_data: np.ndarray, ref_transform: Affine, ref_crs
                     ) -> np.ndarray:
    """src를 ref 격자로 재투영 (평균 리샘플링)."""
    dst = np.full_like(ref_data, np.nan, dtype=np.float32)
    reproject(
        source=src_data, destination=dst,
        src_transform=src_transform, src_crs=CRS.from_user_input(src_crs),
        dst_transform=ref_transform, dst_crs=CRS.from_user_input(ref_crs),
        src_nodata=np.nan, dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    return dst


def collocate(a: np.ndarray, b: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """두 동일 크기 배열에서 둘 다 유한한 픽셀만 추출."""
    both = np.isfinite(a) & np.isfinite(b)
    return a[both], b[both]


def sample_tif_at_points(tif_path: str, lon: np.ndarray, lat: np.ndarray,
                         agg_radius_px: int = 0) -> np.ndarray:
    """BB GeoTIFF에서 MAIAC 산점 (lon, lat) 위치 값을 직접 샘플링.

    중간 grid 단계 없이 MAIAC HDF의 raw 픽셀 위치를 BB 격자에 대응시킴.
    agg_radius_px>0이면 해당 반경 내 BB 픽셀 평균 (1km MAIAC 셀 ≈ ±20 BB 픽셀).
    """
    with rasterio.open(tif_path) as src:
        data = src.read(1).astype(np.float32)
        nd = src.nodata
        if nd is not None:
            data[data == nd] = np.nan
        data[data < 0] = np.nan
        data[data > 5] = np.nan
        tf = src.transform
        h, w = data.shape

    inv = ~tf
    cols = np.floor(inv.a * lon + inv.b * lat + inv.c).astype(int)
    rows = np.floor(inv.d * lon + inv.e * lat + inv.f).astype(int)
    out = np.full(len(lon), np.nan, dtype=np.float32)

    if agg_radius_px <= 0:
        ok = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        out[ok] = data[rows[ok], cols[ok]]
    else:
        rad = int(agg_radius_px)
        for i in range(len(lon)):
            r, c = rows[i], cols[i]
            if r - rad < 0 or r + rad >= h or c - rad < 0 or c + rad >= w:
                continue
            win = data[r - rad:r + rad + 1, c - rad:c + rad + 1]
            wv = win[np.isfinite(win)]
            if wv.size > 0:
                out[i] = wv.mean()
    return out


# ---------------------------------------------------------------------------
# 검증 통계
# ---------------------------------------------------------------------------

def compute_stats(ref: np.ndarray, pred: np.ndarray) -> dict:
    bias = float(np.mean(pred - ref))
    rmse = float(np.sqrt(np.mean((pred - ref) ** 2)))
    mae  = float(np.mean(np.abs(pred - ref)))
    if ref.std() > 0 and pred.std() > 0:
        r = float(np.corrcoef(ref, pred)[0, 1])
    else:
        r = float("nan")
    return dict(n=len(ref), bias=bias, rmse=rmse, mae=mae, r=r,
                ref_mean=float(ref.mean()), pred_mean=float(pred.mean()))


def print_stats(label: str, stats: dict):
    print(f"\n{'─'*50}")
    print(f"  {label}")
    print(f"{'─'*50}")
    print(f"  N          : {stats['n']:,}")
    print(f"  MAIAC mean : {stats['ref_mean']:.3f}")
    print(f"  Pred  mean : {stats['pred_mean']:.3f}")
    print(f"  Bias       : {stats['bias']:+.3f}")
    print(f"  RMSE       : {stats['rmse']:.3f}")
    print(f"  MAE        : {stats['mae']:.3f}")
    print(f"  R          : {stats['r']:.3f}")


# ---------------------------------------------------------------------------
# scatter plot
# ---------------------------------------------------------------------------

def save_scatter(ref: np.ndarray, pred: np.ndarray, label: str,
                 stats: dict, out_path: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(5, 5))
        ax.scatter(ref, pred, s=1, alpha=0.3, color="steelblue")
        lim = max(ref.max(), pred.max(), 0.1) * 1.1
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.plot([0, lim], [0, lim], "k--", lw=0.8)
        ax.set_xlabel("MAIAC AOD 550")
        ax.set_ylabel(f"{label} AOD 550")
        ax.set_title(f"{label} vs MAIAC\n"
                     f"N={stats['n']:,}  Bias={stats['bias']:+.3f}  "
                     f"RMSE={stats['rmse']:.3f}  R={stats['r']:.3f}")
        fig.tight_layout()
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"  Scatter plot → {out_path}")
    except ImportError:
        print("  (matplotlib 없음 — scatter 생략)")


# ---------------------------------------------------------------------------
# BlueBON radiance_scale 역산
# ---------------------------------------------------------------------------

def estimate_radiance_scale(
        input_tiff: str,
        maiac_lon: np.ndarray,
        maiac_lat: np.ndarray,
        maiac_aod: np.ndarray,
        current_scale: float,
        lut_aot: np.ndarray,
        lut_path: np.ndarray,
        solar_z: float,
        view_z: float = 0.0,
        surf_blue_red_ratio: float = 0.5,
) -> dict:
    """MAIAC AOD를 참조로 BlueBON radiance_scale 역산.

    원리
    ----
    현재 scale k_0 로 얻은 TOA 반사율이 전부 k_0 에 비례하므로:

        rho_true_blue  = rho_obs_blue  × (k / k_0)
        rho_true_red   = rho_obs_red   × (k / k_0)
        surf_blue_true = ratio × rho_true_red

    MAIAC AOD_i 에 해당하는 경로 반사율:
        rho_path_target_i = LUT(AOD_i)

    DDV 픽셀에서:
        rho_path_target = rho_true_blue - surf_blue_true × T(AOD_i)
                        = (rho_obs_blue - ratio × rho_obs_red × T) × k

    따라서:
        k_i = rho_path_target_i / (rho_obs_blue_i - ratio × rho_obs_red_i × T_i)
        k_best = median(k_i)  [이상치 제거 후]
    """
    from bb_aod_calval import (
        BB_BANDS, esun_at_nm, earth_sun_distance_au, solar_zenith_azimuth,
        parse_sensing_time, _TAU_RAY_490, _ANGSTROM,
    )

    sensing_time = parse_sensing_time(input_tiff)

    with rasterio.open(input_tiff) as src:
        h, w = src.height, src.width
        transform = src.transform
        crs = src.crs

        left, bottom, right, top = array_bounds(h, w, transform)
        lat_c = 0.5 * (bottom + top)
        lon_c = 0.5 * (left + right)
        sza, _ = solar_zenith_azimuth(sensing_time, lat_c, lon_c)
        d = earth_sun_distance_au(sensing_time)
        cos_sza = math.cos(math.radians(sza))

        def read_raw(bidx: int) -> np.ndarray:
            dn = src.read(bidx).astype(np.float64)
            dn[dn == 0] = np.nan
            return dn

        dn_blue = read_raw(BB_BANDS["BLUE"]["raster_band"])
        dn_red  = read_raw(BB_BANDS["RED"]["raster_band"])
        dn_nir  = read_raw(BB_BANDS["NIR"]["raster_band"])

    esun_b = esun_at_nm(BB_BANDS["BLUE"]["center_nm"])
    esun_r = esun_at_nm(BB_BANDS["RED"]["center_nm"])
    esun_n = esun_at_nm(BB_BANDS["NIR"]["center_nm"])

    # 현재 scale 기준 반사율
    c = math.pi * d**2 / cos_sza
    rho_blue = dn_blue * current_scale * c / esun_b
    rho_red  = dn_red  * current_scale * c / esun_r
    rho_nir  = dn_nir  * current_scale * c / esun_n

    ndvi = (rho_nir - rho_red) / (rho_nir + rho_red + 1e-9)

    # DDV 마스크 (현재 scale 기준)
    ddv = (ndvi >= 0.30) & (rho_red <= 0.20) & np.isfinite(rho_blue)

    # MAIAC 값을 픽셀 좌표로 매핑
    if crs and CRS.from_user_input(crs).is_geographic:
        tf = Transformer.from_crs("EPSG:4326", CRS.from_user_input(crs), always_xy=True)
    else:
        tf = Transformer.from_crs("EPSG:4326", CRS.from_user_input(crs), always_xy=True)

    mx, my = tf.transform(maiac_lon, maiac_lat)
    mc = np.round((mx - transform.c) / transform.a).astype(int)
    mr = np.round((my - transform.f) / transform.e).astype(int)

    valid_idx = (mr >= 0) & (mr < h) & (mc >= 0) & (mc < w)
    mr, mc = mr[valid_idx], mc[valid_idx]
    m_aod = maiac_aod[valid_idx]

    # 각 MAIAC 픽셀에서 DDV 여부 확인 + 역산
    mu_s = max(math.cos(math.radians(solar_z)), 0.01)
    mu_v = max(math.cos(math.radians(view_z)),  0.01)

    k_vals = []
    for i in range(len(mr)):
        r_i, c_i = mr[i], mc[i]
        if not ddv[r_i, c_i]:
            continue
        if not np.isfinite(m_aod[i]) or m_aod[i] < 0:
            continue

        rho_path_target = float(np.interp(m_aod[i], lut_aot, lut_path))
        obs_b = float(dn_blue[r_i, c_i])
        obs_r = float(dn_red[r_i, c_i])
        if not (np.isfinite(obs_b) and np.isfinite(obs_r) and obs_b > 0):
            continue

        # 전달 계수 (MAIAC AOD 기준)
        tau_aero = m_aod[i] * (490.0 / 550.0) ** _ANGSTROM
        tau_tot  = _TAU_RAY_490 + tau_aero
        T = math.exp(-tau_tot * (1.0 / mu_s + 1.0 / mu_v))

        # k = rho_path_target / (obs_b_factor - ratio × obs_r_factor × T)
        # obs_factor = current_scale × c / esun
        obs_b_unit = obs_b * c / esun_b   # = rho_blue / current_scale
        obs_r_unit = obs_r * c / esun_r

        denom = obs_b_unit - surf_blue_red_ratio * obs_r_unit * T
        if denom < 1e-6:
            continue

        k = rho_path_target / denom
        if 0.001 < k < 100:
            k_vals.append(k)

    if not k_vals:
        return {"status": "no_valid_ddv_maiac_overlap",
                "n_matched": 0, "suggested_scale": current_scale}

    k_arr = np.array(k_vals)
    k_med = float(np.median(k_arr))
    k_p25 = float(np.percentile(k_arr, 25))
    k_p75 = float(np.percentile(k_arr, 75))
    suggested = current_scale * k_med

    return {
        "status": "ok",
        "n_matched": len(k_arr),
        "k_median": k_med,
        "k_iqr": (k_p25, k_p75),
        "current_scale": current_scale,
        "suggested_scale": suggested,
        "solar_z": solar_z,
    }


# ---------------------------------------------------------------------------
# surf_blue_red_ratio 역산
# ---------------------------------------------------------------------------

def estimate_surf_ratio(
        input_tiff: str,
        maiac_lon: np.ndarray,
        maiac_lat: np.ndarray,
        maiac_aod: np.ndarray,
        radiance_scale: float,
        lut_aot: np.ndarray,
        lut_path: np.ndarray,
        solar_z: float,
        view_z: float = 0.0,
) -> dict:
    """MAIAC AOD에서 best-fit surf_blue_red_ratio 추정.

    rho_blue_toa = rho_path(AOD) + ratio × rho_red × T(AOD)
    → ratio = (rho_blue_toa - rho_path) / (rho_red × T)
    """
    from bb_aod_calval import (
        BB_BANDS, esun_at_nm, earth_sun_distance_au, solar_zenith_azimuth,
        parse_sensing_time, _TAU_RAY_490, _ANGSTROM,
    )

    sensing_time = parse_sensing_time(input_tiff)

    with rasterio.open(input_tiff) as src:
        h, w = src.height, src.width
        transform = src.transform
        crs = src.crs
        left, bottom, right, top = array_bounds(h, w, transform)
        lat_c = 0.5 * (bottom + top)
        lon_c = 0.5 * (left + right)
        sza, _ = solar_zenith_azimuth(sensing_time, lat_c, lon_c)
        d = earth_sun_distance_au(sensing_time)
        cos_sza = math.cos(math.radians(sza))

        def read_rho(bidx: int, esun: float) -> np.ndarray:
            dn = src.read(bidx).astype(np.float64)
            dn[dn == 0] = np.nan
            return np.clip(math.pi * dn * radiance_scale * d**2 / (esun * cos_sza), 0, 1.5)

        rho_blue = read_rho(BB_BANDS["BLUE"]["raster_band"], esun_at_nm(490))
        rho_red  = read_rho(BB_BANDS["RED"]["raster_band"],  esun_at_nm(665))
        rho_nir  = read_rho(BB_BANDS["NIR"]["raster_band"],  esun_at_nm(842))

    ndvi = (rho_nir - rho_red) / (rho_nir + rho_red + 1e-9)
    ddv  = (ndvi >= 0.30) & (rho_red <= 0.20) & np.isfinite(rho_blue)

    tf_crs = CRS.from_user_input(crs) if crs else CRS.from_epsg(4326)
    tf = Transformer.from_crs("EPSG:4326", tf_crs, always_xy=True)
    mx, my = tf.transform(maiac_lon, maiac_lat)
    mc = np.round((mx - transform.c) / transform.a).astype(int)
    mr = np.round((my - transform.f) / transform.e).astype(int)

    valid_idx = (mr >= 0) & (mr < h) & (mc >= 0) & (mc < w)
    mr, mc, m_aod = mr[valid_idx], mc[valid_idx], maiac_aod[valid_idx]

    mu_s = max(math.cos(math.radians(solar_z)), 0.01)
    mu_v = max(math.cos(math.radians(view_z)),  0.01)

    ratio_vals = []
    for i in range(len(mr)):
        r_i, c_i = mr[i], mc[i]
        if not ddv[r_i, c_i]:
            continue
        if not np.isfinite(m_aod[i]) or m_aod[i] < 0:
            continue

        rho_path = float(np.interp(m_aod[i], lut_aot, lut_path))
        tau_aero = m_aod[i] * (490.0 / 550.0) ** _ANGSTROM
        T = math.exp(-(_TAU_RAY_490 + tau_aero) * (1.0 / mu_s + 1.0 / mu_v))

        b = float(rho_blue[r_i, c_i])
        r = float(rho_red[r_i, c_i])
        denom = r * T
        if denom < 1e-5 or not np.isfinite(b):
            continue

        ratio = (b - rho_path) / denom
        if 0.0 < ratio < 1.5:
            ratio_vals.append(ratio)

    if not ratio_vals:
        return {"status": "no_data", "suggested_ratio": 0.5}

    arr = np.array(ratio_vals)
    return {
        "status": "ok",
        "n": len(arr),
        "ratio_median": float(np.median(arr)),
        "ratio_p25": float(np.percentile(arr, 25)),
        "ratio_p75": float(np.percentile(arr, 75)),
        "suggested_ratio": float(np.clip(np.median(arr), 0.2, 1.0)),
    }


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="BlueBON/S2 AOD vs MAIAC 검증")
    p.add_argument("--bb-input",  required=True, help="bb_l1c_*_8band.tiff (원본)")
    p.add_argument("--bb-aod",    required=True, help="bb_aod_output.tif")
    p.add_argument("--s2-aod",    default=None,  help="aod_final.tif (S2, 날짜 다름)")
    p.add_argument("--out-dir",   default="./validation")
    p.add_argument("--username",  default=None)
    p.add_argument("--password",  default=None)
    p.add_argument("--current-scale", type=float, default=0.3,
                   help="현재 사용된 radiance_scale")
    p.add_argument("--no-download", action="store_true",
                   help="이미 다운로드된 .hdf 파일 사용 (out-dir 에서 검색)")
    # 관심 지점 — 수원 경기도청 (기본값)
    p.add_argument("--focus-lat", type=float, default=37.2753,
                   help="검증 관심 지점 위도  (기본: 수원 경기도청 37.2753°N)")
    p.add_argument("--focus-lon", type=float, default=127.0090,
                   help="검증 관심 지점 경도  (기본: 수원 경기도청 127.009°E)")
    p.add_argument("--focus-radius-deg", type=float, default=0.10,
                   help="관심 지점 검색 반경 [도]  (기본: 0.10 ≈ 10 km)")
    p.add_argument("--search-days", type=int, default=7,
                   help="BlueBON 날짜 기준 ±N일 MAIAC 탐색  (기본: 7)")
    return p.parse_args()


def main():
    args = parse_args()
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    # --- BlueBON 입력 bbox ---
    with rasterio.open(args.bb_input) as src:
        h_bb, w_bb = src.height, src.width
        tf_bb = src.transform
        crs_bb = src.crs
        left, bottom, right, top = array_bounds(h_bb, w_bb, tf_bb)

    if crs_bb and not CRS.from_user_input(crs_bb).is_geographic:
        t = Transformer.from_crs(CRS.from_user_input(crs_bb), "EPSG:4326", always_xy=True)
        lon_min, lat_min = t.transform(left, bottom)
        lon_max, lat_max = t.transform(right, top)
    else:
        lon_min, lon_max = left, right
        lat_min, lat_max = bottom, top

    bbox = (lon_min - 0.1, lat_min - 0.1, lon_max + 0.1, lat_max + 0.1)
    print(f"BlueBON scene bbox: {bbox}")

    # --- BlueBON 날짜 ---
    import re
    m = re.search(r"(\d{8})_(\d{6})", args.bb_input)
    bb_date = m.group(1)[:4] + "-" + m.group(1)[4:6] + "-" + m.group(1)[6:8]
    bb_dt   = datetime.strptime(bb_date, "%Y-%m-%d")
    print(f"BlueBON date: {bb_date}")

    # 검색 날짜 범위: ±search_days
    search_start = (bb_dt - timedelta(days=args.search_days)).strftime("%Y-%m-%d")
    search_end   = (bb_dt + timedelta(days=args.search_days)).strftime("%Y-%m-%d")

    # --- MAIAC 다운로드 또는 기존 파일 사용 ---
    all_hdf: List[str] = []
    if args.no_download:
        all_hdf = sorted([str(f) for f in Path(out_dir).glob("MCD19A2*.hdf")])
        if not all_hdf:
            print("--no-download 지정했지만 .hdf 파일 없음 → 다운로드 시도")
            args.no_download = False

    if not args.no_download:
        print(f"\n[1] MAIAC 다운로드: {search_start} ~ {search_end}")
        try:
            all_hdf = download_maiac_range(
                search_start, search_end, bbox, out_dir,
                args.username, args.password,
            )
        except Exception as e:
            print(f"  MAIAC 다운로드 실패: {e}")
            sys.exit(1)

    # --- BlueBON 동일 날짜 MAIAC 우선 선택 ---
    print(f"\n[1b] BlueBON 동일 날짜({bb_date}) MAIAC 우선 선택")
    bb_doy_tag = f"A{bb_dt.strftime('%Y%j')}"
    same_date_hdfs = [hf for hf in all_hdf if bb_doy_tag in os.path.basename(str(hf))]
    best_hdf, best_date, best_n = None, None, 0
    if same_date_hdfs:
        # 동일 날짜 HDF 중 유효 픽셀 가장 많은 tile 선택
        for hf in same_date_hdfs:
            try:
                _, _, _aod = read_maiac_aod(str(hf), bbox)
                if _aod.size > best_n:
                    best_hdf, best_date, best_n = hf, bb_date, _aod.size
            except Exception:
                pass
        print(f"  동일 날짜 HDF: {len(same_date_hdfs)}개, 최대 픽셀={best_n:,}")

    if best_hdf is None or best_n == 0:
        # 동일 날짜 픽셀 없을 때만 fallback (Suwon 인근 최적 날짜)
        print(f"  동일 날짜 유효 픽셀 없음 → 수원 인근 최적 날짜 fallback")
        print(f"     관심 지점: {args.focus_lat:.4f}°N  {args.focus_lon:.4f}°E  "
              f"반경={args.focus_radius_deg:.2f}°")
        best_hdf, best_date, best_n = find_best_maiac_date(
            all_hdf,
            focus_lat=args.focus_lat,
            focus_lon=args.focus_lon,
            bbox=bbox,
            radius_deg=args.focus_radius_deg,
        )

    day_gap = abs((datetime.strptime(best_date, "%Y-%m-%d") - bb_dt).days) if best_date else 0
    print(f"\n  ★ 선택 날짜  : {best_date}  (Suwon 인근 {best_n}픽셀, "
          f"BlueBON과 {day_gap}일 차이)")

    # --- MAIAC AOD 추출 (선택된 날짜) ---
    print(f"\n[2] MAIAC AOD 추출 ({best_date})")
    lon_m, lat_m, aod_m = np.array([]), np.array([]), np.array([])
    try:
        lon_m, lat_m, aod_m = read_maiac_aod(best_hdf, bbox)
    except Exception as e:
        print(f"  {os.path.basename(best_hdf)}: {e}")

    if aod_m.size == 0:
        print("  유효한 MAIAC 픽셀 없음!")
        sys.exit(1)

    print(f"  MAIAC 유효 픽셀: {aod_m.size:,}")
    print(f"  MAIAC AOD 통계: mean={aod_m.mean():.3f}  "
          f"median={np.median(aod_m):.3f}  std={aod_m.std():.3f}  "
          f"range=[{aod_m.min():.3f},{aod_m.max():.3f}]")

    # 수원 인근 MAIAC 통계 별도 출력
    dist_sq = (lon_m - args.focus_lon)**2 + (lat_m - args.focus_lat)**2
    near_mask = dist_sq <= args.focus_radius_deg**2
    if near_mask.any():
        aod_near = aod_m[near_mask]
        print(f"  Suwon 인근 MAIAC ({near_mask.sum()}픽셀): "
              f"mean={aod_near.mean():.3f}  median={np.median(aod_near):.3f}")
    else:
        print(f"  Suwon 인근 MAIAC 픽셀 없음")

    # MAIAC 래스터화 (0.01° ≈ 1 km)
    maiac_grid, maiac_tf = maiac_to_raster(lon_m, lat_m, aod_m, res_deg=0.01)
    maiac_crs = CRS.from_epsg(4326)

    # MAIAC GeoTIFF 저장
    maiac_out = os.path.join(out_dir, f"maiac_aod_{best_date}.tif")
    profile = dict(driver="GTiff", height=maiac_grid.shape[0],
                   width=maiac_grid.shape[1], count=1, dtype="float32",
                   crs=maiac_crs, transform=maiac_tf, nodata=np.nan,
                   compress="deflate")
    with rasterio.open(maiac_out, "w", **profile) as dst:
        dst.write(maiac_grid.astype(np.float32), 1)
    print(f"  MAIAC GeoTIFF → {maiac_out}")

    # --- BlueBON AOD를 MAIAC HDF 산점 위치에서 직접 샘플링 ---
    # (중간 0.01° grid 거치지 않고 raw MAIAC 픽셀 위치마다 BB 값 추출)
    maiac_label = best_date if best_date else bb_date
    day_note = f"  (MAIAC {best_date}, BlueBON {bb_date}, {day_gap}일 차이)" if day_gap > 0 else ""
    print(f"\n[3] BlueBON vs MAIAC ({maiac_label}){day_note}  [HDF 산점 직접 매칭]")
    # 1km MAIAC 셀당 BB 평균 (BB ~25 m → ±20 px ≈ ±500 m)
    bb_at_maiac = sample_tif_at_points(args.bb_aod, lon_m, lat_m, agg_radius_px=20)
    valid_pair = np.isfinite(bb_at_maiac) & np.isfinite(aod_m)
    print(f"  매칭 산점: {int(valid_pair.sum()):,} / {aod_m.size:,} (MAIAC 픽셀 중 BB swath 내)")
    if valid_pair.sum() > 0:
        ref_bb, pred_bb = aod_m[valid_pair], bb_at_maiac[valid_pair]
        stats_bb = compute_stats(ref_bb, pred_bb)
        print_stats(f"BlueBON (scale={args.current_scale}) vs MAIAC ({maiac_label})", stats_bb)
        save_scatter(ref_bb, pred_bb, "BlueBON",
                     stats_bb, os.path.join(out_dir, "scatter_bb_vs_maiac.png"))
    else:
        stats_bb = None
        print("  매칭 픽셀 없음")

    # --- S2 AOD (날짜 다름 주의) ---
    if args.s2_aod and os.path.exists(args.s2_aod):
        print(f"\n[4] S2 vs MAIAC ({maiac_label}) — 참고용 [HDF 산점 직접 매칭]")
        s2_at_maiac = sample_tif_at_points(args.s2_aod, lon_m, lat_m, agg_radius_px=20)
        valid_pair_s2 = np.isfinite(s2_at_maiac) & np.isfinite(aod_m)
        print(f"  매칭 산점: {int(valid_pair_s2.sum()):,}")
        if valid_pair_s2.sum() > 0:
            ref_s2, pred_s2 = aod_m[valid_pair_s2], s2_at_maiac[valid_pair_s2]
            stats_s2 = compute_stats(ref_s2, pred_s2)
            print_stats(f"S2 vs MAIAC ({maiac_label})", stats_s2)
            save_scatter(ref_s2, pred_s2, "S2",
                         stats_s2, os.path.join(out_dir, "scatter_s2_vs_maiac.png"))

    # --- radiance_scale 역산 (scene-wide) ---
    # ★ 보정은 반드시 블루본과 동일 날짜 MAIAC 사용 (날짜 차이 있을 경우 대기 조건 달라 왜곡)
    print(f"\n[5] BlueBON radiance_scale 역산 (MAIAC scene-wide 보정 — 동일 날짜 {bb_date})")
    lut_aot  = np.array([0.01, 0.05, 0.10, 0.20, 0.30, 0.50, 0.80, 1.20, 2.00])
    lut_path = np.array([0.065, 0.069, 0.073, 0.081, 0.089, 0.106, 0.129, 0.155, 0.193])
    solar_z  = 49.76   # Feb 20, Seoul

    # 동일 날짜 MAIAC 로드 (calibration 전용)
    import re as _re2
    calib_lon: np.ndarray = np.array([])
    calib_lat: np.ndarray = np.array([])
    calib_aod: np.ndarray = np.array([])
    bb_doy = bb_dt.strftime("%Y%j")  # e.g. "2026051"
    for hf in all_hdf:
        if f"A{bb_doy}" in os.path.basename(str(hf)):
            try:
                cl, cla, ca = read_maiac_aod(str(hf), bbox)
                calib_lon = np.concatenate([calib_lon, cl])
                calib_lat = np.concatenate([calib_lat, cla])
                calib_aod = np.concatenate([calib_aod, ca])
            except Exception:
                pass

    if calib_aod.size == 0:
        print(f"  동일 날짜({bb_date}) MAIAC 없음 → 선택 날짜({best_date}) MAIAC로 대체 (참고용)")
        calib_lon, calib_lat, calib_aod = lon_m, lat_m, aod_m
        calib_is_sameday = False
    else:
        print(f"  동일 날짜 MAIAC: {calib_aod.size:,}픽셀  "
              f"AOD mean={calib_aod.mean():.3f}  median={np.median(calib_aod):.3f}")
        calib_is_sameday = True

    # DDV 픽셀 반사율 계산
    print(f"  DDV 반사율 통계 계산 중 (이미지 로드) …")
    from bb_aod_calval import (
        BB_BANDS, esun_at_nm, earth_sun_distance_au,
        solar_zenith_azimuth, parse_sensing_time,
    )
    sensing_time = parse_sensing_time(args.bb_input)
    with rasterio.open(args.bb_input) as src:
        h_in, w_in = src.height, src.width
        tf_in = src.transform
        d_au = earth_sun_distance_au(sensing_time)
        lat_c2 = 0.5 * (src.bounds.bottom + src.bounds.top)
        lon_c2 = 0.5 * (src.bounds.left  + src.bounds.right)
        sza2, _ = solar_zenith_azimuth(sensing_time, lat_c2, lon_c2)
        cos_sza2 = math.cos(math.radians(sza2))
        c_fac = math.pi * d_au**2 / cos_sza2

        def _rho(bidx, esun):
            dn = src.read(bidx).astype(np.float32)
            dn[dn == 0] = np.nan
            return np.clip(dn * args.current_scale * c_fac / esun, 0, 1.5)

        rb = _rho(BB_BANDS["BLUE"]["raster_band"], esun_at_nm(490))
        rr = _rho(BB_BANDS["RED"]["raster_band"],  esun_at_nm(665))
        rn = _rho(BB_BANDS["NIR"]["raster_band"],  esun_at_nm(842))

    ndvi_in = (rn - rr) / (rn + rr + 1e-9)
    ddv_in  = (ndvi_in >= 0.25) & (rr <= 0.15) & np.isfinite(rb)

    ratio_base = 0.40
    frac = np.clip((ndvi_in - 0.25) / 0.35, 0.0, 1.0)
    ratio_map = ratio_base * (0.6 + 0.4 * frac)
    surf_b = ratio_map * rr

    # 픽셀-by-픽셀 매칭: 날짜 차이가 0일 때만 유효
    if calib_is_sameday:
        scale_result = estimate_radiance_scale(
            args.bb_input, calib_lon, calib_lat, calib_aod,
            current_scale=args.current_scale,
            lut_aot=lut_aot, lut_path=lut_path,
            solar_z=solar_z,
        )
        print(f"  픽셀-by-픽셀 MAIAC-DDV 매칭: {scale_result['n_matched']:,}")
    else:
        scale_result = {"status": "skipped", "n_matched": 0}
        print(f"  픽셀-by-픽셀 매칭 생략 (날짜 불일치 — 결과 왜곡 가능)")

    # Scene-wide 보정 (동일 날짜 MAIAC 기준)
    calib_median = float(np.median(calib_aod))
    calib_mean   = float(np.mean(calib_aod))
    path_target  = float(np.interp(calib_median, lut_aot, lut_path))

    _TAU_RAY_490 = 0.133
    _ANGSTROM = 1.3
    mu_s_scene = max(math.cos(math.radians(solar_z)), 0.01)
    tau_aero_490 = calib_median * (490.0 / 550.0) ** _ANGSTROM
    tau_tot_490  = _TAU_RAY_490 + tau_aero_490
    T_maiac = math.exp(-tau_tot_490 * (1.0 / mu_s_scene + 1.0))

    path_ddv = (rb - surf_b * T_maiac)[ddv_in]
    path_ddv = path_ddv[np.isfinite(path_ddv)]

    if path_ddv.size > 0:
        path_obs = float(np.median(path_ddv))
        path_obs = max(path_obs, 1e-4)
        k_scene  = path_target / path_obs
        sugg_scale_scene = args.current_scale * k_scene
        calib_tag = bb_date if calib_is_sameday else f"{best_date} (날짜 불일치)"
        print(f"\n  [Scene-wide 보정]  MAIAC 기준일: {calib_tag}")
        print(f"  DDV 픽셀 수          : {ddv_in.sum():,}")
        print(f"  T(MAIAC AOD={calib_median:.3f}) : {T_maiac:.4f}  (2-way transmittance at 490nm)")
        print(f"  path_reflectance obs : {path_obs:.4f}  (median, blue - surf×T, scale={args.current_scale})")
        print(f"  path_reflectance tgt : {path_target:.4f}  (LUT 보간, MAIAC AOD={calib_median:.3f})")
        print(f"  scale 보정 계수 k    : {k_scene:.3f}")
        print(f"  현재 radiance_scale  : {args.current_scale}")
        print(f"  권장 radiance_scale  : {sugg_scale_scene:.4f}")
    else:
        sugg_scale_scene = args.current_scale
        calib_mean = float(np.mean(aod_m))
        print("  DDV 픽셀 없음 → scene-wide 보정 불가")

    # 픽셀 매칭 성공 + 동일 날짜 + k 물리적 범위(0.5~2.0) 내에서만 우선 사용
    if (calib_is_sameday
            and scale_result.get("status") == "ok"
            and scale_result["n_matched"] > 10
            and 0.5 < scale_result["k_median"] < 2.0):
        print(f"\n  [픽셀-by-픽셀 보정 (우선)]")
        print(f"  k_median={scale_result['k_median']:.3f}  "
              f"IQR={scale_result['k_iqr'][0]:.3f}–{scale_result['k_iqr'][1]:.3f}")
        sugg_scale = scale_result["suggested_scale"]
    else:
        sugg_scale = sugg_scale_scene

    # --- surf_blue_red_ratio 역산 ---
    print(f"\n[6] surf_blue_red_ratio 역산")
    ratio_result = estimate_surf_ratio(
        args.bb_input, lon_m, lat_m, aod_m,
        radiance_scale=sugg_scale,
        lut_aot=lut_aot, lut_path=lut_path,
        solar_z=solar_z,
    )
    if ratio_result["status"] == "ok" and ratio_result["n"] > 0:
        print(f"  매칭 픽셀: {ratio_result['n']:,}")
        print(f"  blue/red 비율 중앙값: {ratio_result['ratio_median']:.3f}  "
              f"(IQR {ratio_result['ratio_p25']:.3f}–{ratio_result['ratio_p75']:.3f})")
        print(f"  권장  surf-blue-red-ratio: {ratio_result['suggested_ratio']:.3f}")
        sugg_ratio = ratio_result["suggested_ratio"]
    else:
        print("  픽셀 매칭 없음 → ratio 유지")
        sugg_ratio = 0.40

    print(f"\n{'='*60}")
    print("권장 재실행 명령:")
    print(f"  python bb_aod_calval.py \\")
    print(f"    --input  {args.bb_input} \\")
    print(f"    --out    bb_aod_calibrated.tif \\")
    print(f"    --out-qa bb_aod_calibrated_qa.tif \\")
    print(f"    --radiance-scale {sugg_scale:.4f} \\")
    print(f"    --surf-blue-red-ratio {sugg_ratio:.3f} \\")
    print(f"    --ndvi-min 0.25 \\")
    print(f"    --red-dark-max 0.15 \\")
    print(f"    --maiac-aod-mean {calib_mean:.4f}")
    if not calib_is_sameday:
        print(f"  ⚠ MAIAC 동일 날짜({bb_date}) 데이터가 없어 선택 날짜({best_date}) 평균을 사용했습니다.")
        print(f"     기상 조건이 다를 수 있으니 권장값은 참고만 하세요.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
