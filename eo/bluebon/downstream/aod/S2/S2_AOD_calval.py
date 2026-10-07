from __future__ import annotations

"""
Prototype Sentinel-2 AOD retrieval with Py6S physics and MODIS MCD19A2 validation.

Key improvements over previous version
---------------------------------------
- Parses solar/view angles automatically from SAFE MTD_TL.xml (no manual input needed)
- Selects atmosphere profile automatically from scene month and latitude
- Builds a multi-AOT 6S LUT for physics-based path-reflectance-to-AOD inversion
- Applies one-iteration transmittance correction for the surface contribution
- Removes incorrect fallback Rayleigh offset (0.02 is wrong for solar_z ~50 deg)

External requirements
---------------------
    pip install rasterio numpy scipy pyproj earthaccess pyhdf Py6S

Example
-------
python S2_AOD_calval.py \\
  --safe S2C_MSIL1C_20260225T021651_N0512_R003_T52SCG_20260225T041634.SAFE \\
  --out aod_output.tif \\
  --run-validation \\
  --earthdata-username YOUR_USER \\
  --earthdata-password YOUR_PASS
"""

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import glob
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.transform import Affine, array_bounds
from rasterio.warp import reproject
from scipy.ndimage import gaussian_filter

S2_SCALE = 10000.0
S2_BANDS = {
    "B02": 490,
    "B03": 560,
    "B04": 665,
    "B08": 842,
    "B11": 1610,
    "B12": 2190,
}

# Rayleigh optical depth at 490 nm (standard atmosphere, Bodhaine et al. 1999)
_TAU_RAY_490 = 0.133
# Ångström exponent for 550→490 nm aerosol scaling
_ANGSTROM = 1.3


# ---------------------------------------------------------------------------
# Optional dependency imports
# ---------------------------------------------------------------------------

def try_import_py6s():
    try:
        from Py6S import SixS, AtmosProfile, AeroProfile, Geometry, Wavelength, GroundReflectance
        return SixS, AtmosProfile, AeroProfile, Geometry, Wavelength, GroundReflectance
    except Exception:
        return None


def try_import_earthaccess():
    try:
        import earthaccess
        return earthaccess
    except Exception:
        return None


def try_import_pyhdf():
    try:
        from pyhdf.SD import SD, SDC
        return SD, SDC
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BandData:
    array: np.ndarray
    transform: Affine
    crs: object
    nodata: Optional[float]


@dataclass
class RetrievalConfig:
    # DDV selection thresholds
    ndvi_min: float = 0.25
    swir1_max: float = 0.22

    # Mask thresholds
    blue_cloud_thresh: float = 0.25
    snow_ndsi_thresh: float = 0.4
    snow_green_thresh: float = 0.2
    water_ndvi_thresh: float = 0.05
    water_nir_thresh: float = 0.05

    # Surface blue from SWIR: rho_surf_blue = a * rho_swir1 + b
    surf_blue_a: float = 0.50
    surf_blue_b: float = 0.005

    # Fallback calibration used only when Py6S is unavailable
    fallback_rayleigh_blue_offset: float = 0.02
    aod_gain: float = 4.0
    aod_bias: float = 0.0

    # Spatial filtering
    smooth_sigma_px: float = 3.0
    fill_sigma_px: float = 300.0
    min_valid_ddv_fraction: float = 0.001
    out_res: int = 20

    # 6S configuration
    use_py6s: bool = True
    aerosol_profile: str = "continental"
    atmosphere_profile: str = "auto"   # "auto" = derived from scene date + latitude
    target_alt_km: float = 0.0
    sensor_alt_satellite: bool = True

    # AOT sampling nodes for the 6S LUT
    lut_aot_nodes: Tuple[float, ...] = (0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0)

    # MODIS validation
    modis_collection: str = "MCD19A2"
    modis_version: str = "061"


@dataclass
class SixSLUT:
    """Lookup table: AOT (at 550 nm) → atmospheric path reflectance at 490 nm."""
    aot_nodes: np.ndarray
    path_ref: np.ndarray
    rayleigh_offset: float = 0.0   # path_ref extrapolated to AOT=0

    @property
    def is_valid(self) -> bool:
        return len(self.aot_nodes) >= 2 and len(self.path_ref) >= 2


# ---------------------------------------------------------------------------
# Sentinel-2 reader
# ---------------------------------------------------------------------------

