# =============================================================================
# Coherence Change Detection (CCD) — 지진 피해 예비분석
# [DISCLAIMER] 현장 미검증 예비분석. 확정 피해 판정 아님.
# =============================================================================

# ── CONFIG ────────────────────────────────────────────────────────────────────
WORK_DIR    = r"<DATA_ROOT>\Venezuela\left"
FILE_PRE    = "20260611_20260618_Orb_Stack_Ifg_Deb_Flt_IW1_TC.tif"   # γ_pre (baseline)
FILE_CO     = "20260618_20260624_Orb_Stack_Ifg_Deb_Flt_TC.tif"        # γ_co  (co-event)
OUTPUT_DIR  = r"<DATA_ROOT>\Venezuela\left\output"

POL         = "VV"        # 1차 편파 (VV 또는 VH)
COH_THR     = 0.4         # γ_pre 최소 임계값 (안정 지역 필터)
EPS         = 1e-6

# 변화강도 등급 경계 (ΔCoh 기준 — 절대 손상 등급 아님, 상대 변화강도)
THR_LOW     = 0.2
THR_MID     = 0.4
THR_HIGH    = 0.6
# ─────────────────────────────────────────────────────────────────────────────

import os, sys, warnings
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.font_manager as fm
from pathlib import Path

# Windows 한글 폰트 설정
for _fn in ["Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"]:
    if any(_fn.lower() in f.name.lower() for f in fm.fontManager.ttflist):
        matplotlib.rc("font", family=_fn)
        break
matplotlib.rcParams["axes.unicode_minus"] = False

warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)

os.makedirs(OUTPUT_DIR, exist_ok=True)

PATH_PRE = os.path.join(WORK_DIR, FILE_PRE)
PATH_CO  = os.path.join(WORK_DIR, FILE_CO)


# ── 함수 정의 ─────────────────────────────────────────────────────────────────

def check_file(path):
    if not os.path.exists(path):
        sys.exit(f"[ERROR] 파일 없음: {path}")

def print_meta(label, src):
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(f"  파일   : {src.name}")
    print(f"  밴드수 : {src.count}")
    print(f"  dtype  : {src.dtypes}")
    print(f"  nodata : {src.nodata}")
    print(f"  CRS    : {src.crs}")
    print(f"  Shape  : {src.height} x {src.width}  (H×W)")
    print(f"  Transform: {src.transform}")
    px = abs(src.transform.a)
    py = abs(src.transform.e)
    print(f"  픽셀크기: {px:.6f}° × {py:.6f}°  (≈{px*111320:.1f} m × {py*111320:.1f} m at equator)")
    descs = src.descriptions
    tags  = src.tags()
    print(f"  Band descriptions: {descs}")
    print(f"  Tags (top-level) : {tags}")
    for b in range(1, src.count + 1):
        bt = src.tags(b)
        print(f"  Band {b} tags: {bt}")

def band_stats(data, label):
    valid = data[np.isfinite(data) & (data != 0)]
    if valid.size == 0:
        print(f"  [{label}] 유효 픽셀 없음!")
        return
    p = np.percentile(valid, [1, 5, 25, 50, 75, 95, 99])
    print(f"  [{label}] n={valid.size:,}  "
          f"min={valid.min():.4f}  max={valid.max():.4f}  "
          f"mean={valid.mean():.4f}  std={valid.std():.4f}")
    print(f"           p1={p[0]:.4f}  p5={p[1]:.4f}  p25={p[2]:.4f}  "
          f"p50={p[3]:.4f}  p75={p[4]:.4f}  p95={p[5]:.4f}  p99={p[6]:.4f}")

def detect_pol_band(src, pol):
    """밴드 인덱스(1-based) 반환. 메타데이터 → 이름 → 순서 순으로 탐색."""
    pol_u = pol.upper()
    # 1) band descriptions
    for i, d in enumerate(src.descriptions, 1):
        if d and pol_u in str(d).upper():
            return i, f"description '{d}'"
    # 2) band tags
    for i in range(1, src.count + 1):
        bt = src.tags(i)
        for v in bt.values():
            if pol_u in str(v).upper():
                return i, f"tag '{v}'"
    # 3) top-level tags
    tg = src.tags()
    for v in tg.values():
        if pol_u in str(v).upper():
            pass  # top-level tag는 밴드 매핑 불확실 — 건너뜀
    # 4) 관례적 순서: VH=1, VV=2 (SNAP 기본 출력 순서)
    fallback = {"VH": 1, "VV": 2}
    if pol_u in fallback and src.count >= fallback[pol_u]:
        idx = fallback[pol_u]
        return idx, f"관례 순서(VH=1,VV=2) band {idx} — 메타데이터 미확인"
    sys.exit(f"[ERROR] '{pol}' 밴드를 {src.name}에서 찾을 수 없음. "
             f"밴드수={src.count}, descriptions={src.descriptions}")

