from __future__ import annotations

"""
Prototype Sentinel-2 AOD retrieval from Level-1C reflectance.

What this does
--------------
- Reads Sentinel-2 JP2 bands from an L1C SAFE directory.
- Builds a simple cloud / water / snow mask.
- Selects dark-dense-vegetation (DDV) candidates using NDVI and SWIR.
- Estimates surface blue reflectance from SWIR using an empirical relation.
- Computes a proxy aerosol path reflectance in the blue band.
- Converts that proxy to AOD(550) using a configurable linear calibration.
- Optionally resamples the result to a coarser grid and writes GeoTIFF.

What this does NOT do
---------------------
- It is NOT an official Sentinel-2 AOD processor.
- It does NOT use full radiative transfer inversion or VLIDORT/6S LUTs.
- The surface-reflectance relation and path-reflectance to AOD mapping must be
  calibrated for your study region and atmospheric model using AERONET / RTM.

Recommended use
---------------
- Use this as a research baseline or scaffolding.
- Replace `estimate_surface_blue_from_swir()` and `path_reflectance_to_aod()`
  with your calibrated equations or LUT interpolation.

Dependencies
------------
    pip install rasterio numpy scipy

Example
-------
    python sentinel2_aod_retrieval.py \
        --safe /data/S2A_MSIL1C_20260101T023541_N0511_R046_T52SDG_20260101T043212.SAFE \
        --out /data/s2_aod550.tif
"""

import argparse
import glob
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from scipy.ndimage import gaussian_filter


# Sentinel-2 Level-1C reflectance scale factor.
S2_SCALE = 10000.0

# Central wavelengths used in comments / documentation.
S2_BANDS = {
    "B02": 490,   # Blue, 10 m
    "B03": 560,   # Green, 10 m
    "B04": 665,   # Red, 10 m
    "B08": 842,   # NIR, 10 m
    "B11": 1610,  # SWIR1, 20 m
    "B12": 2190,  # SWIR2, 20 m
}


@dataclass
class BandData:
    array: np.ndarray
    transform: Affine
    crs: object
    nodata: Optional[float]


@dataclass
class RetrievalConfig:
    # DDV selection
    ndvi_min: float = 0.5
    swir1_max: float = 0.10

    # Simple cloud / bright mask thresholds
    blue_cloud_thresh: float = 0.25
    cirrus_like_swir2_thresh: float = 0.10
    snow_ndsi_thresh: float = 0.4
    snow_green_thresh: float = 0.2
    water_ndvi_thresh: float = 0.05
    water_nir_thresh: float = 0.05

    # Empirical surface relation over DDV:
    # rho_surf_blue = a * rho_swir1 + b
    surf_blue_a: float = 0.50
    surf_blue_b: float = 0.005

    # Optional Rayleigh/background offset in blue TOA reflectance.
    # In a full algorithm this should come from RTM.
    rayleigh_blue_offset: float = 0.02

    # Convert aerosol path reflectance to AOD550:
    # AOD550 = max(0, gain * rho_aero_blue + bias)
    aod_gain: float = 4.0
    aod_bias: float = 0.0

    # Spatial filtering / fill
    smooth_sigma_px: float = 1.0
    min_valid_ddv_fraction: float = 0.0004

    # Output resolution in meters.
    out_res: int = 20


class Sentinel2L1CReader:
    def __init__(self, safe_dir: str):
        self.safe_dir = safe_dir
        self.band_paths = self._discover_band_paths()

    def _discover_band_paths(self) -> Dict[str, str]:
        pattern = os.path.join(self.safe_dir, "**", "IMG_DATA", "**", "*.jp2")
        paths = glob.glob(pattern, recursive=True)
        if not paths:
            raise FileNotFoundError(f"No JP2 files found under: {self.safe_dir}")

        band_paths: Dict[str, str] = {}
        for path in paths:
            name = os.path.basename(path)
            for band in S2_BANDS:
                if re.search(rf"_{band}(?:_|\.)", name):
                    band_paths[band] = path

        missing = [band for band in ["B02", "B03", "B04", "B08", "B11", "B12"] if band not in band_paths]
        if missing:
            raise FileNotFoundError(f"Missing required Sentinel-2 bands: {missing}")
        return band_paths

    def read_band(self, band: str) -> BandData:
        path = self.band_paths[band]
        with rasterio.open(path) as src:
            arr = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            arr /= S2_SCALE
            return BandData(arr, src.transform, src.crs, nodata)


def resample_to_match(src_band: BandData, dst_band: BandData, resampling: Resampling = Resampling.bilinear) -> np.ndarray:
    dst = np.full(dst_band.array.shape, np.nan, dtype=np.float32)
    reproject(
        source=src_band.array,
        destination=dst,
        src_transform=src_band.transform,
        src_crs=src_band.crs,
        dst_transform=dst_band.transform,
        dst_crs=dst_band.crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=resampling,
    )
    return dst