class Sentinel2L1CReader:
    def __init__(self, safe_dir: str):
        self.safe_dir = safe_dir
        self.band_paths = self._discover_band_paths()
        self._angles: Optional[Dict[str, float]] = None

    def _discover_band_paths(self) -> Dict[str, str]:
        pattern = os.path.join(self.safe_dir, "**", "IMG_DATA", "**", "*.jp2")
        paths = glob.glob(pattern, recursive=True)
        if not paths:
            pattern = os.path.join(self.safe_dir, "**", "IMG_DATA", "*.jp2")
            paths = glob.glob(pattern, recursive=True)
        if not paths:
            raise FileNotFoundError(f"No JP2 files found under: {self.safe_dir}")

        band_paths: Dict[str, str] = {}
        for path in paths:
            name = os.path.basename(path)
            for band in S2_BANDS:
                if re.search(rf"_{band}(?:_|\.)", name):
                    band_paths[band] = path

        missing = [b for b in ["B02", "B03", "B04", "B08", "B11", "B12"] if b not in band_paths]
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

    def read_scene_time(self) -> datetime:
        m = re.search(r"_(\d{8}T\d{6})_", os.path.basename(self.safe_dir.rstrip("/")))
        if m:
            return datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        raise ValueError("Could not parse sensing time from SAFE directory name.")

    def read_scene_angles(self) -> Dict[str, float]:
        """Parse mean solar/view angles from MTD_TL.xml inside the SAFE package.

        Returns dict with solar_z, solar_az, view_z, view_az, rel_az (degrees).
        Falls back to conservative defaults when metadata is missing.
        """
        if self._angles is not None:
            return self._angles

        defaults = {"solar_z": 30.0, "solar_az": 0.0, "view_z": 0.0, "view_az": 0.0, "rel_az": 0.0}

        mtd_paths = glob.glob(os.path.join(self.safe_dir, "**", "MTD_TL.xml"), recursive=True)
        if not mtd_paths:
            self._angles = defaults
            return self._angles

        def _tag(elem) -> str:
            t = elem.tag
            return t.split("}")[-1] if "}" in t else t

        try:
            root = ET.parse(mtd_paths[0]).getroot()
            solar_z: Optional[float] = None
            solar_az: Optional[float] = None
            view_z_vals: List[float] = []
            view_az_vals: List[float] = []

            for elem in root.iter():
                t = _tag(elem)
                if t == "Mean_Sun_Angle":
                    for child in elem:
                        ct = _tag(child)
                        if ct == "ZENITH_ANGLE" and child.text:
                            solar_z = float(child.text)
                        elif ct == "AZIMUTH_ANGLE" and child.text:
                            solar_az = float(child.text)
                elif t == "Mean_Viewing_Incidence_Angle":
                    for child in elem:
                        ct = _tag(child)
                        try:
                            if ct == "ZENITH_ANGLE" and child.text:
                                view_z_vals.append(float(child.text))
                            elif ct == "AZIMUTH_ANGLE" and child.text:
                                view_az_vals.append(float(child.text))
                        except (ValueError, TypeError):
                            pass

            if solar_z is None or solar_az is None:
                self._angles = defaults
                return self._angles

            view_z = float(np.mean(view_z_vals)) if view_z_vals else 0.0
            view_az = float(np.mean(view_az_vals)) if view_az_vals else 0.0

            rel_az = abs(solar_az - view_az)
            if rel_az > 180.0:
                rel_az = 360.0 - rel_az

            self._angles = {
                "solar_z": float(solar_z),
                "solar_az": float(solar_az),
                "view_z": float(view_z),
                "view_az": float(view_az),
                "rel_az": float(rel_az),
            }
        except Exception as exc:
            print(f"  WARNING: angle metadata parse failed ({exc}); using defaults.")
            self._angles = defaults

        return self._angles


# ---------------------------------------------------------------------------
# Index / mask helpers
# ---------------------------------------------------------------------------

def resample_to_match(src_band: BandData, dst_band: BandData,
                      resampling: Resampling = Resampling.bilinear) -> np.ndarray:
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
    out = np.full_like(nir, np.nan, dtype=np.float32)
    valid = np.isfinite(denom) & (np.abs(denom) > 1e-6)
    out[valid] = (nir[valid] - red[valid]) / denom[valid]
    return out


def compute_ndsi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    denom = green + swir1
    out = np.full_like(green, np.nan, dtype=np.float32)
    valid = np.isfinite(denom) & (np.abs(denom) > 1e-6)
    out[valid] = (green[valid] - swir1[valid]) / denom[valid]
    return out


def build_masks(blue, green, red, nir, swir1, swir2,
                cfg: RetrievalConfig) -> Dict[str, np.ndarray]:
    ndvi = compute_ndvi(nir, red)
    ndsi = compute_ndsi(green, swir1)

    # Thick-cloud detection: blue reflectance only.
    # The previously used (swir2 > 0.10) & (blue > 0.18) condition is WRONG for
    # land scenes: soil and vegetation normally have SWIR2 > 0.10, so this
    # condition flags virtually all land pixels as cloud.
    cloud = blue > cfg.blue_cloud_thresh

    snow = (ndsi > cfg.snow_ndsi_thresh) & (green > cfg.snow_green_thresh)
    water = (ndvi < cfg.water_ndvi_thresh) & (nir < cfg.water_nir_thresh)
    invalid = (
        ~np.isfinite(blue) | ~np.isfinite(green) | ~np.isfinite(red)
        | ~np.isfinite(nir) | ~np.isfinite(swir1) | ~np.isfinite(swir2)
    )
    return {"ndvi": ndvi, "ndsi": ndsi, "cloud": cloud,
            "snow": snow, "water": water, "invalid": invalid}


def select_ddv(ndvi: np.ndarray, swir1: np.ndarray,
               masks: Dict[str, np.ndarray], cfg: RetrievalConfig) -> np.ndarray:
    return (
        (ndvi >= cfg.ndvi_min)
        & (swir1 <= cfg.swir1_max)
        & ~masks["cloud"]
        & ~masks["snow"]
        & ~masks["water"]
        & ~masks["invalid"]
    )


