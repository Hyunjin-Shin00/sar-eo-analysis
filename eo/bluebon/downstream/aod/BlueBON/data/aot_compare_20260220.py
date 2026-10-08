#!/usr/bin/env python3
"""
2026-02-20 AOT 비교 통계.

Sources
-------
GT      : MAIAC MCD19A2 Optical_Depth_055 (1km, sinusoidal)
BB      : BlueBON pipeline output  bb_aod_20260220_025632_sm.tif (WGS84, ~5m)
S2      : Sentinel-2 L2A AOT 60m, T52SCG (UTM 52N, 60m)

Approach
--------
Reproject all sources to a common 0.01° (~1km) WGS84 grid covering the
L1C scene bbox, then compute pixel-wise statistics on co-valid pixels.
"""

from __future__ import annotations

import os
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.transform import from_origin
from rasterio.crs import CRS
from pyhdf.SD import SD, SDC

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
MAIAC_HDF = "<WORK_ROOT>/working/AOD/BlueBON/maiac_cache/MCD19A2.A2026051.h28v05.061.2026052163901.hdf"
BB_AOD    = "<WORK_ROOT>/working/AOD/BlueBON/output_20260220/bb_aod_20260220_025632_sm.tif"
S2_AOT    = "/tmp/s2_aot/T52SCG_20260220T021629_AOT_60m.jp2"
L1C_TIFF  = "<WORK_ROOT>/working/AOD/BlueBON/data/L1C/bb_l1c_20260220_025632_8band.tiff"

OUT_DIR   = Path("<WORK_ROOT>/working/AOD/BlueBON/data/aot_stats_20260220")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Common analysis grid (WGS84, 0.01° ~ 1.1km, matching MAIAC 1km)
PIX = 0.01
# L1C scene bbox (from gdalinfo): 126.7804..127.3141 E, 37.0369..37.8369 N
LON_MIN, LAT_MIN, LON_MAX, LAT_MAX = 126.78, 37.04, 127.32, 37.84

# ---------------------------------------------------------------------------
# Build target grid
# ---------------------------------------------------------------------------
W = int(round((LON_MAX - LON_MIN) / PIX))
H = int(round((LAT_MAX - LAT_MIN) / PIX))
DST_TRANSFORM = from_origin(LON_MIN, LAT_MAX, PIX, PIX)
DST_CRS = CRS.from_epsg(4326)
print(f"target grid: {W}x{H} @ 0.01deg WGS84")

# ---------------------------------------------------------------------------
# 1) MAIAC OD055
# ---------------------------------------------------------------------------
print("\n[MAIAC] reading Optical_Depth_055 ...")
hdf = SD(MAIAC_HDF, SDC.READ)
sds = hdf.select("Optical_Depth_055")
arr = sds.get()                         # shape (3, 1200, 1200)
attrs = sds.attributes()
scale = float(attrs.get("scale_factor", 0.001))
fill  = int(attrs.get("_FillValue", -28672))
print(f"  shape={arr.shape}  scale={scale}  fill={fill}")
print(f"  orbit-mean of valid: per-orbit valid count = {[int((arr[i]!=fill).sum()) for i in range(arr.shape[0])]}")

valid = arr != fill
arr_f = np.where(valid, arr.astype(np.float32) * scale, np.nan)
maiac_2d = np.nanmean(arr_f, axis=0)        # mean over orbits
print(f"  valid pixels (any-orbit): {int(np.isfinite(maiac_2d).sum())}/{maiac_2d.size}")

# MAIAC sinusoidal grid info
g = hdf.attributes()
sds.endaccess(); hdf.end()

# Re-open via rasterio HDF4_EOS subdataset for transform/CRS
sub = f'HDF4_EOS:EOS_GRID:"{MAIAC_HDF}":grid1km:Optical_Depth_055'
with rasterio.open(sub) as src:
    print(f"  src CRS: {src.crs}")
    print(f"  src transform: {src.transform}")
    print(f"  src shape (per band): {src.height}x{src.width}, count={src.count}")
    src_crs = src.crs
    src_tr  = src.transform

maiac_dst = np.full((H, W), np.nan, dtype=np.float32)
reproject(
    source=maiac_2d,
    destination=maiac_dst,
    src_transform=src_tr,
    src_crs=src_crs,
    dst_transform=DST_TRANSFORM,
    dst_crs=DST_CRS,
    src_nodata=np.nan,
    dst_nodata=np.nan,
    resampling=Resampling.average,
)
print(f"  reprojected MAIAC valid: {int(np.isfinite(maiac_dst).sum())}/{maiac_dst.size}")

