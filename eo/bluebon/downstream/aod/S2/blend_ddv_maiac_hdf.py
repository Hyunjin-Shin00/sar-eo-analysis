"""DDV-confidence weighted blend reading MAIAC directly from HDF.

원본 HDF에서 모든 orbit/tile의 raw AOD 픽셀을 읽어 BB 격자로 직접 매핑.
캐시 GeoTIFF 사용 시 발생하는 NaN 손실을 방지.
"""
import os
import sys
import glob
import argparse
import math
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import Affine, rowcol
from scipy.ndimage import distance_transform_edt, gaussian_filter

_R = 6_371_007.181
_T = math.pi * _R / 18  # ~1_111_950.5 m


def maiac_pixel_lonlat(row, col, h, v, nrows=1200):
    ps = _T / nrows
    x_ul = (h - 18) * _T
    y_ul = (9 - v) * _T
    x_c = x_ul + (col + 0.5) * ps
    y_c = y_ul - (row + 0.5) * ps
    lat_rad = y_c / _R
    lat = np.degrees(lat_rad)
    lon = np.degrees(x_c / (_R * np.cos(lat_rad)))
    return lon, lat


def tile_hv(hdf_path):
    import re
    m = re.search(r"h(\d{2})v(\d{2})", os.path.basename(hdf_path))
    return int(m.group(1)), int(m.group(2))


def read_maiac_pixels(hdf_paths, bbox, qa_mask=False):
    """모든 HDF/orbit에서 (lon, lat, aod) 산점 추출."""
    from pyhdf.SD import SD, SDC
    lon_min, lat_min, lon_max, lat_max = bbox
    all_lon, all_lat, all_aod = [], [], []
    for path in hdf_paths:
        h, v = tile_hv(path)
        hdf = SD(str(path), SDC.READ)
        try:
            sds = hdf.select("Optical_Depth_055")
            raw = sds[:].astype(np.float32)
            attrs = sds.attributes()
            scale = attrs.get("scale_factor", 0.001)
            fill  = attrs.get("_FillValue", -28672)
            qa = hdf.select("AOD_QA")[:] if qa_mask else None
        finally:
            hdf.end()

        nt, nr, nc = raw.shape if raw.ndim == 3 else (1, *raw.shape)
        if raw.ndim == 2:
            raw = raw[None, :, :]
            if qa is not None:
                qa = qa[None, :, :]
        rr, cc = np.meshgrid(np.arange(nr), np.arange(nc), indexing="ij")
        lon_g, lat_g = maiac_pixel_lonlat(rr, cc, h, v, nr)
        in_bbox = (lon_g >= lon_min) & (lon_g <= lon_max) & \
                  (lat_g >= lat_min) & (lat_g <= lat_max)
        for t in range(nt):
            valid = (raw[t] != fill) & in_bbox
            if qa is not None:
                qa_aod = (qa[t] >> 8) & 0xF  # 0=best
                valid &= (qa_aod == 0)
            if valid.any():
                all_lon.append(lon_g[valid])
                all_lat.append(lat_g[valid])
                all_aod.append((raw[t][valid] * scale).astype(np.float32))

    if not all_lon:
        return np.array([]), np.array([]), np.array([])
    return (np.concatenate(all_lon),
            np.concatenate(all_lat),
            np.concatenate(all_aod))


