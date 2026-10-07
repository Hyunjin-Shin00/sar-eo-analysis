"""Pan-sharpening style fusion: BlueBON high-res + MAIAC absolute level.

Two modes:
  --mode linear : additive linear fit at 1 km, apply delta to native BB
  --mode brovey : ratio-based — final = upsample(MAIAC) * (BB / upsample(BB_1km))
                  forces 1 km mean ≡ MAIAC, preserves BB relative structure

Brovey is recommended when BB↔MAIAC R² is low (no shared structure).
"""
import os
import sys
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("bb_path", nargs="?", default="bb_aod_v7.tif")
    p.add_argument("out_path", nargs="?", default="bb_aod_v7_pansharp.tif")
    p.add_argument("--mode", choices=["linear", "brovey"], default="brovey")
    args = p.parse_args()
    bb_path, out_path, mode = args.bb_path, args.out_path, args.mode

    candidates = [
        "./validation/maiac_aod_2026-02-20.tif",
        "./validation/maiac_aod_2026-02-16.tif",
    ]
    maiac_tif = next((c for c in candidates if os.path.exists(c)), None)
    if maiac_tif is None:
        print("ERROR: MAIAC GeoTIFF not found")
        sys.exit(1)
    print(f"MAIAC source : {maiac_tif}")

    with rasterio.open(bb_path) as bs:
        bb = bs.read(1).astype(np.float32)
        nd = bs.nodata
        if nd is not None:
            bb[bb == nd] = np.nan
        bb_tf, bb_crs = bs.transform, bs.crs
        bb_profile = bs.profile

    with rasterio.open(maiac_tif) as ms:
        maiac = ms.read(1).astype(np.float32)
        nd = ms.nodata
        if nd is not None:
            maiac[maiac == nd] = np.nan
        m_tf, m_crs = ms.transform, ms.crs
        m_h, m_w = ms.shape

    # 1. BB → MAIAC 1km 격자로 평균 다운샘플
    bb_on_maiac = np.full((m_h, m_w), np.nan, dtype=np.float32)
    reproject(
        source=bb, destination=bb_on_maiac,
        src_transform=bb_tf, src_crs=bb_crs,
        dst_transform=m_tf, dst_crs=m_crs,
        resampling=Resampling.average,
        src_nodata=np.nan, dst_nodata=np.nan,
    )

    # 2. 1km 격자에서 선형 fit
    valid = np.isfinite(bb_on_maiac) & np.isfinite(maiac)
    n = int(valid.sum())
    print(f"1 km matched pixels : {n:,}")
    if n < 50:
        print("ERROR: insufficient matched pixels at 1 km")
        sys.exit(1)

    x = bb_on_maiac[valid].astype(np.float64)
    y = maiac[valid].astype(np.float64)
    print(f"  BB_1km : mean={x.mean():.4f}  std={x.std():.4f}")
    print(f"  MAIAC  : mean={y.mean():.4f}  std={y.std():.4f}")

    print(f"\nMode: {mode}")
    if mode == "linear":
        slope, intercept = np.polyfit(x, y, 1)
        yp = slope * x + intercept
        rmse_before = float(np.sqrt(np.mean((x - y) ** 2)))
        rmse_after  = float(np.sqrt(np.mean((yp - y) ** 2)))
        print(f"Linear fit @1 km : MAIAC = {slope:.4f} * BB + {intercept:+.4f}")
        print(f"  R²       = {1 - np.var(y - yp) / np.var(y):.4f}")
        print(f"  Before   : Bias={(x-y).mean():+.4f}  RMSE={rmse_before:.4f}")
        print(f"  After    : Bias={(yp-y).mean():+.4f}  RMSE={rmse_after:.4f}")
        bb_corr_1km = (slope * bb_on_maiac + intercept).astype(np.float32)
        delta_1km   = (bb_corr_1km - bb_on_maiac).astype(np.float32)
        delta_1km   = np.where(np.isfinite(delta_1km), delta_1km, 0.0).astype(np.float32)
        delta_native = np.zeros(bb.shape, dtype=np.float32)
        reproject(source=delta_1km, destination=delta_native,
                  src_transform=m_tf, src_crs=m_crs,
                  dst_transform=bb_tf, dst_crs=bb_crs,
                  resampling=Resampling.bilinear)
        fused = bb + delta_native
    else:  # brovey
        # ratio = MAIAC / BB_1km, gap-fill missing MAIAC with bias-corrected BB
        bias_1km = float(np.nanmean(bb_on_maiac) - np.nanmean(maiac))
        target_1km = np.where(np.isfinite(maiac), maiac,
                              np.maximum(bb_on_maiac - bias_1km, 0.05)).astype(np.float32)
        # ratio at 1km
        denom_1km = np.where(np.isfinite(bb_on_maiac) & (bb_on_maiac > 0.01),
                             bb_on_maiac, np.nan).astype(np.float32)
        ratio_1km = (target_1km / denom_1km).astype(np.float32)
        # NaN-fill ratio with median (so swath edges get neutral correction)
        med_ratio = float(np.nanmedian(ratio_1km))
        ratio_1km = np.where(np.isfinite(ratio_1km), ratio_1km, med_ratio).astype(np.float32)
        # clip extreme ratios (robustness)
        ratio_1km = np.clip(ratio_1km, 0.1, 5.0)
        print(f"Brovey ratio @1 km: median={med_ratio:.3f}  "
              f"p5={np.percentile(ratio_1km,5):.3f}  p95={np.percentile(ratio_1km,95):.3f}")
        # upsample ratio (bilinear smooth)
        ratio_native = np.ones(bb.shape, dtype=np.float32)
        reproject(source=ratio_1km, destination=ratio_native,
                  src_transform=m_tf, src_crs=m_crs,
                  dst_transform=bb_tf, dst_crs=bb_crs,
                  resampling=Resampling.bilinear)
        fused = bb * ratio_native
    fused = np.clip(fused, 0.0, 5.0).astype(np.float32)
    fused[~np.isfinite(bb)] = np.nan

    prof = bb_profile.copy()
    prof.update(dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(out_path, "w", **prof) as dst:
        dst.write(fused, 1)
    print(f"\nSaved : {out_path}")

    v = fused[np.isfinite(fused)]
    print(f"  mean={v.mean():.3f}  median={np.median(v):.3f}  std={v.std():.3f}  "
          f"range=[{v.min():.3f},{v.max():.3f}]")

    # 검증: 융합 결과를 다시 1km로 다운샘플 → MAIAC와 비교
    fused_on_m = np.full((m_h, m_w), np.nan, dtype=np.float32)
    reproject(source=fused, destination=fused_on_m,
              src_transform=bb_tf, src_crs=bb_crs,
              dst_transform=m_tf, dst_crs=m_crs,
              resampling=Resampling.average,
              src_nodata=np.nan, dst_nodata=np.nan)
    v2 = np.isfinite(fused_on_m) & np.isfinite(maiac)
    if v2.sum() > 50:
        xf = fused_on_m[v2]; yt = maiac[v2]
        print(f"\nFused vs MAIAC @1 km :")
        print(f"  N={int(v2.sum()):,}")
        print(f"  Bias = {(xf - yt).mean():+.4f}")
        print(f"  RMSE = {np.sqrt(np.mean((xf - yt) ** 2)):.4f}")
        print(f"  R    = {np.corrcoef(xf, yt)[0, 1]:.4f}")


if __name__ == "__main__":
    main()