def estimate_surface_blue_from_swir(swir1: np.ndarray,
                                    cfg: RetrievalConfig) -> np.ndarray:
    return np.clip(cfg.surf_blue_a * swir1 + cfg.surf_blue_b, 0.0, 0.2)


# ---------------------------------------------------------------------------
# 6S profile helpers
# ---------------------------------------------------------------------------

def _map_aero_profile(name: str):
    imported = try_import_py6s()
    if imported is None:
        return None
    _, _, AeroProfile, _, _, _ = imported
    return {
        "continental": AeroProfile.Continental,
        "maritime": AeroProfile.Maritime,
        "urban": AeroProfile.Urban,
        "desert": AeroProfile.Desert,
    }.get(name.lower(), AeroProfile.Continental)


def _map_atmos_profile(name: str):
    imported = try_import_py6s()
    if imported is None:
        return None
    _, AtmosProfile, _, _, _, _ = imported
    return {
        "midlatitude_summer": AtmosProfile.MidlatitudeSummer,
        "midlatitude_winter": AtmosProfile.MidlatitudeWinter,
        "tropical": AtmosProfile.Tropical,
        "subarctic_summer": AtmosProfile.SubarcticSummer,
        "subarctic_winter": AtmosProfile.SubarcticWinter,
    }.get(name.lower(), AtmosProfile.MidlatitudeSummer)


def auto_atmosphere_profile(scene_time: datetime, lat: float) -> str:
    """Choose atmosphere profile from scene month and latitude."""
    month = scene_time.month
    if lat > 60:
        return "subarctic_winter" if month in (11, 12, 1, 2, 3, 4) else "subarctic_summer"
    elif lat > 30:
        return "midlatitude_winter" if month in (11, 12, 1, 2, 3) else "midlatitude_summer"
    else:
        return "tropical"


# ---------------------------------------------------------------------------
# Scene geometry
# ---------------------------------------------------------------------------

