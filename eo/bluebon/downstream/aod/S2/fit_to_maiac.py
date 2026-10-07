"""Fit BlueBON AOD to MAIAC via per-pixel linear regression."""
import os
import sys
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling


def main():
    bb_path = sys.argv[1] if len(sys.argv) > 1 else "bb_aod_v7.tif"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "bb_aod_v7_fit.tif"

    with rasterio.open(bb_path) as bs:
        bb = bs.read(1).astype(np.float32)
        nd = bs.nodata
        if nd is not None:
            bb[bb == nd] = np.nan
        bb_tf, bb_crs = bs.transform, bs.crs
        bb_profile = bs.profile

    # 동일 날짜 우선, 없으면 가장 가까운 사용
    candidates = [
        "./validation/maiac_aod_2026-02-20.tif",
        "./validation/maiac_aod_2026-02-16.tif",
    ]
    maiac_tif = next((c for c in candidates if os.path.exists(c)), None)
    if maiac_tif is None:
        print("ERROR: MAIAC GeoTIFF not found")
        sys.exit(1)
    print(f"MAIAC source: {maiac_tif}")

    with rasterio.open(maiac_tif) as ms:
        maiac = ms.read(1).astype(np.float32)
        nd = ms.nodata
        if nd is not None:
            maiac[maiac == nd] = np.nan
        m_tf, m_crs = ms.transform, ms.crs

    maiac_on_bb = np.full(bb.shape, np.nan, dtype=np.float32)
    reproject(
        source=maiac, destination=maiac_on_bb,
        src_transform=m_tf, src_crs=m_crs,
        dst_transform=bb_tf, dst_crs=bb_crs,
        resampling=Resampling.bilinear,
        src_nodata=np.nan, dst_nodata=np.nan,
    )

    valid = np.isfinite(bb) & np.isfinite(maiac_on_bb)
    n = int(valid.sum())
    print(f"Matched valid pixels: {n:,}")
    if n < 100:
        print("ERROR: too few matched pixels")
        sys.exit(1)

    x = bb[valid].astype(np.float64)
    y = maiac_on_bb[valid].astype(np.float64)
    print(f"  BB    : mean={x.mean():.4f}  median={np.median(x):.4f}  std={x.std():.4f}")
    print(f"  MAIAC : mean={y.mean():.4f}  median={np.median(y):.4f}  std={y.std():.4f}")

    slope, intercept = np.polyfit(x, y, 1)
    yp = slope * x + intercept
    rmse_before = float(np.sqrt(np.mean((x - y) ** 2)))
    rmse_after = float(np.sqrt(np.mean((yp - y) ** 2)))
    bias_before = float((x - y).mean())
    bias_after = float((yp - y).mean())
    r_before = float(np.corrcoef(x, y)[0, 1])
    r_after = float(np.corrcoef(yp, y)[0, 1])

    print(f"\nLinear fit: MAIAC = {slope:.4f} * BB + {intercept:+.4f}")
    print(f"            R²            = {1 - np.var(y - yp) / np.var(y):.4f}")
    print(f"  Before:  Bias={bias_before:+.4f}  RMSE={rmse_before:.4f}  R={r_before:.4f}")
    print(f"  After :  Bias={bias_after:+.4f}  RMSE={rmse_after:.4f}  R={r_after:.4f}")

    bb_fit = np.clip(slope * bb + intercept, 0.0, 5.0).astype(np.float32)
    bb_fit[~np.isfinite(bb)] = np.nan

    prof = bb_profile.copy()
    prof.update(dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(out_path, "w", **prof) as dst:
        dst.write(bb_fit, 1)

    v = bb_fit[np.isfinite(bb_fit)]
    print(f"\nSaved : {out_path}")
    print(f"  mean={v.mean():.3f}  median={np.median(v):.3f}  std={v.std():.3f}  "
          f"range=[{v.min():.3f},{v.max():.3f}]")


if __name__ == "__main__":
    main()