# ---------------------------------------------------------------------------
# 2) BlueBON bb_aod (already WGS84)
# ---------------------------------------------------------------------------
print("\n[BB] reading bb_aod ...")
with rasterio.open(BB_AOD) as src:
    print(f"  src CRS={src.crs}  shape={src.height}x{src.width}  res={src.res}")
    bb_dst = np.full((H, W), np.nan, dtype=np.float32)
    reproject(
        source=rasterio.band(src, 1),
        destination=bb_dst,
        src_transform=src.transform,
        src_crs=src.crs,
        dst_transform=DST_TRANSFORM,
        dst_crs=DST_CRS,
        src_nodata=src.nodata,
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
print(f"  BB valid: {int(np.isfinite(bb_dst).sum())}/{bb_dst.size}")

# ---------------------------------------------------------------------------
# 3) S2 L2A AOT (UTM 52N, scale=1/1000, fill=0)
# ---------------------------------------------------------------------------
print("\n[S2] reading L2A AOT 60m ...")
with rasterio.open(S2_AOT) as src:
    print(f"  src CRS={src.crs}  shape={src.height}x{src.width}  res={src.res}")
    s2_dn = src.read(1).astype(np.float32)
    s2_aot_native = np.where(s2_dn > 0, s2_dn / 1000.0, np.nan)
    s2_dst = np.full((H, W), np.nan, dtype=np.float32)
    reproject(
        source=s2_aot_native,
        destination=s2_dst,
        src_transform=src.transform,
        src_crs=src.crs,
        dst_transform=DST_TRANSFORM,
        dst_crs=DST_CRS,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
print(f"  S2 valid: {int(np.isfinite(s2_dst).sum())}/{s2_dst.size}")

# ---------------------------------------------------------------------------
# Per-source quick stats
# ---------------------------------------------------------------------------
def src_stats(name, a):
    v = a[np.isfinite(a)]
    if v.size == 0:
        print(f"  {name}: all NaN")
        return
    print(f"  {name}: n={v.size}  min={v.min():.4f}  max={v.max():.4f} "
          f"mean={v.mean():.4f}  median={np.median(v):.4f}  std={v.std():.4f}")

print("\n[per-source stats on common grid]")
src_stats("MAIAC", maiac_dst)
src_stats("BB   ", bb_dst)
src_stats("S2   ", s2_dst)

# ---------------------------------------------------------------------------
# Pairwise statistics on co-valid pixels
# ---------------------------------------------------------------------------
def pair_stats(label, gt, x):
    m = np.isfinite(gt) & np.isfinite(x)
    n = int(m.sum())
    if n < 5:
        print(f"  [{label}] insufficient overlap (n={n})")
        return None
    g = gt[m]; v = x[m]
    bias = float((v - g).mean())
    mae  = float(np.abs(v - g).mean())
    rmse = float(np.sqrt(((v - g) ** 2).mean()))
    if g.std() > 0 and v.std() > 0:
        r = float(np.corrcoef(g, v)[0, 1])
        r2 = r * r
    else:
        r = float("nan"); r2 = float("nan")
    # Linear regression v = a*g + b (least squares)
    A = np.vstack([g, np.ones_like(g)]).T
    a_, b_ = np.linalg.lstsq(A, v, rcond=None)[0]
    print(f"  [{label}] n={n:6d}  bias={bias:+.4f}  MAE={mae:.4f}  RMSE={rmse:.4f} "
          f"R={r:+.4f}  R^2={r2:.4f}  slope={a_:+.4f}  intercept={b_:+.4f}")
    return dict(label=label, n=n, bias=bias, mae=mae, rmse=rmse,
                R=r, R2=r2, slope=float(a_), intercept=float(b_))

print("\n[pairwise vs MAIAC ground truth]")
res_bb = pair_stats("BB  vs MAIAC", maiac_dst, bb_dst)
res_s2 = pair_stats("S2  vs MAIAC", maiac_dst, s2_dst)
print("\n[between BB and S2]")
res_bs = pair_stats("BB  vs S2   ", s2_dst, bb_dst)

# ---------------------------------------------------------------------------
# Save reprojected rasters and pair plots
# ---------------------------------------------------------------------------
def write_geotiff(path, arr, nodata=np.nan):
    profile = dict(driver="GTiff", height=H, width=W, count=1, dtype="float32",
                   crs=DST_CRS, transform=DST_TRANSFORM, nodata=nodata,
                   compress="lzw")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(np.float32), 1)

write_geotiff(OUT_DIR / "MAIAC_OD055_20260220_grid.tif", maiac_dst)
write_geotiff(OUT_DIR / "BB_AOD_20260220_grid.tif",      bb_dst)
write_geotiff(OUT_DIR / "S2_AOT_20260220_grid.tif",      s2_dst)
print(f"\n[wrote rasters to {OUT_DIR}]")

# scatter plots
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def scatter(gt, x, label, fname, color):
        m = np.isfinite(gt) & np.isfinite(x)
        if m.sum() < 5:
            return
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.scatter(gt[m], x[m], s=6, alpha=0.4, c=color)
        lim = [0, max(np.nanmax(gt[m]), np.nanmax(x[m])) * 1.05]
        ax.plot(lim, lim, "k--", lw=1, label="1:1")
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel("MAIAC OD055 (GT)")
        ax.set_ylabel(label)
        ax.set_title(f"{label} vs MAIAC  2026-02-20")
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right")
        fig.tight_layout()
        fig.savefig(fname, dpi=150)
        plt.close(fig)

    scatter(maiac_dst, bb_dst, "BlueBON AOD", OUT_DIR / "scatter_BB_vs_MAIAC.png", "tab:blue")
    scatter(maiac_dst, s2_dst, "S2 L2A AOT",  OUT_DIR / "scatter_S2_vs_MAIAC.png", "tab:orange")
    print(f"[wrote scatter plots]")
except Exception as e:
    print(f"  plot skipped: {e}")

# Summary CSV
import csv
with open(OUT_DIR / "summary.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["pair", "n", "bias", "mae", "rmse", "R", "R2", "slope", "intercept"])
    for r in (res_bb, res_s2, res_bs):
        if r:
            w.writerow([r["label"], r["n"], f"{r['bias']:+.4f}", f"{r['mae']:.4f}",
                        f"{r['rmse']:.4f}", f"{r['R']:+.4f}", f"{r['R2']:.4f}",
                        f"{r['slope']:+.4f}", f"{r['intercept']:+.4f}"])
print(f"\n[summary saved to {OUT_DIR/'summary.csv'}]")
print("\nDone.")