def compute_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    denom = nir + red
    ndvi = np.full_like(nir, np.nan, dtype=np.float32)
    valid = np.isfinite(denom) & (np.abs(denom) > 1e-6)
    ndvi[valid] = (nir[valid] - red[valid]) / denom[valid]
    return ndvi


def compute_ndsi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    denom = green + swir1
    ndsi = np.full_like(green, np.nan, dtype=np.float32)
    valid = np.isfinite(denom) & (np.abs(denom) > 1e-6)
    ndsi[valid] = (green[valid] - swir1[valid]) / denom[valid]
    return ndsi


def build_masks(
    blue: np.ndarray,
    green: np.ndarray,
    red: np.ndarray,
    nir: np.ndarray,
    swir1: np.ndarray,
    swir2: np.ndarray,
    cfg: RetrievalConfig,
) -> Dict[str, np.ndarray]:
    ndvi = compute_ndvi(nir, red)
    print(ndvi.max(),ndvi.min())
    ndsi = compute_ndsi(green, swir1)

    cloud = (
        (blue > cfg.blue_cloud_thresh)
        | ((swir2 > cfg.cirrus_like_swir2_thresh) & (blue > 0.18))
    )
    snow = (ndsi > cfg.snow_ndsi_thresh) & (green > cfg.snow_green_thresh)
    water = (ndvi < cfg.water_ndvi_thresh) & (nir < cfg.water_nir_thresh)
    invalid = ~np.isfinite(blue) | ~np.isfinite(green) | ~np.isfinite(red) | ~np.isfinite(nir) | ~np.isfinite(swir1) | ~np.isfinite(swir2)

    return {
        "ndvi": ndvi,
        "ndsi": ndsi,
        "cloud": cloud,
        "snow": snow,
        "water": water,
        "invalid": invalid,
    }


def select_ddv(ndvi: np.ndarray, swir1: np.ndarray, masks: Dict[str, np.ndarray], cfg: RetrievalConfig) -> np.ndarray:
    ddv = (
        (ndvi >= cfg.ndvi_min)
        & (swir1 <= cfg.swir1_max)
        & ~masks["cloud"]
        & ~masks["snow"]
        & ~masks["water"]
        & ~masks["invalid"]
    )
    return ddv


def estimate_surface_blue_from_swir(swir1: np.ndarray, cfg: RetrievalConfig) -> np.ndarray:
    surf_blue = cfg.surf_blue_a * swir1 + cfg.surf_blue_b
    return np.clip(surf_blue, 0.0, 0.2)


def estimate_aerosol_path_reflectance(blue_toa: np.ndarray, surf_blue: np.ndarray, cfg: RetrievalConfig) -> np.ndarray:
    rho_aero = blue_toa - surf_blue - cfg.rayleigh_blue_offset
    return np.clip(rho_aero, 0.0, None)


def path_reflectance_to_aod(rho_aero_blue: np.ndarray, cfg: RetrievalConfig) -> np.ndarray:
    aod = cfg.aod_gain * rho_aero_blue + cfg.aod_bias
    return np.clip(aod, 0.0, 5.0)


def fill_from_ddv(aod_ddv: np.ndarray, ddv_mask: np.ndarray) -> np.ndarray:
    """
    Simple spatial propagation from DDV pixels to nearby pixels.
    This is a placeholder for a better interpolation / model-based propagation.
    """
    valid = ddv_mask & np.isfinite(aod_ddv)
    if valid.sum() == 0:
        return np.full_like(aod_ddv, np.nan, dtype=np.float32)

    weights = valid.astype(np.float32)
    values = np.where(valid, aod_ddv, 0.0).astype(np.float32)

    num = gaussian_filter(values, sigma=6.0)
    den = gaussian_filter(weights, sigma=6.0)
    out = np.full_like(aod_ddv, np.nan, dtype=np.float32)
    good = den > 1e-4
    out[good] = num[good] / den[good]
    return out


def downsample_mean(arr: np.ndarray, src_transform: Affine, src_crs: object, out_res: int) -> Tuple[np.ndarray, Affine]:
    if out_res == 10:
        return arr.astype(np.float32), src_transform

    scale = out_res / 10.0
    out_h = int(np.ceil(arr.shape[0] / scale))
    out_w = int(np.ceil(arr.shape[1] / scale))
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


def write_geotiff(path: str, arr: np.ndarray, transform: Affine, crs: object) -> None:
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


