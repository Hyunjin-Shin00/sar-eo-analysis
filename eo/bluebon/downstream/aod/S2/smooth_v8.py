"""bb_aod_v8.tif에 추가 Gaussian 스무딩만 적용해 출력."""
import argparse
import numpy as np
import rasterio
from scipy.ndimage import gaussian_filter

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="src", default="bb_aod_v8.tif")
    ap.add_argument("--out", default="bb_aod_v8_sm.tif")
    ap.add_argument("--sigma-px", type=float, default=20.0,
                    help="추가 Gaussian sigma (출력 격자 픽셀 단위). default=20 (~400m at 20m)")
    args = ap.parse_args()

    with rasterio.open(args.src) as s:
        arr = s.read(1).astype(np.float32)
        nd  = s.nodata
        prof = s.profile
    if nd is not None:
        arr = np.where(arr == nd, np.nan, arr)

    valid = np.isfinite(arr)
    a0 = np.where(valid, arr, 0.0).astype(np.float32)
    w0 = valid.astype(np.float32)
    num = gaussian_filter(a0, sigma=args.sigma_px)
    den = gaussian_filter(w0, sigma=args.sigma_px)
    sm  = num / np.maximum(den, 1e-9)
    out = np.where(valid, sm, np.nan).astype(np.float32)

    prof.update(dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(args.out, "w", **prof) as d:
        d.write(out, 1)

    v = out[np.isfinite(out)]
    print(f"In  : {args.src}  mean={np.nanmean(arr):.3f}  std={np.nanstd(arr):.3f}")
    print(f"Out : {args.out}  mean={v.mean():.3f}  std={v.std():.3f}  sigma_px={args.sigma_px}")

if __name__ == "__main__":
    main()
