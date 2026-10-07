"""DDV-confidence weighted blend of BB Brovey + MAIAC.

Where DDV pixels are nearby → trust BB high-res structure.
Where DDV is sparse / absent → fall back to MAIAC absolute level.

Avoids artifacts in clear-only regions (e.g., sewage plants) where
DDV-derived AOD bleeds in via Gaussian fill smoothing.
"""
import os
import sys
import argparse
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy.ndimage import distance_transform_edt, gaussian_filter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bb",       default="bb_aod_v8_brovey_sm.tif")
    ap.add_argument("--qa",       default="bb_aod_v8_qa.tif")
    ap.add_argument("--maiac",    default="./validation/maiac_aod_2026-02-20.tif")
    ap.add_argument("--out",      default="bb_aod_blend.tif")
    ap.add_argument("--length-m", type=float, default=500.0,
                    help="DDV influence length scale (m); weight=exp(-dist/L)")
    args = ap.parse_args()

    with rasterio.open(args.bb) as bs:
        bb = bs.read(1).astype(np.float32)
        if bs.nodata is not None:
            bb[bb == bs.nodata] = np.nan
        bb_tf, bb_crs = bs.transform, bs.crs
        prof = bs.profile

    with rasterio.open(args.qa) as qs:
        qa = qs.read(1)

    with rasterio.open(args.maiac) as ms:
        maiac = ms.read(1).astype(np.float32)
        if ms.nodata is not None:
            maiac[maiac == ms.nodata] = np.nan
        m_tf, m_crs = ms.transform, ms.crs

    # MAIAC을 BB 격자로 reproject (bilinear → 1km blocky 줄임)
    # NaN 채움: MAIAC NaN인 곳은 nearest valid 값으로
    valid_m = np.isfinite(maiac).astype(np.float32)
    maiac_filled = np.where(np.isfinite(maiac), maiac, 0.0).astype(np.float32)
    # 가벼운 spatial smoothing 후 NaN 영역 채움
    sigma = 3.0
    n_sm = gaussian_filter(maiac_filled * valid_m, sigma=sigma)
    d_sm = gaussian_filter(valid_m, sigma=sigma)
    maiac_smooth = np.where(d_sm > 0.01, n_sm / np.maximum(d_sm, 1e-9),
                            float(np.nanmean(maiac))).astype(np.float32)

    maiac_on_bb = np.full(bb.shape, np.nan, dtype=np.float32)
    reproject(maiac_smooth, maiac_on_bb,
              src_transform=m_tf, src_crs=m_crs,
              dst_transform=bb_tf, dst_crs=bb_crs,
              resampling=Resampling.bilinear)

    # DDV로부터의 거리 (m)
    ddv_mask = (qa == 1)
    print(f"DDV pixels: {ddv_mask.sum():,} / {ddv_mask.size:,} "
          f"({100 * ddv_mask.sum() / ddv_mask.size:.2f}%)")
    px_size_m = abs(bb_tf.a)
    if bb_crs and bb_crs.is_geographic:
        # 위경도 → m 변환 (위도 기반)
        px_size_m = abs(bb_tf.a) * 111320.0
    print(f"Pixel size : {px_size_m:.2f} m")

    if ddv_mask.any():
        # distance_transform_edt: True 위치에서 거리 0, False에서 거리 increasing
        dist_px = distance_transform_edt(~ddv_mask)
        dist_m = dist_px * px_size_m
    else:
        dist_m = np.full(bb.shape, 1e9, dtype=np.float32)

    # DDV 신뢰 가중치 w(d) = exp(-d / L)
    L = args.length_m
    w = np.exp(-dist_m / L).astype(np.float32)
    print(f"\nWeight stats: median={np.median(w):.3f}  "
          f"p25={np.percentile(w,25):.3f}  p75={np.percentile(w,75):.3f}")
    print(f"  Pixels w<0.1 (mostly MAIAC) : {int((w<0.1).sum()):,} ({100*(w<0.1).mean():.1f}%)")
    print(f"  Pixels w>0.5 (mostly BB)    : {int((w>0.5).sum()):,} ({100*(w>0.5).mean():.1f}%)")

    # 융합
    fused = w * bb + (1.0 - w) * maiac_on_bb
    fused[~np.isfinite(bb)] = np.nan
    fused = np.clip(fused, 0.0, 5.0).astype(np.float32)

    prof2 = prof.copy()
    prof2.update(dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(args.out, "w", **prof2) as d:
        d.write(fused, 1)
    print(f"\nSaved : {args.out}")

    v = fused[np.isfinite(fused)]
    print(f"  mean={v.mean():.3f}  median={np.median(v):.3f}  std={v.std():.3f}  "
          f"range=[{v.min():.3f},{v.max():.3f}]")

    # MAIAC 1km 검증
    fused_on_m = np.full(maiac.shape, np.nan, dtype=np.float32)
    reproject(fused, fused_on_m, src_transform=bb_tf, src_crs=bb_crs,
              dst_transform=m_tf, dst_crs=m_crs,
              resampling=Resampling.average,
              src_nodata=np.nan, dst_nodata=np.nan)
    vv = np.isfinite(fused_on_m) & np.isfinite(maiac)
    if vv.sum() > 50:
        x, y = fused_on_m[vv], maiac[vv]
        print(f"\nvs MAIAC @1 km: N={int(vv.sum()):,}")
        print(f"  Bias = {(x-y).mean():+.4f}")
        print(f"  RMSE = {np.sqrt(np.mean((x-y)**2)):.4f}")
        print(f"  R    = {np.corrcoef(x, y)[0, 1]:.4f}")
        print(f"  MAE  = {np.abs(x-y).mean():.4f}")

    # 두 anomaly 위치 검증
    from rasterio.transform import rowcol
    print("\n--- Anomaly 위치 검증 ---")
    for lat, lon in [(37.113468, 126.890428), (37.099250, 126.963510)]:
        r, c = rowcol(bb_tf, lon, lat)
        bb_v = bb[r, c] if 0 <= r < bb.shape[0] and 0 <= c < bb.shape[1] else np.nan
        m_v  = maiac_on_bb[r, c]
        f_v  = fused[r, c]
        w_v  = w[r, c]
        d_v  = dist_m[r, c]
        print(f"  ({lat:.4f}, {lon:.4f}): "
              f"BB={float(bb_v):.3f}  MAIAC={float(m_v):.3f}  blended={float(f_v):.3f}  "
              f"w={float(w_v):.3f}  dist_DDV={float(d_v):.0f}m")


if __name__ == "__main__":
    main()