def retrieve_aod(safe_dir: str, cfg: RetrievalConfig) -> Tuple[np.ndarray, Affine, object, Dict[str, np.ndarray]]:
    reader = Sentinel2L1CReader(safe_dir)

    b02 = reader.read_band("B02")
    b03 = reader.read_band("B03")
    b04 = reader.read_band("B04")
    b08 = reader.read_band("B08")
    b11 = reader.read_band("B11")
    b12 = reader.read_band("B12")

    swir1 = resample_to_match(b11, b02, resampling=Resampling.bilinear)
    swir2 = resample_to_match(b12, b02, resampling=Resampling.bilinear)

    masks = build_masks(b02.array, b03.array, b04.array, b08.array, swir1, swir2, cfg)
    ddv = select_ddv(masks["ndvi"], swir1, masks, cfg)

    ddv_fraction = float(ddv.sum()) / float(ddv.size)

    if ddv_fraction < cfg.min_valid_ddv_fraction:
        raise RuntimeError(
            f"Too few DDV pixels for stable retrieval: {ddv.sum()}, {ddv_fraction:.4%}. "
            "Try a more vegetated scene or relax thresholds."
        )

    surf_blue = estimate_surface_blue_from_swir(swir1, cfg)
    rho_aero = estimate_aerosol_path_reflectance(b02.array, surf_blue, cfg)
    aod_ddv = np.where(ddv, path_reflectance_to_aod(rho_aero, cfg), np.nan).astype(np.float32)

    aod_full = fill_from_ddv(aod_ddv, ddv)
    aod_full[masks["cloud"] | masks["snow"] | masks["invalid"]] = np.nan
    aod_full = gaussian_filter(np.nan_to_num(aod_full, nan=0.0), sigma=cfg.smooth_sigma_px)

    invalid_after = masks["cloud"] | masks["snow"] | masks["invalid"]
    aod_full = aod_full.astype(np.float32)
    aod_full[invalid_after] = np.nan
    aod_full = np.clip(aod_full, 0.0, 5.0)

    out_arr, out_transform = downsample_mean(aod_full, b02.transform, b02.crs, cfg.out_res)
    qa = np.zeros_like(aod_full, dtype=np.uint8)
    qa[ddv] = 1
    qa[masks["water"]] = 2
    qa[masks["cloud"]] = 3
    qa[masks["snow"]] = 4
    qa[masks["invalid"]] = 255
    qa_ds, _ = downsample_mean(qa.astype(np.float32), b02.transform, b02.crs, cfg.out_res)

    debug = {
        "ddv_mask": ddv,
        "rho_aero_blue": rho_aero,
        "surface_blue": surf_blue,
        "qa": qa_ds,
    }
    return out_arr, out_transform, b02.crs, debug


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prototype Sentinel-2 AOD retrieval from L1C SAFE")
    p.add_argument("--safe", required=True, help="Path to Sentinel-2 L1C SAFE directory")
    p.add_argument("--out", required=True, help="Output GeoTIFF path for AOD550")
    p.add_argument("--out-qa", default=None, help="Optional output GeoTIFF path for QA")
    p.add_argument("--ndvi-min", type=float, default=0.3)
    p.add_argument("--swir1-max", type=float, default=0.50)
    p.add_argument("--surf-blue-a", type=float, default=0.50)
    p.add_argument("--surf-blue-b", type=float, default=0.005)
    p.add_argument("--rayleigh-blue-offset", type=float, default=0.02)
    p.add_argument("--aod-gain", type=float, default=4.0)
    p.add_argument("--aod-bias", type=float, default=0.0)
    p.add_argument("--out-res", type=int, default=20, choices=[10, 20, 60])
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = RetrievalConfig(
        ndvi_min=args.ndvi_min,
        swir1_max=args.swir1_max,
        surf_blue_a=args.surf_blue_a,
        surf_blue_b=args.surf_blue_b,
        rayleigh_blue_offset=args.rayleigh_blue_offset,
        aod_gain=args.aod_gain,
        aod_bias=args.aod_bias,
        out_res=args.out_res,
    )

    aod, transform, crs, debug = retrieve_aod(args.safe, cfg)
    write_geotiff(args.out, aod, transform, crs)

    if args.out_qa:
        write_geotiff(args.out_qa, debug["qa"].astype(np.float32), transform, crs)

    finite = np.isfinite(aod)
    if finite.any():
        print(f"Wrote: {args.out}")
        print(f"Valid pixels: {finite.sum()} / {aod.size}")
        print(f"AOD range: {np.nanmin(aod):.3f} .. {np.nanmax(aod):.3f}")
        print(f"AOD mean : {np.nanmean(aod):.3f}")
    else:
        print("Wrote output, but no valid AOD pixels were produced.")


if __name__ == "__main__":
    main()