def rasterize_to_grid(lon, lat, aod, transform, shape):
    """산점 픽셀을 BB 격자로 평균 래스터화."""
    h, w = shape
    sum_g = np.zeros(shape, dtype=np.float64)
    cnt_g = np.zeros(shape, dtype=np.int32)
    inv = ~transform
    cols = np.floor(inv.a * lon + inv.b * lat + inv.c).astype(int)
    rows = np.floor(inv.d * lon + inv.e * lat + inv.f).astype(int)
    ok = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    rows, cols, aod = rows[ok], cols[ok], aod[ok]
    np.add.at(sum_g, (rows, cols), aod)
    np.add.at(cnt_g, (rows, cols), 1)
    out = np.full(shape, np.nan, dtype=np.float32)
    valid = cnt_g > 0
    out[valid] = (sum_g[valid] / cnt_g[valid]).astype(np.float32)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bb",       default="bb_aod_v8_brovey_sm.tif")
    ap.add_argument("--qa",       default="bb_aod_v8_qa.tif")
    ap.add_argument("--maiac-dir", default="./validation",
                    help="Directory containing MCD19A2*.hdf files")
    ap.add_argument("--bb-date",  default="2026051",
                    help="Same-day MAIAC DOY (YYYYDDD); A2026051 = Feb 20")
    ap.add_argument("--out",      default="bb_aod_blend_hdf.tif")
    ap.add_argument("--length-m", type=float, default=500.0)
    ap.add_argument("--qa-best",  action="store_true",
                    help="Filter MAIAC pixels to QA_AOD=0 (best quality only)")
    args = ap.parse_args()

    with rasterio.open(args.bb) as bs:
        bb = bs.read(1).astype(np.float32)
        if bs.nodata is not None:
            bb[bb == bs.nodata] = np.nan
        bb_tf, bb_crs = bs.transform, bs.crs
        prof = bs.profile
        bbox = bs.bounds  # (left, bottom, right, top)

    with rasterio.open(args.qa) as qs:
        qa = qs.read(1)

    # MAIAC HDF 직접 읽기
    pattern = f"MCD19A2.A{args.bb_date}*.hdf"
    hdfs = sorted(glob.glob(os.path.join(args.maiac_dir, pattern)))
    print(f"MAIAC HDFs ({pattern}): {len(hdfs)}개")
    for h in hdfs:
        print(f"  {h}")

    bb_bbox = (bbox.left, bbox.bottom, bbox.right, bbox.top)
    lon, lat, aod = read_maiac_pixels(hdfs, bb_bbox, qa_mask=args.qa_best)
    print(f"Raw MAIAC pixels in BB bbox: {len(aod):,}")
    if aod.size:
        print(f"  AOD range: {aod.min():.3f} .. {aod.max():.3f}  mean={aod.mean():.3f}")

    # MAIAC 픽셀을 BB 격자로 직접 매핑 (1km cell 안의 모든 BB 픽셀 = 동일 MAIAC 값)
    maiac_on_bb = rasterize_to_grid(lon, lat, aod, bb_tf, bb.shape)
    valid_pre = np.isfinite(maiac_on_bb).sum()
    print(f"MAIAC on BB grid: {valid_pre:,} valid pixels")

    # 빈 곳 채움: nearest neighbor (1km MAIAC blocks 사이 보간)
    if not np.isfinite(maiac_on_bb).any():
        print("ERROR: no MAIAC pixels rasterized")
        sys.exit(1)
    valid_m = np.isfinite(maiac_on_bb)
    # 1km 블록을 따라 채우기: large gaussian fill
    sigma = 25.0
    num = gaussian_filter(np.where(valid_m, maiac_on_bb, 0.0), sigma=sigma)
    den = gaussian_filter(valid_m.astype(np.float32), sigma=sigma)
    maiac_filled = np.where(den > 0.001, num / np.maximum(den, 1e-9),
                            float(np.nanmean(maiac_on_bb))).astype(np.float32)

    # DDV 거리 → 가중치
    ddv_mask = (qa == 1)
    px_size_m = abs(bb_tf.a) * 111320.0 if bb_crs.is_geographic else abs(bb_tf.a)
    print(f"\nDDV pixels: {ddv_mask.sum():,}  px_size={px_size_m:.1f}m")
    dist_px = distance_transform_edt(~ddv_mask) if ddv_mask.any() else np.full(bb.shape, 1e9)
    dist_m = dist_px * px_size_m
    w = np.exp(-dist_m / args.length_m).astype(np.float32)
    print(f"Weight: w<0.1: {100*(w<0.1).mean():.1f}%  w>0.5: {100*(w>0.5).mean():.1f}%")

    fused = w * bb + (1.0 - w) * maiac_filled
    fused[~np.isfinite(bb)] = np.nan
    fused = np.clip(fused, 0.0, 5.0).astype(np.float32)

    prof2 = prof.copy()
    prof2.update(dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(args.out, "w", **prof2) as d:
        d.write(fused, 1)
    print(f"\nSaved: {args.out}")
    v = fused[np.isfinite(fused)]
    print(f"  mean={v.mean():.3f}  median={np.median(v):.3f}  std={v.std():.3f}  range=[{v.min():.3f},{v.max():.3f}]")

    print("\n--- Anomaly 위치 검증 ---")
    for lat_p, lon_p in [(37.113468, 126.890428), (37.099250, 126.963510)]:
        r, c = rowcol(bb_tf, lon_p, lat_p)
        if 0 <= r < bb.shape[0] and 0 <= c < bb.shape[1]:
            print(f"  ({lat_p:.4f}, {lon_p:.4f}): "
                  f"BB={float(bb[r,c]):.3f}  MAIAC_raw={float(maiac_on_bb[r,c]):.3f}  "
                  f"MAIAC_filled={float(maiac_filled[r,c]):.3f}  "
                  f"blended={float(fused[r,c]):.3f}  w={float(w[r,c]):.3f}  "
                  f"dist_DDV={float(dist_m[r,c]):.0f}m")


if __name__ == "__main__":
    main()
