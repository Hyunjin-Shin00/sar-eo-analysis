import numpy as np, rasterio, matplotlib, os, sys
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from rasterio.warp import reproject, Resampling
from rasterio.windows import from_bounds
from rasterio.transform import rowcol

matplotlib.use("Agg")
matplotlib.rc("font", family="Malgun Gothic")
matplotlib.rcParams["axes.unicode_minus"] = False

# ── CONFIG ────────────────────────────────────────────────────────────────────
WORK    = r"<DATA_ROOT>\Venezuela\right"
OUT     = r"<DATA_ROOT>\Venezuela\right\output"
FILE_PRE = "20260613_20260618_Orb_Stack_Ifg_Deb_Flt_IW1_TC.tif"   # gamma_pre
FILE_CO  = "20260618_20260625_C8C0_Orb_Stack_Ifg_Deb_Flt_TC.tif"  # gamma_co

POL     = "VV"    # 1차 편파
COH_THR = 0.4
EPS     = 1e-6
THR_LOW, THR_MID, THR_HIGH = 0.2, 0.4, 0.6
# ─────────────────────────────────────────────────────────────────────────────

os.makedirs(OUT, exist_ok=True)
PATH_PRE = os.path.join(WORK, FILE_PRE)
PATH_CO  = os.path.join(WORK, FILE_CO)

POL_BAND = {"VH": 1, "VV": 2}   # SNAP 기본 관례


def overlap_bounds(src1, src2):
    b1, b2 = src1.bounds, src2.bounds
    left   = max(b1.left,   b2.left)
    bottom = max(b1.bottom, b2.bottom)
    right  = min(b1.right,  b2.right)
    top    = min(b1.top,    b2.top)
    if left >= right or bottom >= top:
        sys.exit("[ERROR] 두 파일 간 공통 영역 없음")
    return left, bottom, right, top


def read_clipped(path, bidx, window, out_shape, ref_transform, ref_crs, src_path_ref):
    """파일에서 window 영역만 읽고 ref 격자에 맞게 reproject."""
    with rasterio.open(path) as src:
        # ref와 같은 파일이면 window 직접 read, 다르면 reproject
        if path == src_path_ref:
            arr = src.read(bidx, window=window).astype(np.float32)
            nd = src.nodata
            if nd is not None:
                arr[arr == nd] = np.nan
            arr[arr == 0] = np.nan
            return arr
        else:
            src_arr = src.read(bidx).astype(np.float32)
            nd = src.nodata
            if nd is not None:
                src_arr[src_arr == nd] = np.nan
            src_arr[src_arr == 0] = np.nan
            dst = np.full(out_shape, np.nan, dtype=np.float32)
            reproject(src_arr, dst,
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=ref_transform, dst_crs=ref_crs,
                      resampling=Resampling.bilinear,
                      src_nodata=np.nan, dst_nodata=np.nan)
            return dst


def band_stats(arr, label):
    v = arr[np.isfinite(arr)]
    if v.size == 0:
        print(f"  [{label}] 유효 픽셀 없음")
        return
    p = np.percentile(v, [1, 5, 25, 50, 75, 95, 99])
    print(f"  [{label}] n={v.size:,}  min={v.min():.4f}  max={v.max():.4f}  "
          f"mean={v.mean():.4f}  std={v.std():.4f}")
    print(f"           p5={p[1]:.4f}  p25={p[2]:.4f}  p50={p[3]:.4f}  "
          f"p75={p[4]:.4f}  p95={p[5]:.4f}  p99={p[6]:.4f}")


def classify(dcoh, pre_mask):
    cls = np.zeros(dcoh.shape, dtype=np.uint8)
    valid = pre_mask & np.isfinite(dcoh)
    cls[valid & (dcoh >= THR_LOW) & (dcoh < THR_MID )] = 1
    cls[valid & (dcoh >= THR_MID) & (dcoh < THR_HIGH)] = 2
    cls[valid & (dcoh >= THR_HIGH)]                     = 3
    return cls


def pixel_area_km2(transform):
    dx = abs(transform.a)
    dy = abs(transform.e)
    return (dx * 111320) * (dy * 111320) / 1e6


