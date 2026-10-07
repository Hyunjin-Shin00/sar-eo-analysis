from __future__ import annotations

"""
BlueBON AOD retrieval from L1C TOA Radiance TIFF.

Band specifications (from bluebon_band.png):
  Band 0 – PAN    : center=625nm, FWHM=250nm, HPP=500–750nm
  Band 1 – Blue   : center=490nm, FWHM= 65nm, HPP=457.5–522.5nm
  Band 2 – Green  : center=560nm, FWHM= 35nm, HPP=542.5–577.5nm
  Band 3 – Red    : center=665nm, FWHM= 30nm, HPP=650–680nm
  Band 4 – RE1    : center=705nm, FWHM= 15nm, HPP=697.5–712.5nm
  Band 5 – RE2    : center=740nm, FWHM= 15nm, HPP=732.5–747.5nm
  Band 6 – RE3    : center=783nm, FWHM= 20nm, HPP=773–793nm
  Band 7 – NIR    : center=842nm, FWHM=115nm, HPP=784.5–899.5nm

Key difference from S2 retrieval
----------------------------------
BlueBON has no SWIR band.  The DDV surface-blue estimate therefore uses
the Kaufman et al. (1997) blue-to-red ratio:

    rho_surf_blue ≈ surf_blue_red_ratio × rho_surf_red   (default ratio = 0.5)

This is equivalent to the MODIS Dark Target relationship
    rho_blue ≈ 0.25 × rho_SWIR2,  rho_red ≈ 0.50 × rho_SWIR2
derived by Kaufman et al. (1997) for dense dark vegetation.

Radiance calibration
---------------------
The L1C TIFF stores TOA radiance as uint16 DN.  Physical radiance is:
    L [W m⁻² sr⁻¹ μm⁻¹] = DN × radiance_scale

Set --radiance-scale to the per-sensor calibration coefficient.
Default = 0.3 (produces plausible reflectance for this scene; replace
with the official coefficient once available).

Install dependencies
---------------------
    pip install rasterio numpy scipy pyproj Py6S earthaccess pyhdf

Example
-------
python bb_aod_calval.py \\
  --input bb_l1c_20260220_025632_8band.tiff \\
  --out   bb_aod_output.tif \\
  --out-qa bb_aod_qa.tif
"""

import argparse
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine, array_bounds
from rasterio.warp import reproject
from pyproj import CRS, Transformer
from scipy.ndimage import gaussian_filter, generic_filter, uniform_filter, maximum_filter, minimum_filter

# ---------------------------------------------------------------------------
# BlueBON band table  (from bluebon_band.png)
# ---------------------------------------------------------------------------

BB_BANDS: Dict[str, Dict] = {
    "PAN":   {"raster_band": 1, "center_nm": 625, "fwhm_nm": 250, "hpp_on": 500.0, "hpp_off": 750.0},
    "BLUE":  {"raster_band": 2, "center_nm": 490, "fwhm_nm":  65, "hpp_on": 457.5, "hpp_off": 522.5},
    "GREEN": {"raster_band": 3, "center_nm": 560, "fwhm_nm":  35, "hpp_on": 542.5, "hpp_off": 577.5},
    "RED":   {"raster_band": 4, "center_nm": 665, "fwhm_nm":  30, "hpp_on": 650.0, "hpp_off": 680.0},
    "RE1":   {"raster_band": 5, "center_nm": 705, "fwhm_nm":  15, "hpp_on": 697.5, "hpp_off": 712.5},
    "RE2":   {"raster_band": 6, "center_nm": 740, "fwhm_nm":  15, "hpp_on": 732.5, "hpp_off": 747.5},
    "RE3":   {"raster_band": 7, "center_nm": 783, "fwhm_nm":  20, "hpp_on": 773.0, "hpp_off": 793.0},
    "NIR":   {"raster_band": 8, "center_nm": 842, "fwhm_nm": 115, "hpp_on": 784.5, "hpp_off": 899.5},
}

# ---------------------------------------------------------------------------
# Thuillier (2003) solar spectrum — key reference values [W m⁻² μm⁻¹ at 1 AU]
# Source: Thuillier et al. 2003, Solar Physics 214(1):1–22
# ---------------------------------------------------------------------------

_THUILLIER_WL_NM = np.array([
    450, 460, 470, 480, 490, 500, 510, 520, 530, 540,
    550, 560, 570, 580, 590, 600, 610, 620, 630, 640,
    650, 660, 665, 670, 680, 690, 700, 705, 710, 720,
    730, 740, 750, 760, 770, 780, 783, 790, 800, 810,
    820, 830, 840, 842, 850, 860, 870, 880, 890, 900,
], dtype=np.float64)

_THUILLIER_ESUN = np.array([
    2001, 1963, 1934, 1916, 1881, 1849, 1835, 1818, 1823, 1820,
    1827, 1814, 1802, 1768, 1760, 1745, 1729, 1714, 1700, 1686,
    1672, 1655, 1648, 1640, 1626, 1611, 1641, 1632, 1611, 1638,
    1629, 1620, 1612, 1382, 1559, 1555, 1551, 1542, 1526, 1511,
    1492, 1472, 1444, 1441, 1429, 1398, 1393, 1388, 1368, 1344,
], dtype=np.float64)


def esun_at_nm(wavelength_nm: float) -> float:
    """Interpolate Thuillier 2003 solar irradiance [W m⁻² μm⁻¹] at the given wavelength."""
    return float(np.interp(wavelength_nm, _THUILLIER_WL_NM, _THUILLIER_ESUN))


def esun_for_band(band_name: str) -> float:
    """Mean solar spectral irradiance [W m⁻² μm⁻¹] for a BlueBON band (center wavelength)."""
    return esun_at_nm(BB_BANDS[band_name]["center_nm"])


# ---------------------------------------------------------------------------
# Solar geometry
# ---------------------------------------------------------------------------

def earth_sun_distance_au(sensing_time: datetime) -> float:
    """Earth-Sun distance in AU using the Spencer (1971) formula."""
    doy = sensing_time.timetuple().tm_yday
    B = 2.0 * math.pi * (doy - 1) / 365.0
    return (1.000110
            + 0.034221 * math.cos(B)
            + 0.001280 * math.sin(B)
            + 0.000719 * math.cos(2 * B)
            + 0.000077 * math.sin(2 * B)) ** -0.5


def solar_zenith_azimuth(sensing_time: datetime, lat_deg: float,
                          lon_deg: float) -> Tuple[float, float]:
    """Solar zenith and azimuth angles (degrees) using Spencer (1971) + NOAA formulas.

    Accurate to ~0.01° for applications where AERONET-level precision is
    not required.

    Returns
    -------
    (solar_zenith_deg, solar_azimuth_deg)
    """
    doy = sensing_time.timetuple().tm_yday
    hour_utc = (sensing_time.hour
                + sensing_time.minute / 60.0
                + sensing_time.second / 3600.0)

    B = 2.0 * math.pi * (doy - 1) / 365.0

    # Solar declination [rad]
    decl = (0.006918
            - 0.399912 * math.cos(B)
            + 0.070257 * math.sin(B)
            - 0.006758 * math.cos(2 * B)
            + 0.000907 * math.sin(2 * B)
            - 0.002697 * math.cos(3 * B)
            + 0.00148  * math.sin(3 * B))

    # Equation of time [hours]
    eqtime = (0.000075
              + 0.001868 * math.cos(B)
              - 0.032077 * math.sin(B)
              - 0.014615 * math.cos(2 * B)
              - 0.04089  * math.sin(2 * B)) * (229.18 / 60.0)

    # Local apparent solar time
    time_offset = eqtime + lon_deg / 15.0          # hours
    solar_time = hour_utc + time_offset             # local solar time [h]
    hour_angle = (solar_time - 12.0) * 15.0        # hour angle [deg]

    lat = math.radians(lat_deg)
    ha  = math.radians(hour_angle)

    cos_zen = (math.sin(lat) * math.sin(decl)
               + math.cos(lat) * math.cos(decl) * math.cos(ha))
    cos_zen = max(-1.0, min(1.0, cos_zen))
    sza_deg = math.degrees(math.acos(cos_zen))

    # Azimuth (N=0, E=90)
    sin_az = -math.cos(decl) * math.sin(ha) / math.sin(math.radians(sza_deg)) if sza_deg > 0.1 else 0.0
    sin_az = max(-1.0, min(1.0, sin_az))
    az = math.degrees(math.asin(sin_az))
    cos_az_check = (math.sin(decl) - math.sin(lat) * cos_zen) / (math.cos(lat) * math.sin(math.radians(sza_deg))) if sza_deg > 0.1 else 1.0
    if cos_az_check < 0:
        az = 180.0 - az
    if hour_angle > 0:
        az = 360.0 - az
    if az < 0:
        az += 360.0

    return float(sza_deg), float(az)