def estimate_scene_center(transform: Affine, width: int, height: int,
                          crs_obj) -> Tuple[float, float]:
    left, bottom, right, top = array_bounds(height, width, transform)
    x = 0.5 * (left + right)
    y = 0.5 * (bottom + top)
    transformer = Transformer.from_crs(crs_obj, "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x, y)
    return float(lat), float(lon)


# ---------------------------------------------------------------------------
# 6S LUT construction and AOD inversion
# ---------------------------------------------------------------------------

def build_6s_blue_lut(
    solar_z: float,
    view_z: float,
    rel_az: float,
    target_alt_km: float,
    cfg: RetrievalConfig,
) -> SixSLUT:
    """Run 6S at multiple AOT values to build path-reflectance LUT at 490 nm.

    Ground reflectance is set to zero so the output is the atmospheric
    intrinsic (path) reflectance: Rayleigh + aerosol scattering with no
    surface contribution.
    """
    _fallback = SixSLUT(
        aot_nodes=np.array([0.01, 2.0]),
        path_ref=np.array([
            cfg.fallback_rayleigh_blue_offset,
            cfg.fallback_rayleigh_blue_offset + 0.25,
        ]),
        rayleigh_offset=cfg.fallback_rayleigh_blue_offset,
    )

    if not cfg.use_py6s:
        print("  Py6S disabled — using fallback linear LUT.")
        return _fallback

    imported = try_import_py6s()
    if imported is None:
        print("  Py6S not available — using fallback linear LUT.")
        return _fallback

    SixS, AtmosProfile, AeroProfile, Geometry, Wavelength, GroundReflectance = imported
    atmos = _map_atmos_profile(cfg.atmosphere_profile)
    aero = _map_aero_profile(cfg.aerosol_profile)
    if atmos is None or aero is None:
        return _fallback

    aot_vals: List[float] = []
    path_ref_vals: List[float] = []

    n = len(cfg.lut_aot_nodes)
    print(f"  Building 6S LUT ({n} runs) at 490 nm …", flush=True)
    for aot in cfg.lut_aot_nodes:
        try:
            s = SixS()
            s.geometry = Geometry.User()
            s.geometry.solar_z = float(solar_z)
            s.geometry.view_z = float(view_z)
            s.geometry.solar_a = 0.0
            s.geometry.view_a = float(rel_az)
            s.atmos_profile = AtmosProfile.PredefinedType(atmos)
            s.aero_profile = AeroProfile.PredefinedType(aero)
            s.aot550 = float(max(aot, 0.001))
            s.wavelength = Wavelength(0.490)
            if cfg.sensor_alt_satellite:
                s.altitudes.set_sensor_satellite_level()
            else:
                s.altitudes.set_sensor_custom_altitude(705)
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
        print("  WARNING: too few valid 6S runs; falling back to linear LUT.")
        return _fallback

    aot_arr = np.array(aot_vals, dtype=np.float64)
    path_arr = np.array(path_ref_vals, dtype=np.float64)

    # Extrapolate to AOT=0 to isolate the Rayleigh contribution
    rayleigh = float(np.interp(0.0, aot_arr, path_arr))

    print(f"  Rayleigh offset at 490 nm (AOT→0): {rayleigh:.5f}")
    return SixSLUT(aot_nodes=aot_arr, path_ref=path_arr, rayleigh_offset=rayleigh)


def _two_way_transmittance_490(aot550: np.ndarray,
                               mu_s: float, mu_v: float) -> np.ndarray:
    """Beer-Lambert two-way transmittance at 490 nm (Rayleigh + aerosol)."""
    tau_aero = np.asarray(aot550, dtype=np.float64) * (490.0 / 550.0) ** _ANGSTROM
    tau_total = _TAU_RAY_490 + tau_aero
    return np.exp(-tau_total * (1.0 / mu_s + 1.0 / mu_v)).astype(np.float32)


def invert_aod_from_lut(
    blue_toa: np.ndarray,
    surf_blue: np.ndarray,
    lut: SixSLUT,
    solar_z_deg: float,
    view_z_deg: float,
) -> np.ndarray:
    """Physics-based LUT inversion: blue TOA reflectance → AOD.

    One Newton iteration to account for the surface contribution:
      rho_toa ≈ rho_path(AOD) + T(AOD) * rho_surf
    where T is the two-way transmittance at 490 nm.
    """
    mu_s = max(float(np.cos(np.radians(solar_z_deg))), 0.01)
    mu_v = max(float(np.cos(np.radians(view_z_deg))), 0.01)

    aot_n = lut.aot_nodes.astype(np.float64)
    pr_n = lut.path_ref.astype(np.float64)

    blue = blue_toa.astype(np.float64)
    surf = surf_blue.astype(np.float64)

    # Iteration 0: ignore surface contribution
    rho0 = np.clip(blue - surf, 0.0, None)
    aod0 = np.interp(rho0, pr_n, aot_n, left=0.0, right=aot_n[-1])

    # Iteration 1: subtract surface * transmittance(AOD₀)
    trans = _two_way_transmittance_490(aod0, mu_s, mu_v).astype(np.float64)
    rho1 = np.clip(blue - surf * trans, 0.0, None)
    aod1 = np.interp(rho1, pr_n, aot_n, left=0.0, right=aot_n[-1])

    return np.clip(aod1, 0.0, 5.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Fallback linear helpers (used when Py6S unavailable)
# ---------------------------------------------------------------------------

def estimate_aerosol_path_reflectance(blue_toa: np.ndarray, surf_blue: np.ndarray,
                                      rayleigh_offset: float) -> np.ndarray:
    return np.clip(blue_toa - surf_blue - float(rayleigh_offset), 0.0, None)


def path_reflectance_to_aod(rho_aero: np.ndarray, cfg: RetrievalConfig) -> np.ndarray:
    return np.clip(cfg.aod_gain * rho_aero + cfg.aod_bias, 0.0, 5.0)


# ---------------------------------------------------------------------------
# Spatial fill and output
# ---------------------------------------------------------------------------

def fill_from_ddv(aod_ddv: np.ndarray, ddv_mask: np.ndarray,
                  sigma: float = 6.0) -> np.ndarray:
    valid = ddv_mask & np.isfinite(aod_ddv)
    if valid.sum() == 0:
        return np.full_like(aod_ddv, np.nan, dtype=np.float32)
    weights = valid.astype(np.float32)
    values = np.where(valid, aod_ddv, 0.0).astype(np.float32)
    num = gaussian_filter(values, sigma=sigma)
    den = gaussian_filter(weights, sigma=sigma)
    out = np.full_like(aod_ddv, np.nan, dtype=np.float32)
    good = den > 1e-4
    out[good] = num[good] / den[good]
    return out


def downsample_mean(arr: np.ndarray, src_transform: Affine, src_crs,
                    out_res: int) -> Tuple[np.ndarray, Affine]:
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


def write_geotiff(path: str, arr: np.ndarray, transform: Affine, crs) -> None:
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
# Main retrieval pipeline
# ---------------------------------------------------------------------------

def retrieve_aod(
    safe_dir: str,
    cfg: RetrievalConfig,
    solar_z_deg: Optional[float] = None,
    view_z_deg: Optional[float] = None,
    rel_az_deg: Optional[float] = None,
):
    reader = Sentinel2L1CReader(safe_dir)
    scene_time = reader.read_scene_time()

    # --- Geometry: prefer explicit overrides, otherwise parse from metadata ---
    angles = reader.read_scene_angles()
    sz = solar_z_deg if solar_z_deg is not None else angles["solar_z"]
    vz = view_z_deg if view_z_deg is not None else angles["view_z"]
    ra = rel_az_deg if rel_az_deg is not None else angles["rel_az"]

    print(f"Scene time   : {scene_time.isoformat()}")
    print(f"Geometry     : solar_z={sz:.2f}°  view_z={vz:.2f}°  rel_az={ra:.2f}°")
    if solar_z_deg is None:
        print("               (angles parsed from MTD_TL.xml)")

    # --- Read bands ---
    b02 = reader.read_band("B02")
    b03 = reader.read_band("B03")
    b04 = reader.read_band("B04")
    b08 = reader.read_band("B08")
    b11 = reader.read_band("B11")
    b12 = reader.read_band("B12")

    swir1 = resample_to_match(b11, b02, resampling=Resampling.bilinear)
    swir2 = resample_to_match(b12, b02, resampling=Resampling.bilinear)

    # --- Auto atmosphere profile ---
    atmos_profile = cfg.atmosphere_profile
    if atmos_profile == "auto":
        scene_lat, scene_lon = estimate_scene_center(
            b02.transform, b02.array.shape[1], b02.array.shape[0], b02.crs
        )
        atmos_profile = auto_atmosphere_profile(scene_time, scene_lat)
        print(f"Atmosphere   : {atmos_profile}  (auto, lat={scene_lat:.1f}°, month={scene_time.month})")
        cfg.atmosphere_profile = atmos_profile
    else:
        print(f"Atmosphere   : {atmos_profile}")

    print(f"Aerosol type : {cfg.aerosol_profile}")

    # --- Masks and DDV selection ---
    masks = build_masks(b02.array, b03.array, b04.array, b08.array, swir1, swir2, cfg)
    ddv = select_ddv(masks["ndvi"], swir1, masks, cfg)

    ddv_frac = float(ddv.sum()) / float(ddv.size)
    cloud_frac = float(masks["cloud"].mean())
    snow_frac = float(masks["snow"].mean())
    clear_frac = float((~masks["cloud"] & ~masks["snow"] & ~masks["invalid"]).mean())

    ndvi_vals = masks["ndvi"][np.isfinite(masks["ndvi"])]
    print(f"Scene fractions: cloud={cloud_frac:.1%}  snow={snow_frac:.1%}  clear={clear_frac:.1%}")
    if ndvi_vals.size > 0:
        print(f"NDVI range   : {ndvi_vals.min():.3f} .. {ndvi_vals.max():.3f}  "
              f"mean={ndvi_vals.mean():.3f}")

    # Detailed DDV rejection breakdown for diagnostics
    usable = ~masks["cloud"] & ~masks["snow"] & ~masks["water"] & ~masks["invalid"]
    n_ndvi_ok = int(((masks["ndvi"] >= cfg.ndvi_min) & usable).sum())
    n_swir_ok = int(((swir1 <= cfg.swir1_max) & usable).sum())
    n_both    = int(((masks["ndvi"] >= cfg.ndvi_min) & (swir1 <= cfg.swir1_max) & usable).sum())
    print(f"DDV diagnosis: usable={usable.sum():,}  "
          f"NDVI≥{cfg.ndvi_min}={n_ndvi_ok:,}  "
          f"SWIR1≤{cfg.swir1_max}={n_swir_ok:,}  "
          f"both={n_both:,}")
    print(f"DDV pixels   : {ddv.sum():,}  ({ddv_frac:.4%} of scene)")

    if ddv_frac < cfg.min_valid_ddv_fraction:
        # Suggest thresholds based on what's available in the clear fraction
        if n_ndvi_ok == 0:
            hint = "Very few high-NDVI pixels; try --ndvi-min 0.25 --swir1-max 0.20"
        elif n_both == 0:
            # Show the actual SWIR1 distribution for high-NDVI pixels
            pix = (masks["ndvi"] >= cfg.ndvi_min) & usable & np.isfinite(swir1)
            if pix.sum() > 0:
                p50 = float(np.nanpercentile(swir1[pix], 50))
                hint = (f"High-NDVI pixels have SWIR1 median={p50:.3f}; "
                        f"try --swir1-max {p50+0.02:.2f}")
            else:
                hint = "No valid SWIR1 for high-NDVI pixels; try --ndvi-min 0.25"
        else:
            hint = f"Increase --min-ddv-fraction below {ddv_frac:.5f}"
        raise RuntimeError(
            f"Too few DDV pixels ({ddv_frac:.5%}). {hint}"
        )

    # --- 6S LUT ---
    lut = build_6s_blue_lut(
        solar_z=sz,
        view_z=vz,
        rel_az=ra,
        target_alt_km=cfg.target_alt_km,
        cfg=cfg,
    )

    # --- Surface blue and AOD retrieval ---
    surf_blue = estimate_surface_blue_from_swir(swir1, cfg)

    if lut.is_valid and cfg.use_py6s:
        aod_ddv_vals = invert_aod_from_lut(b02.array, surf_blue, lut, sz, vz)
        aod_ddv = np.where(ddv, aod_ddv_vals, np.nan).astype(np.float32)
        method = "6S LUT inversion"
    else:
        rho_aero = estimate_aerosol_path_reflectance(b02.array, surf_blue,
                                                     lut.rayleigh_offset)
        aod_ddv = np.where(ddv, path_reflectance_to_aod(rho_aero, cfg), np.nan).astype(np.float32)
        method = "fallback linear"

    print(f"AOD method   : {method}")

    if np.isfinite(aod_ddv).any():
        ddv_aod = aod_ddv[np.isfinite(aod_ddv)]
        print(f"AOD on DDV   : {ddv_aod.min():.3f} .. {ddv_aod.max():.3f}  "
              f"mean={ddv_aod.mean():.3f}")

    # --- Spatial fill and smooth ---
    # 1. Gaussian-weighted fill from DDV pixels (fill_sigma_px controls spatial reach)
    aod_full = fill_from_ddv(aod_ddv, ddv, sigma=cfg.fill_sigma_px)

    # 2. Clear-sky pixels still NaN (far from DDV) get the scene-wide DDV median
    #    This avoids false zeros from nan_to_num; NaN clear pixels become valid estimates.
    invalid_mask = masks["cloud"] | masks["snow"] | masks["invalid"]
    clear_unfilled = ~invalid_mask & ~np.isfinite(aod_full)
    if clear_unfilled.any() and np.isfinite(aod_ddv).any():
        ddv_median = float(np.nanmedian(aod_ddv))
        aod_full[clear_unfilled] = ddv_median
        n_fallback = int(clear_unfilled.sum())
        print(f"  Clear-sky unfilled: {n_fallback:,} px → filled with DDV median={ddv_median:.3f}")

    # 3. Final smooth (small sigma, just for sub-pixel noise reduction)
    valid_before = np.isfinite(aod_full)
    aod_full = gaussian_filter(np.where(valid_before, aod_full, 0.0).astype(np.float32),
                               sigma=cfg.smooth_sigma_px)
    aod_full[~valid_before] = np.nan   # restore NaN where no data existed

    # 4. Mask cloud/snow/invalid pixels → NaN
    aod_full[invalid_mask] = np.nan
    aod_full = np.clip(aod_full, 0.0, 5.0).astype(np.float32)

    # --- Downsample and QA ---
    out_arr, out_transform = downsample_mean(aod_full, b02.transform, b02.crs, cfg.out_res)

    qa = np.zeros_like(aod_full, dtype=np.uint8)
    qa[ddv] = 1
    qa[masks["water"]] = 2
    qa[masks["cloud"]] = 3
    qa[masks["snow"]] = 4
    qa[masks["invalid"]] = 255
    qa_ds, _ = downsample_mean(qa.astype(np.float32), b02.transform, b02.crs, cfg.out_res)

    scene_lat, scene_lon = estimate_scene_center(
        b02.transform, b02.array.shape[1], b02.array.shape[0], b02.crs
    )
    debug = {
        "ddv_mask": ddv,
        "rho_aero_blue": np.where(ddv, b02.array - surf_blue - lut.rayleigh_offset, np.nan),
        "surface_blue": surf_blue,
        "qa": qa_ds,
        "rayleigh_blue_offset": np.array([[lut.rayleigh_offset]], dtype=np.float32),
        "scene_center_latlon": np.array([[scene_lat, scene_lon]], dtype=np.float32),
        "scene_time_utc": scene_time.isoformat(),
        "angles_used": {"solar_z": sz, "view_z": vz, "rel_az": ra},
        "atmosphere_profile": atmos_profile,
        "lut_aot_nodes": lut.aot_nodes.tolist(),
        "lut_path_ref": lut.path_ref.tolist(),
    }
    return out_arr, out_transform, b02.crs, debug


# ---------------------------------------------------------------------------
# MODIS MCD19A2 validation
# ---------------------------------------------------------------------------

def get_bbox_wgs84(transform: Affine, width: int, height: int,
                   crs_obj) -> Tuple[float, float, float, float]:
    left, bottom, right, top = array_bounds(height, width, transform)
    transformer = Transformer.from_crs(crs_obj, "EPSG:4326", always_xy=True)
    lon1, lat1 = transformer.transform(left, bottom)
    lon2, lat2 = transformer.transform(right, top)
    return min(lon1, lon2), min(lat1, lat2), max(lon1, lon2), max(lat1, lat2)


def earthaccess_login(username: Optional[str], password: Optional[str]):
    earthaccess = try_import_earthaccess()
    if earthaccess is None:
        raise ImportError("earthaccess required. Install with: pip install earthaccess")
    if username:
        os.environ["EARTHDATA_USERNAME"] = username
    if password:
        os.environ["EARTHDATA_PASSWORD"] = password
    return earthaccess.login(strategy="environment", persist=False)


def search_and_download_modis_mcd19a2(
    bbox_wgs84: Tuple[float, float, float, float],
    scene_time_utc: datetime,
    out_dir: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    short_name: str = "MCD19A2",
    version: str = "061",
) -> List[str]:
    earthaccess = try_import_earthaccess()
    if earthaccess is None:
        raise ImportError("earthaccess required.")
    earthaccess_login(username, password)
    start = (scene_time_utc - timedelta(days=1)).strftime("%Y-%m-%d")
    end = (scene_time_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    results = earthaccess.search_data(
        short_name=short_name,
        version=version,
        bounding_box=bbox_wgs84,
        temporal=(start, end),
    )
    if not results:
        return []
    out = earthaccess.download(results, out_dir)
    return [str(Path(p)) for p in (out or [])]


def _find_mcd19_sds_name(sd_obj, preferred: Iterable[str]) -> Optional[str]:
    ds_names = list(sd_obj.datasets().keys())
    lower_map = {n.lower(): n for n in ds_names}
    for cand in preferred:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    for name in ds_names:
        ln = name.lower()
        if ("opt" in ln and "055" in ln) or ("aod" in ln and ("055" in ln or "550" in ln)):
            return name
    return None


def infer_modis_sinusoidal_transform(path: str, width: int, height: int) -> Affine:
    m = re.search(r"h(\d{2})v(\d{2})", os.path.basename(path))
    if not m:
        raise ValueError(f"Could not infer MODIS tile h/v from: {path}")
    h, v = int(m.group(1)), int(m.group(2))
    earth_half = 20015109.354
    tile_m = 1111950.5196666666
    xmin = -earth_half + h * tile_m
    ymax = 10007554.677 - v * tile_m
    return Affine(tile_m / width, 0.0, xmin, 0.0, -tile_m / height, ymax)


def read_mcd19a2_aod_grid(hdf_path: str) -> Tuple[np.ndarray, Affine, CRS]:
    imported = try_import_pyhdf()
    if imported is None:
        raise ImportError("pyhdf required. Install with: pip install pyhdf")
    SD, SDC = imported
    hdf = SD(hdf_path, SDC.READ)
    sds_name = _find_mcd19_sds_name(hdf, ["Optical_Depth_055", "Optical_Depth_055_1"])
    if sds_name is None:
        raise KeyError(f"AOD SDS not found in {hdf_path}")
    sds = hdf.select(sds_name)
    arr = sds.get().astype(np.float32)
    attrs = sds.attributes()
    scale = float(attrs.get("scale_factor", 0.001 if np.nanmax(arr) > 10 else 1.0))
    offset = float(attrs.get("add_offset", 0.0))
    fill = attrs.get("_FillValue", attrs.get("fillvalue", -28672))
    arr[arr == fill] = np.nan
    arr = (arr - offset) * scale
    if arr.ndim == 3:
        arr = np.nanmean(arr, axis=2)
    elif arr.ndim != 2:
        raise ValueError(f"Unexpected AOD SDS shape: {arr.shape}")
    crs = CRS.from_proj4("+proj=sinu +R=6371007.181 +nadgrids=@null +wktext")
    transform = infer_modis_sinusoidal_transform(hdf_path, arr.shape[1], arr.shape[0])
    return arr, transform, crs


def reproject_match(source_arr, source_transform, source_crs,
                    target_shape, target_transform, target_crs,
                    resampling=Resampling.bilinear) -> np.ndarray:
    dst = np.full(target_shape, np.nan, dtype=np.float32)
    reproject(
        source=source_arr.astype(np.float32),
        destination=dst,
        src_transform=source_transform,
        src_crs=source_crs,
        dst_transform=target_transform,
        dst_crs=target_crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=resampling,
    )
    return dst


def collocate_validation_stats(s2_aod: np.ndarray,
                               modis_aod: np.ndarray) -> Dict[str, float]:
    valid = np.isfinite(s2_aod) & np.isfinite(modis_aod)
    if valid.sum() == 0:
        return {"n": 0, "bias": np.nan, "rmse": np.nan, "mae": np.nan, "corr": np.nan}
    x = s2_aod[valid].astype(np.float64)
    y = modis_aod[valid].astype(np.float64)
    diff = x - y
    return {
        "n": int(valid.sum()),
        "bias": float(np.mean(diff)),
        "rmse": float(np.sqrt(np.mean(diff ** 2))),
        "mae": float(np.mean(np.abs(diff))),
        "corr": float(np.corrcoef(x, y)[0, 1]) if len(x) > 1 else np.nan,
    }


def save_validation_csv(path: str, stats: Dict[str, float]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("metric,value\n")
        for k, v in stats.items():
            f.write(f"{k},{v}\n")


def run_modis_validation(
    safe_dir: str,
    s2_aod: np.ndarray,
    s2_transform: Affine,
    s2_crs,
    cfg: RetrievalConfig,
    modis_cache: str,
    earthdata_username: Optional[str],
    earthdata_password: Optional[str],
) -> Tuple[Optional[np.ndarray], Dict[str, float], List[str]]:
    reader = Sentinel2L1CReader(safe_dir)
    scene_time = reader.read_scene_time()
    bbox = get_bbox_wgs84(s2_transform, s2_aod.shape[1], s2_aod.shape[0], s2_crs)

    _empty = {"n": 0, "bias": np.nan, "rmse": np.nan, "mae": np.nan, "corr": np.nan}

    modis_files = search_and_download_modis_mcd19a2(
        bbox_wgs84=bbox,
        scene_time_utc=scene_time,
        out_dir=modis_cache,
        username=earthdata_username,
        password=earthdata_password,
        short_name=cfg.modis_collection,
        version=cfg.modis_version,
    )
    if not modis_files:
        print("  No MODIS files found for this scene.")
        return None, _empty, []

    modis_stack = []
    for fp in modis_files:
        try:
            arr, transform, crs = read_mcd19a2_aod_grid(fp)
            arr_match = reproject_match(arr, transform, crs,
                                        s2_aod.shape, s2_transform, s2_crs)
            modis_stack.append(arr_match)
        except Exception as exc:
            print(f"  WARNING: could not read {fp}: {exc}")

    if not modis_stack:
        return None, _empty, modis_files

    modis_mean = np.nanmean(np.stack(modis_stack, axis=0), axis=0).astype(np.float32)
    stats = collocate_validation_stats(s2_aod, modis_mean)
    return modis_mean, stats, modis_files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sentinel-2 AOD retrieval with 6S LUT physics and MODIS validation"
    )
    p.add_argument("--safe", required=True,
                   help="Path to Sentinel-2 L1C SAFE directory")
    p.add_argument("--out", required=True,
                   help="Output GeoTIFF path for AOD550")
    p.add_argument("--out-qa", default=None,
                   help="Optional QA GeoTIFF output path")
    p.add_argument("--out-modis", default=None,
                   help="Optional collocated MODIS AOD GeoTIFF output path")
    p.add_argument("--validation-csv", default=None)
    p.add_argument("--validation-json", default=None)
    p.add_argument("--modis-cache", default="./modis_cache",
                   help="Directory for downloaded MODIS files")
    p.add_argument("--run-validation", action="store_true",
                   help="Download MODIS MCD19A2 and compute validation statistics")

    # Retrieval thresholds
    p.add_argument("--ndvi-min", type=float, default=0.25)
    p.add_argument("--swir1-max", type=float, default=0.22)
    p.add_argument("--surf-blue-a", type=float, default=0.50)
    p.add_argument("--surf-blue-b", type=float, default=0.005)
    p.add_argument("--aod-gain", type=float, default=4.0,
                   help="Fallback linear gain (used only when Py6S unavailable)")
    p.add_argument("--aod-bias", type=float, default=0.0,
                   help="Fallback linear bias (used only when Py6S unavailable)")
    p.add_argument("--fallback-rayleigh-blue-offset", type=float, default=0.02,
                   help="Rayleigh offset used only when Py6S unavailable")
    p.add_argument("--min-ddv-fraction", type=float, default=0.001,
                   help="Minimum fraction of scene that must be DDV (default: 0.001 = 0.1%%)")
    p.add_argument("--out-res", type=int, default=20, choices=[10, 20, 60])

    # 6S configuration
    p.add_argument("--no-py6s", action="store_true",
                   help="Disable Py6S and use fallback linear calibration")
    p.add_argument("--solar-z-deg", type=float, default=None,
                   help="Override solar zenith angle (degrees); default: auto from metadata")
    p.add_argument("--view-z-deg", type=float, default=None,
                   help="Override view zenith angle (degrees); default: auto from metadata")
    p.add_argument("--rel-az-deg", type=float, default=None,
                   help="Override relative azimuth angle (degrees); default: auto from metadata")
    p.add_argument("--aerosol-profile", default="continental",
                   choices=["continental", "maritime", "urban", "desert"])
    p.add_argument("--atmosphere-profile", default="auto",
                   choices=["auto", "midlatitude_summer", "midlatitude_winter",
                            "tropical", "subarctic_summer", "subarctic_winter"],
                   help="Atmosphere profile for 6S; 'auto' detects from scene date and latitude")
    p.add_argument("--target-alt-km", type=float, default=0.0)

    # Earthdata credentials
    p.add_argument("--earthdata-username", default=None)
    p.add_argument("--earthdata-password", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    cfg = RetrievalConfig(
        ndvi_min=args.ndvi_min,
        swir1_max=args.swir1_max,
        surf_blue_a=args.surf_blue_a,
        surf_blue_b=args.surf_blue_b,
        fallback_rayleigh_blue_offset=args.fallback_rayleigh_blue_offset,
        aod_gain=args.aod_gain,
        aod_bias=args.aod_bias,
        out_res=args.out_res,
        use_py6s=not args.no_py6s,
        aerosol_profile=args.aerosol_profile,
        atmosphere_profile=args.atmosphere_profile,
        target_alt_km=args.target_alt_km,
        min_valid_ddv_fraction=args.min_ddv_fraction,
    )

    aod, transform, crs, debug = retrieve_aod(
        args.safe,
        cfg,
        solar_z_deg=args.solar_z_deg,
        view_z_deg=args.view_z_deg,
        rel_az_deg=args.rel_az_deg,
    )

    write_geotiff(args.out, aod, transform, crs)
    print(f"\nWrote AOD GeoTIFF: {args.out}")

    if args.out_qa:
        write_geotiff(args.out_qa, debug["qa"].astype(np.float32), transform, crs)
        print(f"Wrote QA  GeoTIFF: {args.out_qa}")

    finite = np.isfinite(aod)
    if finite.any():
        print(f"Valid pixels : {finite.sum():,} / {aod.size:,}")
        print(f"AOD range    : {np.nanmin(aod):.3f} .. {np.nanmax(aod):.3f}")
        print(f"AOD mean     : {np.nanmean(aod):.3f}")
        print(f"AOD median   : {np.nanmedian(aod):.3f}")
    else:
        print("WARNING: no valid AOD pixels in output.")

    if args.run_validation:
        print("\n--- MODIS MCD19A2 validation ---")
        modis_match, stats, files = run_modis_validation(
            safe_dir=args.safe,
            s2_aod=aod,
            s2_transform=transform,
            s2_crs=crs,
            cfg=cfg,
            modis_cache=args.modis_cache,
            earthdata_username=args.earthdata_username or os.getenv("EARTHDATA_USERNAME"),
            earthdata_password=args.earthdata_password or os.getenv("EARTHDATA_PASSWORD"),
        )
        print("MODIS files downloaded:")
        for fp in files:
            print(f"  {fp}")
        print("Validation statistics (S2 - MODIS):")
        for k, v in stats.items():
            print(f"  {k:6s}: {v}")

        if modis_match is not None and args.out_modis:
            write_geotiff(args.out_modis, modis_match, transform, crs)
            print(f"Wrote MODIS collocated: {args.out_modis}")
        if args.validation_csv:
            save_validation_csv(args.validation_csv, stats)
        if args.validation_json:
            with open(args.validation_json, "w", encoding="utf-8") as f:
                json.dump({k: (v if np.isfinite(v) else None)
                           for k, v in stats.items()}, f, indent=2)


if __name__ == "__main__":
    main()