def print_class_table(cls, px_km2):
    labels = {1: "LOW  (0.2<=DCoh<0.4)", 2: "MID  (0.4<=DCoh<0.6)", 3: "HIGH (DCoh>=0.6)"}
    print(f"\n  {'등급':<26} {'픽셀수':>12} {'면적(km2)':>12}")
    print(f"  {'─'*52}")
    total = 0
    for k in [1, 2, 3]:
        n = int((cls == k).sum())
        total += n
        print(f"  {labels[k]:<26} {n:>12,} {n*px_km2:>12.3f}")
    print(f"  {'─'*52}")
    print(f"  {'합계 (변화 감지)':<26} {total:>12,} {total*px_km2:>12.3f}")
    print("  ※ 상대적 변화강도 등급. 절대 손상 등급 아님.")


def save_geotiff(path, arr, ref_transform, ref_crs, dtype, nodata_val):
    h, w = arr.shape
    profile = dict(driver="GTiff", count=1, dtype=dtype,
                   crs=ref_crs, transform=ref_transform,
                   width=w, height=h, nodata=nodata_val, compress="lzw")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(dtype), 1)
    print(f"  저장: {path}")


def make_plots(pre, co, dcoh, cls, pol):
    # 3-패널 비교
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(f"Coherence Change Detection — {pol}  [예비분석, 미검증]",
                 fontsize=13, fontweight="bold")
    im0 = axes[0].imshow(pre,  cmap="gray", vmin=0, vmax=1, aspect="auto")
    axes[0].set_title("gamma_pre  (20260613-20260618, baseline)")
    plt.colorbar(im0, ax=axes[0], fraction=0.046)
    im1 = axes[1].imshow(co,   cmap="gray", vmin=0, vmax=1, aspect="auto")
    axes[1].set_title("gamma_co   (20260618-20260625, co-event)")
    plt.colorbar(im1, ax=axes[1], fraction=0.046)
    im2 = axes[2].imshow(dcoh, cmap="RdBu_r", vmin=-0.5, vmax=1.0, aspect="auto")
    axes[2].set_title("DCoh = pre - co  (빨강=변화큼)")
    plt.colorbar(im2, ax=axes[2], fraction=0.046)
    for ax in axes:
        ax.axis("off")
    plt.tight_layout()
    p = os.path.join(OUT, f"ccd_compare_{pol}.png")
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  저장: {p}")

    # 등급 분류도
    cmap_cls = matplotlib.colors.ListedColormap(
        ["#d9d9d9", "#fee08b", "#fc8d59", "#d73027"])
    norm_cls = matplotlib.colors.BoundaryNorm([0, 1, 2, 3, 4], 4)
    fig2, ax2 = plt.subplots(figsize=(10, 8))
    ax2.imshow(cls, cmap=cmap_cls, norm=norm_cls, aspect="auto")
    ax2.set_title(f"변화강도 등급 분류 — {pol}  [예비분석, 미검증]", fontsize=12)
    ax2.axis("off")
    patches = [
        mpatches.Patch(color="#d9d9d9", label="무효"),
        mpatches.Patch(color="#fee08b", label="LOW  (0.2-0.4)"),
        mpatches.Patch(color="#fc8d59", label="MID  (0.4-0.6)"),
        mpatches.Patch(color="#d73027", label="HIGH (>=0.6)"),
    ]
    ax2.legend(handles=patches, loc="lower right", fontsize=10)
    p2 = os.path.join(OUT, f"ccd_class_{pol}.png")
    plt.savefig(p2, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  저장: {p2}")


def run(pol):
    bidx = POL_BAND[pol]
    print(f"\n{'='*60}")
    print(f"  편파: {pol}  (band {bidx})")
    print(f"{'='*60}")

    with rasterio.open(PATH_PRE) as src_pre, rasterio.open(PATH_CO) as src_co:
        # 공통 영역 계산
        left, bottom, right, top = overlap_bounds(src_pre, src_co)
        print(f"\n[OVERLAP]  lon {left:.5f}~{right:.5f}  lat {bottom:.5f}~{top:.5f}")
        print(f"           W={(right-left)*111320:.0f}m  H={(top-bottom)*111320:.0f}m")

        # pre 격자 위 overlap window
        win = from_bounds(left, bottom, right, top, src_pre.transform)
        win = win.round_lengths().round_offsets()
        ref_transform = src_pre.window_transform(win)
        ref_crs = src_pre.crs
        out_h = int(win.height)
        out_w = int(win.width)
        print(f"  클립 shape: {out_h} x {out_w}  (H x W)")

        # pre 읽기 (window 직접 슬라이스)
        pre = src_pre.read(bidx, window=win).astype(np.float32)
        pre[pre == 0] = np.nan
        if src_pre.nodata is not None:
            pre[pre == src_pre.nodata] = np.nan

        # co 읽기 → pre 격자로 reproject
        co_raw = src_co.read(bidx).astype(np.float32)
        co_raw[co_raw == 0] = np.nan
        if src_co.nodata is not None:
            co_raw[co_raw == src_co.nodata] = np.nan

    # co를 pre overlap 격자로 reproject
    co = np.full((out_h, out_w), np.nan, dtype=np.float32)
    with rasterio.open(PATH_CO) as src_co:
        reproject(co_raw, co,
                  src_transform=src_co.transform, src_crs=src_co.crs,
                  dst_transform=ref_transform, dst_crs=ref_crs,
                  resampling=Resampling.bilinear,
                  src_nodata=np.nan, dst_nodata=np.nan)

    print("\n[STEP 0] 값 통계 확인")
    band_stats(pre, f"gamma_pre {pol}")
    band_stats(co,  f"gamma_co  {pol}")

    print("\n[STEP 2] DCoh 계산")
    dcoh = pre - co
    band_stats(dcoh, "DCoh 전체")

    print(f"\n[STEP 3] gamma_pre >= {COH_THR} 마스킹")
    pre_mask = np.isfinite(pre) & (pre >= COH_THR)
    n_before = int(np.isfinite(dcoh).sum())
    n_after  = int((pre_mask & np.isfinite(dcoh)).sum())
    print(f"  마스킹 전: {n_before:,}  →  후: {n_after:,}")

    print("\n[STEP 4] 변화강도 등급화")
    cls = classify(dcoh, pre_mask)
    px_km2 = pixel_area_km2(ref_transform)
    print(f"  픽셀 크기: {px_km2:.6f} km2")
    print_class_table(cls, px_km2)

    print(f"\n[STEP 5] 출력 저장 -> {OUT}")
    dcoh_out = np.where(np.isfinite(dcoh), dcoh, -9999.0).astype(np.float32)
    save_geotiff(os.path.join(OUT, f"dcoh_{pol}.tif"),
                 dcoh_out, ref_transform, ref_crs, "float32", -9999.0)
    save_geotiff(os.path.join(OUT, f"dcoh_class_{pol}.tif"),
                 cls, ref_transform, ref_crs, "uint8", 0)
    make_plots(pre, co, dcoh, cls, pol)

    # summary
    lines = [
        f"\n{'='*60}",
        f"  [right] 편파: {pol}",
        f"  gamma_pre : {FILE_PRE}",
        f"  gamma_co  : {FILE_CO}",
        f"  overlap: lon {left:.5f}~{right:.5f}  lat {bottom:.5f}~{top:.5f}",
        f"  clip shape: {out_h}x{out_w}  px={px_km2:.6f}km2",
        f"  COH_THR={COH_THR}  LOW>={THR_LOW}  MID>={THR_MID}  HIGH>={THR_HIGH}",
        "",
    ]
    for k, lab in [(1,"LOW "),(2,"MID "),(3,"HIGH")]:
        n = int((cls==k).sum())
        lines.append(f"    {lab}: {n:>10,} px  {n*px_km2:.3f} km2")
    lines.append("\n[DISCLAIMER] 현장 미검증 예비분석. 단일 co-event 페어 기반."
                 " coherence 손실은 건물 붕괴 외 다양한 원인 가능. 확정 피해 판정 아님.")
    with open(os.path.join(OUT, "summary.txt"), "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  저장: {os.path.join(OUT, 'summary.txt')}")

    print("\n[DISCLAIMER] 현장 미검증 예비분석. 확정 피해 판정 아님.")


if __name__ == "__main__":
    for pol in ["VV", "VH"]:
        run(pol)
    print("\n완료.")