def load_band(path, pol):
    """지정 편파 밴드를 float32 배열로 반환. nodata/0 → NaN."""
    with rasterio.open(path) as src:
        idx, how = detect_pol_band(src, pol)
        print(f"  [{pol}] band {idx} 선택 (근거: {how})")
        arr = src.read(idx).astype(np.float32)
        nd  = src.nodata
        if nd is not None:
            arr[arr == nd] = np.nan
        arr[arr == 0] = np.nan
        return arr, src.profile, src.transform, src.crs

def align_grids(arr_co, profile_co, ref_transform, ref_crs, ref_shape):
    """γ_co를 γ_pre 격자에 맞춰 bilinear reproject."""
    dst = np.full(ref_shape, np.nan, dtype=np.float32)
    reproject(
        source=arr_co,
        destination=dst,
        src_transform=profile_co["transform"],
        src_crs=profile_co["crs"],
        dst_transform=ref_transform,
        dst_crs=ref_crs,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return dst

def compute_dcoh(pre, co):
    dcoh      = pre - co
    dcoh_norm = (pre - co) / (pre + EPS)
    return dcoh, dcoh_norm

def classify(dcoh, pre_mask):
    """등급 분류: 0=무효, 1=LOW, 2=MID, 3=HIGH."""
    cls = np.zeros(dcoh.shape, dtype=np.uint8)
    valid = pre_mask & np.isfinite(dcoh)
    cls[valid & (dcoh >= THR_LOW) & (dcoh <  THR_MID )] = 1
    cls[valid & (dcoh >= THR_MID) & (dcoh <  THR_HIGH)] = 2
    cls[valid & (dcoh >= THR_HIGH)]                       = 3
    return cls

def pixel_area_km2(transform):
    """픽셀 면적 ㎢. 도 단위 transform이면 equator 기준 근사."""
    dx = abs(transform.a)
    dy = abs(transform.e)
    m_per_deg = 111320.0
    return (dx * m_per_deg) * (dy * m_per_deg) / 1e6

def print_class_table(cls, px_km2):
    labels = {1: "LOW  (0.2≤ΔCoh<0.4)", 2: "MID  (0.4≤ΔCoh<0.6)", 3: "HIGH (ΔCoh≥0.6)"}
    print(f"\n  {'등급':<28} {'픽셀수':>12} {'면적(㎢)':>12}")
    print(f"  {'─'*54}")
    total_px = 0
    for k in [1, 2, 3]:
        n = int((cls == k).sum())
        total_px += n
        print(f"  {labels[k]:<28} {n:>12,} {n*px_km2:>12.3f}")
    print(f"  {'─'*54}")
    print(f"  {'합계 (변화 감지)':<28} {total_px:>12,} {total_px*px_km2:>12.3f}")
    print(f"  ※ 상대적 변화강도 등급. 절대 손상 등급 아님.")

def save_geotiff(path, arr, profile, dtype, nodata_val):
    p = profile.copy()
    p.update(count=1, dtype=dtype, nodata=nodata_val, compress="lzw", driver="GTiff")
    with rasterio.open(path, "w", **p) as dst:
        dst.write(arr.astype(dtype), 1)
    print(f"  저장: {path}")

def make_plots(pre, co, dcoh, cls, pol, transform):
    # ── 3-패널 비교 ───────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(f"Coherence Change Detection — {pol}  [예비분석, 미검증]",
                 fontsize=13, fontweight="bold")

    im0 = axes[0].imshow(pre,  cmap="gray", vmin=0, vmax=1, aspect="auto")
    axes[0].set_title("γ_pre  (20260611–20260618, baseline)")
    plt.colorbar(im0, ax=axes[0], fraction=0.046)

    im1 = axes[1].imshow(co,   cmap="gray", vmin=0, vmax=1, aspect="auto")
    axes[1].set_title("γ_co   (20260618–20260624, co-event)")
    plt.colorbar(im1, ax=axes[1], fraction=0.046)

    im2 = axes[2].imshow(dcoh, cmap="RdBu_r", vmin=-0.5, vmax=1.0, aspect="auto")
    axes[2].set_title("ΔCoh = γ_pre − γ_co  (빨강=변화큼)")
    plt.colorbar(im2, ax=axes[2], fraction=0.046)

    for ax in axes:
        ax.axis("off")

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, f"ccd_compare_{pol}.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  저장: {out}")

    # ── 등급 분류도 ──────────────────────────────────────────────────────────
    cmap_cls = matplotlib.colors.ListedColormap(
        ["#d9d9d9", "#fee08b", "#fc8d59", "#d73027"])  # 무효/LOW/MID/HIGH
    norm_cls = matplotlib.colors.BoundaryNorm([0, 1, 2, 3, 4], 4)

    fig2, ax2 = plt.subplots(figsize=(10, 8))
    im3 = ax2.imshow(cls, cmap=cmap_cls, norm=norm_cls, aspect="auto")
    ax2.set_title(f"변화강도 등급 분류 — {pol}  [예비분석, 미검증]", fontsize=12)
    ax2.axis("off")
    patches = [
        mpatches.Patch(color="#d9d9d9", label="무효"),
        mpatches.Patch(color="#fee08b", label="LOW  (0.2–0.4)"),
        mpatches.Patch(color="#fc8d59", label="MID  (0.4–0.6)"),
        mpatches.Patch(color="#d73027", label="HIGH (≥0.6)"),
    ]
    ax2.legend(handles=patches, loc="lower right", fontsize=9)
    out2 = os.path.join(OUTPUT_DIR, f"ccd_class_{pol}.png")
    plt.savefig(out2, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  저장: {out2}")


def save_summary(lines):
    path = os.path.join(OUTPUT_DIR, "summary.txt")
    mode = "a" if os.path.exists(path) else "w"
    with open(path, mode, encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  저장: {path}")


DISCLAIMER = (
    "\n[DISCLAIMER] 본 결과는 현장 미검증 예비분석이다. "
    "단일 co-event 페어 + baseline 1개 기반으로 통계적 검증 불가하며, "
    "시간·수직 baseline 미정규화, 토지피복 의존 false positive 가능. "
    "coherence 손실은 건물 붕괴 외 잔해·강수·작물 변화 등으로도 발생할 수 있다. "
    "확정 피해 판정 아님."
)


# ── STEP 0 : 밴드 검증 ───────────────────────────────────────────────────────
def step0():
    print("\n" + "="*60)
    print("  STEP 0 — 밴드 메타데이터 검증")
    print("="*60)

    check_file(PATH_PRE)
    check_file(PATH_CO)

    coh_suspect = False

    for label, path in [("γ_pre (baseline)", PATH_PRE), ("γ_co (co-event)", PATH_CO)]:
        with rasterio.open(path) as src:
            print_meta(label, src)
            print(f"\n  ── 밴드별 값 통계 ──")
            for b in range(1, src.count + 1):
                arr = src.read(b).astype(np.float32)
                nd  = src.nodata
                if nd is not None:
                    arr[arr == nd] = np.nan
                arr[arr == 0] = np.nan
                band_stats(arr, f"band {b}")
                valid = arr[np.isfinite(arr)]
                if valid.size > 0:
                    mn, mx = valid.min(), valid.max()
                    if mn < -0.1 or mx > 1.1:
                        coh_suspect = True
                        print(f"  [WARNING] band {b}: 값 범위 [{mn:.4f}, {mx:.4f}] → "
                              f"coherence [0,1] 범위 벗어남!")

    # 격자 일치 여부 확인
    with rasterio.open(PATH_PRE) as s1, rasterio.open(PATH_CO) as s2:
        same_shape = (s1.height == s2.height) and (s1.width == s2.width)
        same_crs   = s1.crs == s2.crs
        same_tr    = s1.transform == s2.transform
        print(f"\n  ── 격자 일치 여부 ──")
        print(f"  Shape 일치  : {same_shape}  ({s1.height}x{s1.width} vs {s2.height}x{s2.width})")
        print(f"  CRS 일치    : {same_crs}")
        print(f"  Transform 일치: {same_tr}")
        if not (same_shape and same_crs and same_tr):
            print("  → 격자 불일치. γ_co를 γ_pre 격자로 reproject/resample 예정 (bilinear).")
        else:
            print("  → 격자 일치. reproject 불필요.")

    if coh_suspect:
        print("\n" + "!"*60)
        print("  [STOP] coherence 범위 이상 감지.")
        print("  이 밴드는 coherence가 아닌 것으로 보인다.")
        print("  실제 coherence 밴드 파일이 맞는지 확인 필요.")
        print("  값이 [-π, π]면 위상(phase), 음수 dB면 강도(intensity)일 수 있음.")
        print("  확인 후 다시 실행해주세요.")
        print("!"*60)
        return False

    print("\n  → coherence 범위 정상 확인. STEP 1–5 진행 가능.")
    return True


# ── STEP 1–5 : 본 분석 ───────────────────────────────────────────────────────
def run_analysis(pol):
    print("\n" + "="*60)
    print(f"  분석 시작 — 편파: {pol}")
    print("="*60)

    # STEP 1 — 밴드 로드
    print(f"\n[STEP 1] 편파 {pol} 밴드 로드")
    with rasterio.open(PATH_PRE) as src:
        idx_pre, how_pre = detect_pol_band(src, pol)
        print(f"  γ_pre: band {idx_pre}  ({how_pre})")
        pre_raw = src.read(idx_pre).astype(np.float32)
        nd = src.nodata
        if nd is not None:
            pre_raw[pre_raw == nd] = np.nan
        pre_raw[pre_raw == 0] = np.nan
        pre_profile   = src.profile
        pre_transform = src.transform
        pre_crs       = src.crs
        pre_shape     = (src.height, src.width)

    with rasterio.open(PATH_CO) as src:
        idx_co, how_co = detect_pol_band(src, pol)
        print(f"  γ_co : band {idx_co}  ({how_co})")
        co_raw = src.read(idx_co).astype(np.float32)
        nd = src.nodata
        if nd is not None:
            co_raw[co_raw == nd] = np.nan
        co_raw[co_raw == 0] = np.nan
        co_profile = src.profile.copy()
        co_profile["transform"] = src.transform
        co_profile["crs"]       = src.crs
        same_grid = (src.height == pre_shape[0] and src.width == pre_shape[1]
                     and src.crs == pre_crs and src.transform == pre_transform)

    if not same_grid:
        print("  [STEP 1] 격자 불일치 → bilinear reproject 수행 중...")
        co_aligned = align_grids(co_raw, co_profile, pre_transform, pre_crs, pre_shape)
        print("  reproject 완료.")
    else:
        co_aligned = co_raw

    pre = pre_raw
    co  = co_aligned

    # STEP 2 — ΔCoh 계산
    print(f"\n[STEP 2] ΔCoh 계산")
    dcoh, dcoh_norm = compute_dcoh(pre, co)
    valid_all = np.isfinite(dcoh)
    print(f"  유효 픽셀(ΔCoh): {valid_all.sum():,}")
    band_stats(dcoh[valid_all], "ΔCoh 전체")

    # STEP 3 — 마스킹
    print(f"\n[STEP 3] γ_pre ≥ {COH_THR} 마스킹")
    pre_mask = np.isfinite(pre) & (pre >= COH_THR)
    print(f"  마스킹 전 유효 픽셀: {valid_all.sum():,}")
    print(f"  마스킹 후 유효 픽셀: {(pre_mask & valid_all).sum():,}")

    # STEP 4 — 등급화
    print(f"\n[STEP 4] 변화강도 등급화")
    cls = classify(dcoh, pre_mask)
    px_km2 = pixel_area_km2(pre_transform)
    print(f"  픽셀 크기: {px_km2:.6f} ㎢")
    print_class_table(cls, px_km2)

    # STEP 5 — 출력물 저장
    print(f"\n[STEP 5] 출력물 저장 → {OUTPUT_DIR}")

    # GeoTIFF
    dcoh_out = dcoh.copy()
    dcoh_out[~np.isfinite(dcoh_out)] = -9999.0
    save_geotiff(
        os.path.join(OUTPUT_DIR, f"dcoh_{pol}.tif"),
        dcoh_out, pre_profile, "float32", -9999.0
    )
    save_geotiff(
        os.path.join(OUTPUT_DIR, f"dcoh_class_{pol}.tif"),
        cls, pre_profile, "uint8", 0
    )

    # PNG
    make_plots(pre, co, dcoh, cls, pol, pre_transform)

    # Summary 텍스트
    lines = [
        f"\n{'='*60}",
        f"  편파: {pol}",
        f"  γ_pre : {FILE_PRE}",
        f"  γ_co  : {FILE_CO}",
        f"  COH_THR: {COH_THR}  |  LOW≥{THR_LOW}  MID≥{THR_MID}  HIGH≥{THR_HIGH}",
        f"  픽셀크기: {px_km2:.6f} ㎢",
        f"",
        f"  등급별 결과:",
    ]
    for k, lab in [(1, "LOW "), (2, "MID "), (3, "HIGH")]:
        n = int((cls == k).sum())
        lines.append(f"    {lab} : {n:>10,} px  {n*px_km2:.3f} ㎢")
    lines.append(DISCLAIMER)
    save_summary(lines)

    print(DISCLAIMER)
    return True


# ── 메인 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ok = step0()
    if not ok:
        sys.exit(0)

    # STEP 0 통과 → VV, VH 순으로 분석
    for pol in ["VV", "VH"]:
        run_analysis(pol)

    print("\n" + "="*60)
    print("  전체 분석 완료.")
    print(f"  출력 폴더: {OUTPUT_DIR}")
    print("="*60)
    print(DISCLAIMER)