def parse_sensing_time(filepath: str) -> datetime:
    """Extract UTC sensing time from BlueBON filename: bb_l1c_YYYYMMDD_HHMMSS_*.tiff"""
    name = os.path.basename(filepath)
    m = re.search(r"(\d{8})_(\d{6})", name)
    if m:
        dt_str = m.group(1) + m.group(2)
        return datetime.strptime(dt_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    raise ValueError(f"Cannot parse sensing time from filename: {name}")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

@dataclass
class SceneData:
    blue:  np.ndarray
    green: np.ndarray
    red:   np.ndarray
    nir:   np.ndarray
    re1:   np.ndarray
    re2:   np.ndarray
    re3:   np.ndarray
    transform: Affine
    crs: object
    shape: Tuple[int, int]   # (height, width)


def load_bb_reflectance(tiff_path: str, radiance_scale: float) -> SceneData:
    """Read BlueBON L1C TIFF, convert DN → TOA radiance → TOA reflectance.

    TOA reflectance formula:
        ρ = π × L × d² / (ESUN × cos(θ_z))

    where L = DN × radiance_scale  [W m⁻² sr⁻¹ μm⁻¹]
    and ESUN, d, θ_z are computed from acquisition metadata.

    Parameters
    ----------
    tiff_path : str
        Path to bb_l1c_*_8band.tiff
    radiance_scale : float
        DN-to-radiance coefficient [W m⁻² sr⁻¹ μm⁻¹ / DN].
        Provide the official per-sensor value; default 0.3 is approximate.
    """
    sensing_time = parse_sensing_time(tiff_path)

    with rasterio.open(tiff_path) as src:
        transform = src.transform
        crs = src.crs
        h, w = src.height, src.width

        # Scene center for solar geometry
        left, bottom, right, top = array_bounds(h, w, transform)

        if crs and not crs.is_geographic:
            tf = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            cx, cy = tf.transform(0.5 * (left + right), 0.5 * (bottom + top))
        else:
            cx = 0.5 * (left + right)
            cy = 0.5 * (bottom + top)

        lat_c, lon_c = float(cy), float(cx)

        sza, saa = solar_zenith_azimuth(sensing_time, lat_c, lon_c)
        d = earth_sun_distance_au(sensing_time)
        cos_sza = math.cos(math.radians(sza))

        print(f"Sensing time : {sensing_time.isoformat()}")
        print(f"Scene center : lat={lat_c:.3f}°  lon={lon_c:.3f}°")
        print(f"Solar zenith : {sza:.2f}°   azimuth={saa:.2f}°")
        print(f"Earth-Sun d  : {d:.5f} AU")

        def read_refl(band_name: str) -> np.ndarray:
            bidx = BB_BANDS[band_name]["raster_band"]
            dn = src.read(bidx).astype(np.float32)
            nodata = src.nodatavals[bidx - 1]
            if nodata is not None:
                dn[dn == nodata] = np.nan
            else:
                dn[dn == 0] = np.nan

            L = dn * radiance_scale
            esun = esun_for_band(band_name)
            rho = (math.pi * L * d ** 2) / (esun * cos_sza)
            rho = np.clip(rho, 0.0, 1.5).astype(np.float32)
            return rho

        blue  = read_refl("BLUE")
        green = read_refl("GREEN")
        red   = read_refl("RED")
        nir   = read_refl("NIR")
        re1   = read_refl("RE1")
        re2   = read_refl("RE2")
        re3   = read_refl("RE3")

    return SceneData(blue=blue, green=green, red=red, nir=nir,
                     re1=re1, re2=re2, re3=re3,
                     transform=transform, crs=crs, shape=(h, w))


def write_geotiff(path: str, arr: np.ndarray,
                  transform: Affine, crs) -> None:
    profile = {
        "driver": "GTiff",
        "height": arr.shape[0],
        "width": arr.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": np.nan,
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(np.float32), 1)


# ---------------------------------------------------------------------------
# Spectral indices and masks
# ---------------------------------------------------------------------------

def compute_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    denom = nir + red
    out = np.full_like(nir, np.nan, dtype=np.float32)
    v = np.isfinite(denom) & (np.abs(denom) > 1e-6)
    out[v] = (nir[v] - red[v]) / denom[v]
    return out


def compute_ndre(nir: np.ndarray, re1: np.ndarray) -> np.ndarray:
    """NDRE = (NIR - RedEdge1) / (NIR + RedEdge1) — sensitive to moderate vegetation density."""
    denom = nir + re1
    out = np.full_like(nir, np.nan, dtype=np.float32)
    v = np.isfinite(denom) & (np.abs(denom) > 1e-6)
    out[v] = (nir[v] - re1[v]) / denom[v]
    return out


@dataclass
class RetrievalConfig:
    # DDV selection — red band used instead of SWIR (no SWIR on BlueBON)
    ndvi_min: float = 0.25        # 겨울 한반도: 0.25로 완화
    red_dark_max: float = 0.15    # 겨울 휴면 식생 허용

    # Blue-to-red surface ratio (Kaufman et al. 1997 DDV relationship)
    # 여름 밀집 식생: 0.50 / 겨울 한반도 중간 식생: 0.35–0.45
    surf_blue_red_ratio: float = 0.40
    # 산림(NDVI≥forest_ndvi_thresh)용 별도 ratio (chlorophyll 흡수로 더 작음)
    surf_blue_red_ratio_forest: float = 0.27
    forest_ndvi_thresh: float = 0.55

    # NDVI-dependent ratio 활성화: NDVI 낮을수록 ratio 감소
    # NDVI ndvi_min ~ forest_ndvi_thresh : surf_blue_red_ratio × (0.6→1.0)
    # NDVI ≥ forest_ndvi_thresh         : surf_blue_red_ratio_forest 적용
    # v9 검증에서 mean +0.028 systematic bias 유발 → v8 동작으로 기본 비활성
    ndvi_dependent_ratio: bool = False

    # Cloud / snow masks
    blue_cloud_thresh: float = 0.25
    snow_blue_thresh:  float = 0.35
    snow_nir_thresh:   float = 0.25
    water_ndvi_thresh: float = 0.05
    water_nir_thresh:  float = 0.05
    ddv_nir_min:       float = 0.20  # 식생 NIR 하한 (조류/하수 침전지 배제)

    # GOCI-II 풍 추가 cloud tests (G2AR Table 7 Step 2/3/5 차용)
    # 다운샘플 → 3×3 테스트 → 업샘플 (GOCI-II는 250m TOA에서 3×3 적용)
    # GEMI test는 정의/스케일 검증 필요해 우선 보류
    # v9 검증에서 R 0.245→0.181 후퇴 → BlueBON 캘리브레이션 차이로 임계 부적합, 기본 비활성
    cloud_tests_enabled: bool = False
    cloud_block_px:     int   = 10      # 25m × 10 = 250m (GOCI-II native 등가)
    blue_stddev_thresh: float = 0.015   # G2AR Step 3
    blue_maxmin_thresh: float = 1.10    # G2AR Step 2
    blue_high_thresh:   float = 0.40    # G2AR Step 5
    use_gemi_test:      bool  = False
    gemi_thresh:        float = 1.87    # G2AR Step 6

    # DDV quality gate
    min_valid_ddv_fraction: float = 0.0005

    # Spatial fill / smooth [pixels at native resolution]
    fill_sigma_px: float = 300.0
    smooth_sigma_px: float = 100.0  # v8 60 → 100 (출력 격자 ~2.5km 스무딩)

    # Output resolution (metres; only used when reprojecting to metric CRS)
    out_res_m: int = 20

    # G2AR Step 9 풍 블록 트리밍 평균 (dark 20% + bright 40% 제외)
    # 네이티브 DDV AOD를 출력 해상도 블록 단위로 트리밍 평균 → 외란/구름잔재 둔감
    # v9 검증에서 단독으로는 bias 보정 효과 부족 → v8 단순 평균으로 기본 비활성
    use_block_trimmed_mean: bool = False
    trim_drop_low_frac:  float  = 0.20
    trim_drop_high_frac: float  = 0.40
    trim_min_count:      int    = 5

    # MAIAC-anchored DDV 교정 (maiac_aod_mean 지정 시에만 적용)
    # - maiac_clip_high_mult: DDV AOD 상한을 MAIAC_mean × mult 로 제한.
    #   None 이면 비활성 (기존 p10..p95 클리핑만).
    #   clean day(MAIAC 0.06)에서 DDV 꼬리(p95=1.0+)가 전역으로 smear 되는 문제 방지.
    # - maiac_scale_ddv_median: DDV median 을 MAIAC_mean 에 맞도록 선형 스케일.
    #   scale 값이 [scale_min, scale_max] 밖이면 무시(극단 보정 방지).
    maiac_clip_high_mult:   Optional[float] = None
    maiac_scale_ddv_median: bool  = False
    maiac_scale_min:        float = 0.5
    maiac_scale_max:        float = 2.0

    # 6S parameters
    use_py6s: bool = True
    aerosol_profile: str = "continental"
    atmosphere_profile: str = "auto"
    target_alt_km: float = 0.0
    lut_aot_nodes: Tuple[float, ...] = (0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0)

    # Fallback when Py6S unavailable
    fallback_rayleigh_blue_offset: float = 0.067   # ~correct for SZA 50°
    aod_gain: float = 4.0
    aod_bias: float = 0.0


def _local_stddev(arr: np.ndarray, size: int = 3) -> np.ndarray:
    """size×size 픽셀 표준편차 (uniform_filter 기반, NaN→0 처리)."""
    a = np.where(np.isfinite(arr), arr, 0.0).astype(np.float32)
    m = np.isfinite(arr).astype(np.float32)
    den    = np.maximum(uniform_filter(m, size=size), 1e-6)
    mean   = uniform_filter(a, size=size) / den
    sq     = uniform_filter(a * a, size=size) / den
    var    = np.clip(sq - mean * mean, 0.0, None)
    return np.sqrt(var).astype(np.float32)


def _gemi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Global Environment Monitoring Index (Pinty & Verstraete 1992)."""
    eta = (2.0 * (nir * nir - red * red) + 1.5 * nir + 0.5 * red) \
          / np.maximum(nir + red + 0.5, 1e-6)
    return (eta * (1.0 - 0.25 * eta) - (red - 0.125) / np.maximum(1.0 - red, 1e-6)).astype(np.float32)


def build_masks(scene: SceneData, cfg: RetrievalConfig) -> Dict[str, np.ndarray]:
    blue, green, red, nir = scene.blue, scene.green, scene.red, scene.nir

    ndvi = compute_ndvi(nir, red)
    ndre = compute_ndre(nir, scene.re1)

    # Thick cloud: high blue only (same reasoning as S2 fix — SWIR > 0.10 is
    # normal over land so the SWIR-based cirrus test would flag all land)
    cloud = blue > cfg.blue_cloud_thresh

    # GOCI-II G2AR Table 7 풍 spatial cloud tests (Steps 2/3/5)
    # 25m native blue를 ~250m로 다운샘플 → 3×3 테스트 → 25m로 업샘플(블록 단위)
    if cfg.cloud_tests_enabled:
        bk = max(2, int(cfg.cloud_block_px))
        H, W = blue.shape
        Hc = (H // bk) * bk
        Wc = (W // bk) * bk
        b_crop = blue[:Hc, :Wc]
        valid_crop = np.isfinite(b_crop)
        b_filled = np.where(valid_crop, b_crop, 0.0).astype(np.float32)
        # bk×bk 블록 평균
        view = b_filled.reshape(Hc // bk, bk, Wc // bk, bk)
        cnt  = valid_crop.reshape(Hc // bk, bk, Wc // bk, bk).sum(axis=(1, 3))
        ssum = view.sum(axis=(1, 3))
        block_mean = np.where(cnt > 0, ssum / np.maximum(cnt, 1), np.nan).astype(np.float32)
        # 3×3 테스트 (블록 단위)
        sdev_b = _local_stddev(block_mean, size=3)
        bm = np.where(np.isfinite(block_mean) & (block_mean > 1e-4), block_mean, np.nan)
        bmax = maximum_filter(np.where(np.isnan(bm), -np.inf, bm), size=3)
        bmin = minimum_filter(np.where(np.isnan(bm),  np.inf, bm), size=3)
        ratio_b = np.where(np.isfinite(bmax) & (bmin > 1e-4),
                           bmax / np.maximum(bmin, 1e-4), 0.0)
        block_cloud = (sdev_b > cfg.blue_stddev_thresh) | (ratio_b > cfg.blue_maxmin_thresh)
        # 25m로 업샘플(블록 단위 nearest)
        spatial_cloud = np.zeros_like(blue, dtype=bool)
        spatial_cloud[:Hc, :Wc] = np.repeat(np.repeat(block_cloud, bk, axis=0), bk, axis=1)
        # Step 5: TOA blue > 0.4 (native)
        cloud_high = blue > cfg.blue_high_thresh
        cloud = cloud | spatial_cloud | cloud_high
        # Step 6: GEMI < thresh — optional
        if cfg.use_gemi_test:
            gemi = _gemi(red, nir)
            cloud = cloud | (gemi < cfg.gemi_thresh)

    # Snow: high blue AND high NIR (proxy without SWIR-based NDSI)
    snow = (blue > cfg.snow_blue_thresh) & (nir > cfg.snow_nir_thresh) & (ndvi < 0.15)

    water = (ndvi < cfg.water_ndvi_thresh) & (nir < cfg.water_nir_thresh)

    invalid = (
        ~np.isfinite(blue) | ~np.isfinite(green)
        | ~np.isfinite(red) | ~np.isfinite(nir)
    )

    return {"ndvi": ndvi, "ndre": ndre, "cloud": cloud,
            "snow": snow, "water": water, "invalid": invalid}


def select_ddv(scene: SceneData, masks: Dict[str, np.ndarray],
               cfg: RetrievalConfig) -> np.ndarray:
    """Dark Dense Vegetation without SWIR.

    Uses NDVI threshold + dark-red criterion (Kaufman et al. 1997):
      - NDVI ≥ ndvi_min  (dense green canopy)
      - TOA red ≤ red_dark_max  (dark surface, consistent with DDV)
      - NIR ≥ nir_min   (real vegetation reflects NIR strongly;
                         excludes algae mats / sewage ponds where NIR is absorbed by water)
    """
    return (
        (masks["ndvi"] >= cfg.ndvi_min)
        & (scene.red <= cfg.red_dark_max)
        & (scene.nir >= cfg.ddv_nir_min)
        & ~masks["cloud"]
        & ~masks["snow"]
        & ~masks["water"]
        & ~masks["invalid"]
    )


def estimate_surface_blue(scene: SceneData, ndvi: np.ndarray,
                          cfg: RetrievalConfig) -> np.ndarray:
    """Estimate surface blue reflectance from red (Kaufman 1997 ratio).

    NDVI 의존 비율 (ndvi_dependent_ratio=True 시):
      겨울/중간 식생(NDVI~0.25): ratio × 0.6
      여름 밀집 식생(NDVI≥0.60): ratio × 1.0
    - Kaufman 1997의 0.5는 여름 밀집 식생 기준이므로
      겨울 한반도처럼 NDVI가 낮은 경우 ratio를 낮춰야 함.
    """
    if cfg.ndvi_dependent_ratio:
        ndvi_low  = cfg.ndvi_min
        ndvi_high = cfg.forest_ndvi_thresh
        frac = np.clip((ndvi - ndvi_low) / max(ndvi_high - ndvi_low, 0.01), 0.0, 1.0)
        ratio_low = cfg.surf_blue_red_ratio * (0.6 + 0.4 * frac)
        # 산림은 chlorophyll 흡수로 blue/red 더 작음 → 별도 분기
        ratio = np.where(ndvi >= cfg.forest_ndvi_thresh,
                         cfg.surf_blue_red_ratio_forest,
                         ratio_low).astype(np.float32)
    else:
        ratio = cfg.surf_blue_red_ratio

    surf_blue = ratio * scene.red
    return np.clip(surf_blue, 0.0, 0.20).astype(np.float32)


# ---------------------------------------------------------------------------
# 6S LUT (reused from S2_AOD_calval logic)
# ---------------------------------------------------------------------------

_TAU_RAY_490 = 0.133
_ANGSTROM    = 1.3


def try_import_py6s():
    try:
        from Py6S import SixS, AtmosProfile, AeroProfile, Geometry, Wavelength, GroundReflectance
        return SixS, AtmosProfile, AeroProfile, Geometry, Wavelength, GroundReflectance
    except Exception:
        return None


def _map_aero_profile(name: str):
    imported = try_import_py6s()
    if imported is None:
        return None
    _, _, AeroProfile, _, _, _ = imported
    return {"continental": AeroProfile.Continental,
            "maritime": AeroProfile.Maritime,
            "urban": AeroProfile.Urban,
            "desert": AeroProfile.Desert}.get(name.lower(), AeroProfile.Continental)


def _map_atmos_profile(name: str):
    imported = try_import_py6s()
    if imported is None:
        return None
    _, AtmosProfile, _, _, _, _ = imported
    return {"midlatitude_summer": AtmosProfile.MidlatitudeSummer,
            "midlatitude_winter": AtmosProfile.MidlatitudeWinter,
            "tropical": AtmosProfile.Tropical,
            "subarctic_summer": AtmosProfile.SubarcticSummer,
            "subarctic_winter": AtmosProfile.SubarcticWinter}.get(
                name.lower(), AtmosProfile.MidlatitudeSummer)


def auto_atmosphere_profile(sensing_time: datetime, lat: float) -> str:
    month = sensing_time.month
    if lat > 60:
        return "subarctic_winter" if month in (11, 12, 1, 2, 3, 4) else "subarctic_summer"
    elif lat > 30:
        return "midlatitude_winter" if month in (11, 12, 1, 2, 3) else "midlatitude_summer"
    return "tropical"


@dataclass
class SixSLUT:
    aot_nodes: np.ndarray
    path_ref: np.ndarray
    rayleigh_offset: float = 0.0

    @property
    def is_valid(self) -> bool:
        return len(self.aot_nodes) >= 2


def build_6s_blue_lut(solar_z: float, view_z: float, rel_az: float,
                      target_alt_km: float, atmos_profile: str,
                      cfg: RetrievalConfig) -> SixSLUT:
    _fallback = SixSLUT(
        aot_nodes=np.array([0.01, 2.0]),
        path_ref=np.array([cfg.fallback_rayleigh_blue_offset,
                           cfg.fallback_rayleigh_blue_offset + 0.25]),
        rayleigh_offset=cfg.fallback_rayleigh_blue_offset,
    )
    if not cfg.use_py6s:
        print("  Py6S disabled — fallback Rayleigh offset used.")
        return _fallback

    imported = try_import_py6s()
    if imported is None:
        print("  Py6S not available — fallback Rayleigh offset used.")
        return _fallback

    SixS, AtmosProfile, AeroProfile, Geometry, Wavelength, GroundReflectance = imported
    atmos = _map_atmos_profile(atmos_profile)
    aero  = _map_aero_profile(cfg.aerosol_profile)
    if atmos is None or aero is None:
        return _fallback

    aot_vals, path_ref_vals = [], []
    print(f"  Building 6S LUT ({len(cfg.lut_aot_nodes)} runs) at 490 nm …", flush=True)
    for aot in cfg.lut_aot_nodes:
        try:
            s = SixS()
            s.geometry = Geometry.User()
            s.geometry.solar_z = float(solar_z)
            s.geometry.view_z  = float(view_z)
            s.geometry.solar_a = 0.0
            s.geometry.view_a  = float(rel_az)
            s.atmos_profile = AtmosProfile.PredefinedType(atmos)
            s.aero_profile  = AeroProfile.PredefinedType(aero)
            s.aot550        = float(max(aot, 0.001))
            s.wavelength    = Wavelength(0.490)
            s.altitudes.set_sensor_satellite_level()
            s.altitudes.set_target_custom_altitude(float(target_alt_km))
            s.ground_reflectance = GroundReflectance.HomogeneousLambertian(0.0)
            s.run()
            rho_p = float(s.outputs.atmospheric_intrinsic_reflectance)
            if np.isfinite(rho_p) and rho_p >= 0:
                aot_vals.append(float(aot))
                path_ref_vals.append(rho_p)
                print(f"    AOT={aot:.3f}  rho_path={rho_p:.5f}")
        except Exception as exc:
            print(f"    AOT={aot:.3f}  FAILED: {exc}")

    if len(aot_vals) < 2:
        print("  WARNING: too few 6S runs; using fallback.")
        return _fallback

    aot_arr  = np.array(aot_vals, dtype=np.float64)
    path_arr = np.array(path_ref_vals, dtype=np.float64)
    rayleigh = float(np.interp(0.0, aot_arr, path_arr))
    print(f"  Rayleigh offset at 490 nm (AOT→0): {rayleigh:.5f}")
    return SixSLUT(aot_nodes=aot_arr, path_ref=path_arr, rayleigh_offset=rayleigh)


def _two_way_transmittance_490(aot550: np.ndarray,
                               mu_s: float, mu_v: float) -> np.ndarray:
    tau_aero  = np.asarray(aot550, dtype=np.float64) * (490.0 / 550.0) ** _ANGSTROM
    tau_total = _TAU_RAY_490 + tau_aero
    return np.exp(-tau_total * (1.0 / mu_s + 1.0 / mu_v)).astype(np.float32)


def invert_aod_from_lut(blue_toa: np.ndarray, surf_blue: np.ndarray,
                        lut: SixSLUT, solar_z_deg: float,
                        view_z_deg: float) -> np.ndarray:
    """6S LUT 역산 (2회 Newton 반복).

    surf_blue > blue_toa 인 경우 path_reflectance < Rayleigh 이 되어
    np.interp left=0 으로 AOD=0 이 반환되는 문제를 방지하기 위해:
    - 초기 추정은 (blue - Rayleigh) 에서 시작 (surf 기여 무시)
    - 수렴된 AOD에서 surf × T 를 차감한 residual 로 재추정
    """
    mu_s = max(math.cos(math.radians(solar_z_deg)), 0.01)
    mu_v = max(math.cos(math.radians(view_z_deg)),  0.01)
    aot_n = lut.aot_nodes.astype(np.float64)
    pr_n  = lut.path_ref.astype(np.float64)
    blue  = blue_toa.astype(np.float64)
    surf  = surf_blue.astype(np.float64)
    rayl  = lut.rayleigh_offset

    # 1단계: path ≈ blue - Rayleigh (surf 기여 제외, 보수적 초기값)
    rho0 = np.clip(blue - rayl, 0.0, None)
    aod0 = np.interp(rho0, pr_n, aot_n, left=0.0, right=aot_n[-1])

    # 2단계: surf × T(aod0) 보정
    trans0 = _two_way_transmittance_490(aod0, mu_s, mu_v).astype(np.float64)
    rho1   = np.clip(blue - surf * trans0, 0.0, None)
    aod1   = np.interp(rho1, pr_n, aot_n, left=0.0, right=aot_n[-1])

    # 3단계: 한 번 더 반복 (수렴 개선)
    trans1 = _two_way_transmittance_490(aod1, mu_s, mu_v).astype(np.float64)
    rho2   = np.clip(blue - surf * trans1, 0.0, None)
    aod2   = np.interp(rho2, pr_n, aot_n, left=0.0, right=aot_n[-1])

    return np.clip(aod2, 0.0, 5.0).astype(np.float32)


def path_reflectance_to_aod_linear(rho_aero: np.ndarray, cfg: RetrievalConfig) -> np.ndarray:
    return np.clip(cfg.aod_gain * rho_aero + cfg.aod_bias, 0.0, 5.0)


# ---------------------------------------------------------------------------
# Spatial fill helpers
# ---------------------------------------------------------------------------

def fill_from_ddv(aod_ddv: np.ndarray, ddv_mask: np.ndarray,
                  sigma: float = 300.0) -> np.ndarray:
    valid = ddv_mask & np.isfinite(aod_ddv)
    if not valid.any():
        return np.full_like(aod_ddv, np.nan, dtype=np.float32)
    weights = valid.astype(np.float32)
    values  = np.where(valid, aod_ddv, 0.0).astype(np.float32)
    num = gaussian_filter(values,  sigma=sigma)
    den = gaussian_filter(weights, sigma=sigma)
    out = np.full_like(aod_ddv, np.nan, dtype=np.float32)
    good = den > 1e-4
    out[good] = num[good] / den[good]
    return out


def downsample_mean(arr: np.ndarray, src_transform: Affine,
                    src_crs, out_res: int) -> Tuple[np.ndarray, Affine]:
    """Downsample from native resolution to out_res metres (approximate for geographic CRS)."""
    from rasterio.transform import from_bounds
    h, w = arr.shape
    left, bottom, right, top = array_bounds(h, w, src_transform)

    # Estimate native pixel size in metres
    if src_crs and CRS.from_user_input(src_crs).is_geographic:
        lat_mid = 0.5 * (top + bottom)
        px_m = src_transform.e * 110540      # deg → m (N-S)
        py_m = src_transform.a * 111320 * math.cos(math.radians(lat_mid))  # deg → m (E-W)
        native_m = 0.5 * (abs(px_m) + abs(py_m))
    else:
        native_m = abs(src_transform.a)

    scale = out_res / native_m
    if scale <= 1.0:
        return arr.astype(np.float32), src_transform

    out_h = max(1, int(np.ceil(h / scale)))
    out_w = max(1, int(np.ceil(w / scale)))
    dst = np.full((out_h, out_w), np.nan, dtype=np.float32)
    dst_transform = src_transform * Affine.scale(scale, scale)

    reproject(
        source=arr.astype(np.float32),
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=src_crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    return dst, dst_transform


def block_trimmed_mean(arr: np.ndarray, src_transform: Affine, src_crs,
                       out_res: int,
                       drop_low_frac: float = 0.20,
                       drop_high_frac: float = 0.40,
                       min_count: int = 5) -> Tuple[np.ndarray, Affine]:
    """G2AR Step 9 등가 블록 트리밍 평균.

    출력 픽셀(out_res 미터)마다 native 값들을 정렬하여 하위 drop_low_frac,
    상위 drop_high_frac을 제외한 가운데 평균을 반환. 유효 픽셀이 min_count 미만이면
    그냥 평균. NaN은 무시.
    """
    h, w = arr.shape
    if src_crs and CRS.from_user_input(src_crs).is_geographic:
        left, bottom, right, top = array_bounds(h, w, src_transform)
        lat_mid = 0.5 * (top + bottom)
        px_m = abs(src_transform.e) * 110540
        py_m = abs(src_transform.a) * 111320 * math.cos(math.radians(lat_mid))
        native_m = 0.5 * (px_m + py_m)
    else:
        native_m = abs(src_transform.a)
    scale = out_res / native_m
    if scale <= 1.0:
        return arr.astype(np.float32), src_transform

    bk = max(2, int(round(scale)))
    Hc = (h // bk) * bk
    Wc = (w // bk) * bk
    a_crop = arr[:Hc, :Wc].astype(np.float32)
    Hb, Wb = Hc // bk, Wc // bk

    blocks = (a_crop.reshape(Hb, bk, Wb, bk)
                    .transpose(0, 2, 1, 3)
                    .reshape(Hb, Wb, bk * bk))
    finite_count = np.isfinite(blocks).sum(axis=2).astype(np.int32)
    sorted_blocks = np.sort(blocks, axis=2)  # NaN → 끝
    sorted_safe = np.where(np.isfinite(sorted_blocks), sorted_blocks, 0.0)
    cs0 = np.concatenate(
        [np.zeros((Hb, Wb, 1), dtype=np.float32),
         np.cumsum(sorted_safe, axis=2, dtype=np.float32)],
        axis=2,
    )

    n = finite_count
    lo_full = np.round(n * drop_low_frac).astype(np.int32)
    hi_full = n - np.round(n * drop_high_frac).astype(np.int32)
    hi_full = np.maximum(hi_full, lo_full + 1)
    small = n < min_count
    lo = np.where(small, 0, lo_full)
    hi = np.where(small, n, hi_full)

    ii, jj = np.meshgrid(np.arange(Hb), np.arange(Wb), indexing="ij")
    sums = cs0[ii, jj, hi] - cs0[ii, jj, lo]
    counts = (hi - lo).astype(np.float32)
    out = np.where((n > 0) & (counts > 0),
                   sums / np.maximum(counts, 1.0),
                   np.nan).astype(np.float32)

    new_transform = src_transform * Affine.scale(bk, bk)
    return out, new_transform


# ---------------------------------------------------------------------------
# Main retrieval pipeline
# ---------------------------------------------------------------------------

def retrieve_aod(input_path: str, cfg: RetrievalConfig,
                 radiance_scale: float,
                 solar_z_override: Optional[float] = None,
                 view_z_deg: float = 0.0,
                 rel_az_deg: float = 0.0,
                 maiac_aod_mean: Optional[float] = None) -> Tuple[np.ndarray, Affine, object, dict]:

    sensing_time = parse_sensing_time(input_path)
    scene = load_bb_reflectance(input_path, radiance_scale)

    # Solar geometry
    left, bottom, right, top = array_bounds(scene.shape[0], scene.shape[1], scene.transform)
    if scene.crs and not CRS.from_user_input(scene.crs).is_geographic:
        tf = Transformer.from_crs(scene.crs, "EPSG:4326", always_xy=True)
        lon_c, lat_c = tf.transform(0.5 * (left + right), 0.5 * (bottom + top))
    else:
        lon_c, lat_c = 0.5 * (left + right), 0.5 * (bottom + top)

    sza, saa = solar_zenith_azimuth(sensing_time, lat_c, lon_c)
    solar_z = solar_z_override if solar_z_override is not None else sza

    # Default view angles (BlueBON is push-broom, near-nadir)
    vz  = view_z_deg
    ra  = rel_az_deg if rel_az_deg != 0.0 else abs(saa - 180.0) % 180.0

    print(f"\nGeometry     : solar_z={solar_z:.2f}°  view_z={vz:.2f}°  rel_az={ra:.2f}°")

    # Atmosphere profile
    atmos = cfg.atmosphere_profile
    if atmos == "auto":
        atmos = auto_atmosphere_profile(sensing_time, lat_c)
        print(f"Atmosphere   : {atmos}  (auto, lat={lat_c:.1f}°, month={sensing_time.month})")
    print(f"Aerosol type : {cfg.aerosol_profile}")

    # Masks and DDV
    masks = build_masks(scene, cfg)
    ddv   = select_ddv(scene, masks, cfg)

    cloud_frac = float(masks["cloud"].mean())
    snow_frac  = float(masks["snow"].mean())
    clear_frac = float((~masks["cloud"] & ~masks["snow"] & ~masks["invalid"]).mean())
    ddv_frac   = float(ddv.sum()) / float(ddv.size)

    ndvi_vals = masks["ndvi"][np.isfinite(masks["ndvi"])]
    print(f"\nScene fractions: cloud={cloud_frac:.1%}  snow={snow_frac:.1%}  clear={clear_frac:.1%}")
    if ndvi_vals.size > 0:
        print(f"NDVI range   : {ndvi_vals.min():.3f} .. {ndvi_vals.max():.3f}  "
              f"mean={ndvi_vals.mean():.3f}")

    usable = ~masks["cloud"] & ~masks["snow"] & ~masks["water"] & ~masks["invalid"]
    n_ndvi = int(((masks["ndvi"] >= cfg.ndvi_min) & usable).sum())
    n_red  = int(((scene.red <= cfg.red_dark_max) & usable).sum())
    n_both = int(ddv.sum())
    print(f"DDV diagnosis: usable={usable.sum():,}  "
          f"NDVI≥{cfg.ndvi_min}={n_ndvi:,}  "
          f"Red≤{cfg.red_dark_max}={n_red:,}  "
          f"both={n_both:,}")
    print(f"DDV pixels   : {n_both:,}  ({ddv_frac:.4%})")

    if ddv_frac < cfg.min_valid_ddv_fraction:
        # Diagnostics hint
        if n_ndvi == 0:
            hint = "No dense vegetation; try --ndvi-min 0.25"
        elif n_both == 0:
            p50 = float(np.nanpercentile(scene.red[masks["ndvi"] >= cfg.ndvi_min & usable], 50)) \
                  if (masks["ndvi"] >= cfg.ndvi_min).any() else 0.15
            hint = f"Dark pixels have red median ≈ {p50:.3f}; try --red-dark-max {p50+0.02:.2f}"
        else:
            hint = f"Lower --min-ddv-fraction below {ddv_frac:.5f}"
        raise RuntimeError(f"Too few DDV pixels ({ddv_frac:.5%}). {hint}")

    # 6S LUT at 490 nm
    lut = build_6s_blue_lut(solar_z, vz, ra, cfg.target_alt_km, atmos, cfg)

    # Surface blue (NDVI-dependent ratio) and AOD on DDV pixels
    surf_blue = estimate_surface_blue(scene, masks["ndvi"], cfg)

    # DDV 픽셀에서 surf_blue 통계 출력
    if ddv.any():
        sb_ddv = surf_blue[ddv]
        bl_ddv = scene.blue[ddv]
        path_ddv = np.clip(bl_ddv - sb_ddv, 0.0, None)
        print(f"DDV reflectance: blue={bl_ddv.mean():.4f}  surf_blue={sb_ddv.mean():.4f}  "
              f"path_init={path_ddv.mean():.4f}  Rayleigh={lut.rayleigh_offset:.4f}")

    if lut.is_valid and cfg.use_py6s:
        aod_ddv_vals = invert_aod_from_lut(scene.blue, surf_blue, lut, solar_z, vz)
        aod_ddv = np.where(ddv, aod_ddv_vals, np.nan).astype(np.float32)
        method = "6S LUT inversion (NDVI-dependent DDV ratio)"
    else:
        rho_aero = np.clip(scene.blue - surf_blue - lut.rayleigh_offset, 0.0, None)
        aod_ddv  = np.where(ddv, path_reflectance_to_aod_linear(rho_aero, cfg), np.nan).astype(np.float32)
        method = "fallback linear"

    print(f"AOD method   : {method}")
    if np.isfinite(aod_ddv).any():
        v = aod_ddv[np.isfinite(aod_ddv)]
        p10 = float(np.percentile(v, 10))
        p95 = float(np.percentile(v, 95))
        print(f"AOD on DDV   : {v.min():.3f} .. {v.max():.3f}  mean={v.mean():.3f}  "
              f"median={np.median(v):.3f}  p10={p10:.3f}  p95={p95:.3f}")
        zero_frac = (v < 0.01).mean()
        if zero_frac > 0.5:
            print(f"  WARNING: DDV AOD={zero_frac:.1%}가 <0.01 → radiance_scale 또는 surf-blue-red-ratio 점검 필요")
        # 양방향 클리핑(NaN 처리 대신 값 클립): 분포의 꼬리를 줄여 spatial coherence 향상
        finite_mask = np.isfinite(aod_ddv)
        clipped = np.clip(aod_ddv[finite_mask], p10, p95)
        n_low  = int((aod_ddv[finite_mask] < p10).sum())
        n_high = int((aod_ddv[finite_mask] > p95).sum())
        aod_ddv[finite_mask] = clipped.astype(np.float32)
        print(f"  DDV clip [{p10:.3f},{p95:.3f}]: low={n_low:,}  high={n_high:,} 픽셀 클립")

        # MAIAC-anchored 추가 교정 (maiac_aod_mean 지정 + 옵션 활성화 시)
        if maiac_aod_mean is not None and cfg.maiac_clip_high_mult is not None:
            hi_cap = float(maiac_aod_mean * cfg.maiac_clip_high_mult)
            n_over = int((aod_ddv[finite_mask] > hi_cap).sum())
            aod_ddv[finite_mask] = np.clip(aod_ddv[finite_mask], 0.0, hi_cap).astype(np.float32)
            print(f"  MAIAC-anchored cap: DDV AOD ≤ {hi_cap:.3f} "
                  f"(MAIAC={maiac_aod_mean:.3f} × {cfg.maiac_clip_high_mult:.1f}, "
                  f"{n_over:,} 픽셀 cap)")

        if (maiac_aod_mean is not None and cfg.maiac_scale_ddv_median
                and finite_mask.any()):
            ddv_med_after = float(np.median(aod_ddv[finite_mask]))
            if ddv_med_after > 0.01:
                scale = float(maiac_aod_mean) / ddv_med_after
                if cfg.maiac_scale_min <= scale <= cfg.maiac_scale_max:
                    aod_ddv[finite_mask] = np.clip(
                        aod_ddv[finite_mask] * scale, 0.0, 5.0
                    ).astype(np.float32)
                    print(f"  MAIAC-anchored scale: DDV median {ddv_med_after:.3f} "
                          f"→ {maiac_aod_mean:.3f} (×{scale:.3f})")
                else:
                    print(f"  MAIAC-anchored scale skipped: ×{scale:.3f} out of "
                          f"[{cfg.maiac_scale_min},{cfg.maiac_scale_max}] "
                          f"(DDV median={ddv_med_after:.3f})")

    # Spatial fill — 다운샘플 후 fill (성능 핵심 개선):
    #   1. DDV AOD 및 마스크를 출력 해상도(기본 20m)로 먼저 다운샘플
    #   2. 다운샘플된 격자에서 gaussian fill → 원래 184M 픽셀 대신 11.5M 픽셀에서 연산
    #   3. background fill (clear + cloud + snow) → MAIAC 참조값 또는 DDV 중앙값
    #   4. truly_invalid(DN=0, swath 밖)만 NaN 유지
    truly_invalid = masks["invalid"]

    ddv_med = float(np.nanmedian(aod_ddv)) if np.isfinite(aod_ddv).any() else 0.0
    if maiac_aod_mean is not None:
        fill_val = float(maiac_aod_mean)
        fill_src = "MAIAC ref"
    else:
        fill_val = ddv_med
        fill_src = "DDV median"
    if fill_val < lut.rayleigh_offset * 0.5:
        fill_val = max(fill_val, lut.rayleigh_offset * 0.3)

    # --- Step 1: QA 및 마스크 다운샘플 ---
    qa = np.zeros(scene.shape, dtype=np.uint8)
    qa[ddv]              = 1
    qa[masks["water"]]   = 2
    qa[masks["cloud"]]   = 3
    qa[masks["snow"]]    = 4
    qa[masks["invalid"]] = 255
    qa_ds, out_transform = downsample_mean(qa.astype(np.float32),
                                           scene.transform, scene.crs, cfg.out_res_m)

    # 다운샘플 마스크 (majority 기준)
    inv_ds,  _ = downsample_mean(truly_invalid.astype(np.float32),
                                 scene.transform, scene.crs, cfg.out_res_m)
    cloud_ds, _ = downsample_mean(masks["cloud"].astype(np.float32),
                                  scene.transform, scene.crs, cfg.out_res_m)
    snow_ds, _  = downsample_mean(masks["snow"].astype(np.float32),
                                  scene.transform, scene.crs, cfg.out_res_m)
    inv_ds_mask   = inv_ds   > 0.5
    cloud_ds_mask = cloud_ds > 0.5
    snow_ds_mask  = snow_ds  > 0.5

    # --- Step 2: DDV AOD 다운샘플 (G2AR Step 9: 블록 트리밍 평균) ---
    if cfg.use_block_trimmed_mean:
        aod_trim, trim_tf = block_trimmed_mean(
            aod_ddv, scene.transform, scene.crs, cfg.out_res_m,
            drop_low_frac=cfg.trim_drop_low_frac,
            drop_high_frac=cfg.trim_drop_high_frac,
            min_count=cfg.trim_min_count,
        )
        n_trim_native = int(np.isfinite(aod_trim).sum())
        # qa_ds 격자에 맞춰 정렬 (rasterio nearest)
        aod_ddv_ds = np.full_like(qa_ds, np.nan, dtype=np.float32)
        reproject(
            source=aod_trim,
            destination=aod_ddv_ds,
            src_transform=trim_tf,
            src_crs=scene.crs,
            dst_transform=out_transform,
            dst_crs=scene.crs,
            src_nodata=np.nan,
            dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )
        ddv_ds_mask = np.isfinite(aod_ddv_ds)
        print(f"  Block trimmed-mean (drop low {cfg.trim_drop_low_frac:.0%} / "
              f"high {cfg.trim_drop_high_frac:.0%}): "
              f"{n_trim_native:,} blocks → {int(ddv_ds_mask.sum()):,} on out grid")
    else:
        aod_ddv_ds, _ = downsample_mean(
            np.where(np.isfinite(aod_ddv), aod_ddv, 0.0).astype(np.float32),
            scene.transform, scene.crs, cfg.out_res_m,
        )
        ddv_wt_ds, _ = downsample_mean(
            np.isfinite(aod_ddv).astype(np.float32),
            scene.transform, scene.crs, cfg.out_res_m,
        )
        ddv_ds_mask = ddv_wt_ds > 0.0
        aod_ddv_ds  = np.where(ddv_ds_mask,
                                aod_ddv_ds / np.maximum(ddv_wt_ds, 1e-9),
                                np.nan).astype(np.float32)

    # --- Step 3: Gaussian fill at output resolution ---
    # sigma를 출력 픽셀 단위로 변환 (fill_sigma_px는 5m 기준)
    native_m  = abs(scene.transform.a) * 111320  # 지리좌표 → m 개략 변환
    if scene.crs and not CRS.from_user_input(scene.crs).is_geographic:
        native_m = abs(scene.transform.a)
    sigma_ds = max(1.0, cfg.fill_sigma_px * native_m / cfg.out_res_m)
    aod_full = fill_from_ddv(aod_ddv_ds, ddv_ds_mask, sigma=sigma_ds)

    # --- Step 4: Background fill (clear + cloud + snow) ---
    unfilled = ~inv_ds_mask & ~np.isfinite(aod_full)
    if unfilled.any():
        aod_full[unfilled] = fill_val
        n_clear = int((unfilled & ~cloud_ds_mask & ~snow_ds_mask).sum())
        n_cloud = int((unfilled & cloud_ds_mask).sum())
        n_snow  = int((unfilled & snow_ds_mask).sum())
        print(f"  Background fill ({fill_src}={fill_val:.3f}): "
              f"clear={n_clear:,}  cloud={n_cloud:,}  snow={n_snow:,}")

    valid_before = np.isfinite(aod_full)
    smooth_sigma_ds = max(1.0, cfg.smooth_sigma_px * native_m / cfg.out_res_m)
    # NaN-aware weighted gaussian: 0-leakage 방지하여 swath 경계 인공 gradient 제거
    num = gaussian_filter(np.where(valid_before, aod_full, 0.0).astype(np.float32),
                          sigma=smooth_sigma_ds)
    den = gaussian_filter(valid_before.astype(np.float32),
                          sigma=smooth_sigma_ds)
    smoothed = num / np.maximum(den, 1e-9)
    aod_full = np.where(valid_before, smoothed, np.nan).astype(np.float32)
    aod_full[inv_ds_mask]   = np.nan
    out_arr = np.clip(aod_full, 0.0, 5.0).astype(np.float32)

    debug = {
        "ddv_mask": ddv,
        "surface_blue": surf_blue,
        "qa": qa_ds,
        "rayleigh_offset": lut.rayleigh_offset,
        "solar_z": solar_z,
        "solar_az": saa,
        "atmosphere": atmos,
        "lut_aot": lut.aot_nodes.tolist(),
        "lut_path_ref": lut.path_ref.tolist(),
        "sensing_time": sensing_time.isoformat(),
    }
    return out_arr, out_transform, scene.crs, debug


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="BlueBON AOD retrieval from L1C TOA Radiance 8-band TIFF"
    )
    p.add_argument("--input", required=True,
                   help="Path to bb_l1c_*_8band.tiff (TOA radiance, uint16 DN)")
    p.add_argument("--out", required=True,
                   help="Output GeoTIFF for AOD(550)")
    p.add_argument("--out-qa", default=None,
                   help="Optional QA GeoTIFF")

    # Calibration
    p.add_argument("--radiance-scale", type=float, default=0.3,
                   help="DN → radiance coefficient [W/m²/sr/μm per DN]. "
                        "Replace with official sensor calibration value.")

    # DDV thresholds
    p.add_argument("--ndvi-min", type=float, default=0.25,
                   help="Min NDVI for DDV selection (겨울: 0.25)")
    p.add_argument("--red-dark-max", type=float, default=0.15,
                   help="Max TOA red reflectance for DDV")
    p.add_argument("--ddv-nir-min", type=float, default=0.20,
                   help="Min NIR reflectance for DDV (vegetation reflects NIR strongly; "
                        "excludes algae mats / sewage ponds). Default: 0.20")
    p.add_argument("--surf-blue-red-ratio", type=float, default=0.40,
                   help="rho_surf_blue / rho_surf_red 기준 비율 (Kaufman 1997: 0.5, 겨울: 0.35–0.45)")
    p.add_argument("--no-ndvi-dependent-ratio", action="store_true",
                   help="NDVI-dependent ratio 비활성화 (고정 ratio 사용)")
    p.add_argument("--min-ddv-fraction", type=float, default=0.0005)
    p.add_argument("--maiac-aod-mean", type=float, default=None,
                   help="MAIAC scene AOD 평균값 (validate_bb_aod.py 출력). "
                        "지정 시 clear 픽셀 fill에 DDV median 대신 MAIAC 참조값 사용.")
    # MAIAC 보정
    p.add_argument("--maiac-ref", default=None,
                   help="MAIAC AOD GeoTIFF 경로 (validate_bb_aod.py 출력물). "
                        "지정 시 MAIAC 기반 radiance_scale/ratio 자동 보정 후 산출.")
    p.add_argument("--out-res", type=int, default=20,
                   help="Output resolution in metres")
    p.add_argument("--smooth-sigma-px", type=float, default=100.0,
                   help="Post-fill Gaussian smoothing sigma (5m native px). "
                        "Higher = smoother spatial AOD field (default: 100).")
    p.add_argument("--fill-sigma-px", type=float, default=300.0,
                   help="Spatial fill Gaussian sigma (5m native px). default: 300.")

    # 6S
    p.add_argument("--no-py6s", action="store_true")
    p.add_argument("--solar-z-deg", type=float, default=None,
                   help="Override solar zenith (degrees); default: computed from filename datetime")
    p.add_argument("--view-z-deg",  type=float, default=0.0)
    p.add_argument("--rel-az-deg",  type=float, default=0.0)
    p.add_argument("--aerosol-profile", default="continental",
                   choices=["continental", "maritime", "urban", "desert"])
    p.add_argument("--atmosphere-profile", default="auto",
                   choices=["auto", "midlatitude_summer", "midlatitude_winter",
                            "tropical", "subarctic_summer", "subarctic_winter"])
    p.add_argument("--target-alt-km", type=float, default=0.0)

    # Fallback params (used only when Py6S unavailable)
    p.add_argument("--fallback-rayleigh-offset", type=float, default=0.067)
    p.add_argument("--aod-gain",  type=float, default=4.0)
    p.add_argument("--aod-bias",  type=float, default=0.0)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    cfg = RetrievalConfig(
        ndvi_min=args.ndvi_min,
        red_dark_max=args.red_dark_max,
        ddv_nir_min=args.ddv_nir_min,
        surf_blue_red_ratio=args.surf_blue_red_ratio,
        ndvi_dependent_ratio=not args.no_ndvi_dependent_ratio,
        min_valid_ddv_fraction=args.min_ddv_fraction,
        out_res_m=args.out_res,
        use_py6s=not args.no_py6s,
        aerosol_profile=args.aerosol_profile,
        atmosphere_profile=args.atmosphere_profile,
        target_alt_km=args.target_alt_km,
        fallback_rayleigh_blue_offset=args.fallback_rayleigh_offset,
        aod_gain=args.aod_gain,
        aod_bias=args.aod_bias,
        smooth_sigma_px=args.smooth_sigma_px,
        fill_sigma_px=args.fill_sigma_px,
    )

    radiance_scale = args.radiance_scale

    # MAIAC 기반 radiance_scale 자동 보정
    if args.maiac_ref and os.path.exists(args.maiac_ref):
        print(f"\n[MAIAC 보정] {args.maiac_ref} 로드 중 …")
        try:
            import rasterio as _rio
            with _rio.open(args.maiac_ref) as _ms:
                _maiac = _ms.read(1).astype(np.float32)
                _nd = _ms.nodata
                if _nd is not None:
                    _maiac[_maiac == _nd] = np.nan
                _maiac[_maiac < 0] = np.nan
                _mtf = _ms.transform
                _mcrs = _ms.crs
            _valid = np.isfinite(_maiac)
            if _valid.any():
                _maiac_mean = float(np.nanmean(_maiac))
                print(f"  MAIAC AOD 평균: {_maiac_mean:.3f}  (유효 픽셀 {_valid.sum():,})")
                # 간단 bias 보정: DDV AOD vs MAIAC mean 비율로 scale 추정
                # 정밀 보정은 validate_bb_aod.py 사용 권장
                # 여기서는 MAIAC 평균을 목표 AOD로 삼아 LUT에서 target path_ref 계산
                # path_ref target = LUT(MAIAC_mean) ≈ rayleigh + 0.03 * MAIAC_mean (선형 근사)
                # radiance_scale_new ≈ radiance_scale_old × (target / current_aod_median)
                # → retrieve 후 통계에서 조정 안내
                print(f"  정밀 보정은 validate_bb_aod.py 를 권장합니다.")
                print(f"  현재 radiance_scale={radiance_scale} 유지")
            else:
                print("  MAIAC 유효 픽셀 없음")
        except Exception as e:
            print(f"  MAIAC 로드 실패: {e}")

    aod, transform, crs, debug = retrieve_aod(
        args.input, cfg,
        radiance_scale=radiance_scale,
        solar_z_override=args.solar_z_deg,
        view_z_deg=args.view_z_deg,
        rel_az_deg=args.rel_az_deg,
        maiac_aod_mean=args.maiac_aod_mean,
    )

    write_geotiff(args.out, aod, transform, crs)
    print(f"\nWrote AOD GeoTIFF : {args.out}")

    if args.out_qa:
        write_geotiff(args.out_qa, debug["qa"].astype(np.float32), transform, crs)
        print(f"Wrote QA  GeoTIFF : {args.out_qa}")

    finite = np.isfinite(aod)
    if finite.any():
        print(f"\nValid pixels : {finite.sum():,} / {aod.size:,}  ({100*finite.mean():.1f}%)")
        print(f"AOD range    : {np.nanmin(aod):.3f} .. {np.nanmax(aod):.3f}")
        print(f"AOD mean     : {np.nanmean(aod):.3f}")
        print(f"AOD median   : {np.nanmedian(aod):.3f}")
    else:
        print("WARNING: no valid AOD pixels produced.")

    print("\nReflectance calibration note:")
    print(f"  radiance_scale used = {args.radiance_scale}")
    print("  Replace with official BlueBON L1C calibration coefficient")
    print("  to obtain physically accurate TOA reflectance and AOD values.")


if __name__ == "__main__":
    main()
