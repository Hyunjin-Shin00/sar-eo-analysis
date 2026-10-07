"""Step 12: N2 / Sentinel-1 / Sentinel-2 3열 비교 PNG (최신 기하보정본 기준).

    python step12_compare_3col.py

구 halla_baengnokdam/n2/work/step11_compare_png.py 를 **새 기하보정 산출물**로 갈아끼운 판.
바뀐 점
  · N2 열 = step10 미세정합본 `Output/baengnokdam/output/*_coreg.tif` (구: geo_5m_psm)
  · 공통격자 10 m -> **5 m** (N2 원 해상도에 맞춤)
  · 노란선 = DEM 최저 5 %(물이 고이는 자리) 추가, N2 제목에 **최저부 이상치 Δ dB** 표기
  · 적선 = 분화구 바닥(폐합요지), 청록선 = S2 NDWI>0.1 수체(눈·구름 제외)

출력: Output/halla/water/compare_3col_crater_new.png (±600 m),
      Output/halla/water/compare_3col_context_new.png (±1500 m)
"""
import os, csv, glob
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from scipy.ndimage import uniform_filter
from skimage.morphology import reconstruction
from pyproj import Transformer
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

for p in ["/mnt/c/Windows/Fonts/malgun.ttf", "/mnt/c/Windows/Fonts/malgunbd.ttf"]:
    if os.path.exists(p):
        fm.fontManager.addfont(p)
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "Output")
N2D = os.path.join(ROOT, "baengnokdam", "output")
HAL = os.path.join(ROOT, "halla")
S1D, S2D, LEG = os.path.join(HAL, "reference", "s1"), os.path.join(HAL, "reference", "s2"), os.path.join(HAL, "legacy")
OUTD = os.path.join(HAL, "water")
DEM_PATH = "/mnt/c/N2_InSAR/DEM/cop_dem_N33E126.tif"
BLD_LON, BLD_LAT = 126.53310, 33.36156
GRID, HALF = 5.0, 1500.0
EPSG = 32652

tf = Transformer.from_crs(4326, EPSG, always_xy=True)
E0, N0 = tf.transform(BLD_LON, BLD_LAT)
E0 = round(E0 / GRID) * GRID; N0 = round(N0 / GRID) * GRID
H = W = int(2 * HALF / GRID) + 1
DST_T = from_origin(E0 - HALF - GRID / 2, N0 + HALF + GRID / 2, GRID, GRID)
DST_CRS = "EPSG:%d" % EPSG


def to_grid(path, band=1, resamp=Resampling.bilinear):
    out = np.full((H, W), np.nan, "float32")
    with rasterio.open(path) as s:
        reproject(s.read(band).astype("float32"), out, src_transform=s.transform, src_crs=s.crs,
                  dst_transform=DST_T, dst_crs=DST_CRS, resampling=resamp,
                  src_nodata=s.nodata if s.nodata is not None else np.nan, dst_nodata=np.nan)
    return out


# ---------------------------------------------- 분화구 바닥 / 최저부 (5 m 공통격자)
dem = to_grid(DEM_PATH)
d0 = np.nan_to_num(dem, nan=float(np.nanmax(dem)))
seed = d0.copy(); seed[1:-1, 1:-1] = d0.max()
dep = reconstruction(seed, d0, method="erosion") - d0
yy, xx = np.mgrid[0:H, 0:W]
dist = GRID * np.hypot(yy - H // 2, xx - W // 2)
floor = (dep > 1.0) & (dist < 400)
hf = np.where(floor, dem, np.nan)
core = np.isfinite(hf) & (hf <= np.nanpercentile(hf[np.isfinite(hf)], 5))
print("분화구 바닥 %d px (%.2f ha) | 최저5%% %d px (%.2f ha)"
      % (floor.sum(), floor.sum() * GRID ** 2 / 1e4, core.sum(), core.sum() * GRID ** 2 / 1e4))

match = {r["n2_date"]: r for r in csv.DictReader(open(os.path.join(LEG, "sentinel_match.csv"), encoding="utf-8-sig"))}
s1av = {r["n2_date"]: r for r in csv.DictReader(open(os.path.join(LEG, "s1_match.csv"), encoding="utf-8-sig"))}
scn = {r["date"]: r for r in csv.DictReader(open(os.path.join(ROOT, "baengnokdam", "scenes.csv"), encoding="utf-8"))}
DATES = sorted(set(list(match) + list(scn)))


def n2_anom(date):
    """최신 정합본에서 최저부 이상치 Δ dB (국지입사각 보정, 3x3 멀티룩)."""
    g = glob.glob(os.path.join(N2D, "%s_*_int_utm5m_aoi6km_coreg.tif" % date))
    if not g:
        return None, None, np.nan
    f = g[0]
    I = to_grid(f)
    mk = to_grid(f.replace("_int_", "_mask_"), resamp=Resampling.nearest)
    li = to_grid(f.replace("_int_", "_locinc_"))
    dbp = to_grid(f.replace("_int_", "_dB_"))
    good = np.isfinite(I) & (I > 0) & (mk == 0) & np.isfinite(li)
    F = floor & good
    if F.sum() < 300:
        return dbp, good, np.nan
    num = uniform_filter(np.nan_to_num(np.where(good, I, np.nan)), 3)
    den = uniform_filter(good.astype(float), 3)
    db = 10 * np.log10(np.where(den > 0.25, num / np.maximum(den, 1e-9), np.nan))
    ok = F & np.isfinite(db)
    x = np.cos(np.radians(li[ok])); y = db[ok]
    b = np.linalg.lstsq(np.column_stack([np.ones_like(x), x]), y, rcond=None)[0]
    r = np.full(db.shape, np.nan); r[ok] = y - (b[0] + b[1] * x)
    M, R = core & ok, ok & ~core
    d = float(np.nanmedian(r[M]) - np.nanmedian(r[R])) if M.sum() > 10 else np.nan
    return dbp, good, d


GRAY = matplotlib.colormaps["gray"].copy(); GRAY.set_bad("#b9c6d4")


def stretch(a, lo=2, hi=98, sl=None):
    v = a[sl][np.isfinite(a[sl])] if sl is not None else a[np.isfinite(a)]
    if v.size < 10:
        return a
    l, h = np.percentile(v, [lo, hi])
    return np.clip((a - l) / max(h - l, 1e-9), 0, 1)


CACHE = {d: n2_anom(d) for d in DATES}
for d in DATES:
    if not np.isnan(CACHE[d][2]):
        print("  %s 최저부 이상치 %+.2f dB" % (d, CACHE[d][2]))


def make_fig(halfm, fname, title):
    k = int(halfm / GRID); c = H // 2
    sl = (slice(c - k, c + k + 1), slice(c - k, c + k + 1))
    n = len(DATES)
    fig, ax = plt.subplots(n, 3, figsize=(10.6, 2.75 * n))
    for i, date in enumerate(DATES):
        m = match.get(date, {}); sc = scn.get(date, {})
        dbp, good, anom = CACHE[date]
        # --- N2
        A = ax[i, 0]
        if dbp is not None and np.isfinite(dbp[floor]).mean() > 0.02:
            a = np.where(good, dbp, np.nan) if good is not None else dbp
            A.imshow(np.ma.masked_invalid(stretch(a, sl=sl)[sl]), cmap=GRAY, vmin=0, vmax=1)
            vp = 100 * np.isfinite(a[floor]).mean()
            ttl = "N2 %s %s  inc %.1f°  유효 %.0f%%" % (
                date, sc.get("tag", ""), float(sc.get("inc_center", np.nan)), vp)
            if np.isfinite(anom):
                ttl += "\n최저부 이상치 %+.2f dB" % anom
                if anom < -1.0:
                    ttl += "  ◀ 저후방산란"
        else:
            if dbp is None:
                why = "N2 없음\n(LV1A SSC 가 스트립 앞 절반만 수록)"
            else:
                vp = 100 * np.isfinite(np.where(good, dbp, np.nan)[floor]).mean() if good is not None else 0.0
                why = "분화구 자료 없음\n(영상은 있으나 분화구가\n유효범위 밖 · 유효 %.0f%%)" % vp
            A.text(.5, .5, why, ha="center", va="center",
                   transform=A.transAxes, fontsize=8, color="0.4")
            ttl = "N2 %s %s" % (date, sc.get("tag", ""))
        A.set_title(ttl, fontsize=8,
                    color=("#c1121f" if (np.isfinite(anom) and anom < -1.0) else "0.15"))
        # --- S1
        A = ax[i, 1]
        r1 = s1av.get(date, {})
        pf = os.path.join(S1D, r1.get("s1_file", "")) if r1.get("s1_file") else ""
        if pf and os.path.exists(pf):
            A.imshow(np.ma.masked_invalid(stretch(to_grid(pf), sl=sl)[sl]), cmap=GRAY, vmin=0, vmax=1)
            A.set_title("S1 RTC %s (Δ%+d일)  %s %s" % (r1["s1_date"], int(r1["s1_ddays"]),
                                                     r1["s1_pol"], r1["s1_orbit"]), fontsize=8)
        else:
            A.text(.5, .5, "S1 없음\n(±10일 내 RTC 부재)\n최근접 %s Δ%s일"
                   % (r1.get("nearest_s1_date", "-"), r1.get("nearest_ddays", "-")),
                   ha="center", va="center", transform=A.transAxes, fontsize=8, color="0.4")
            A.set_title("S1 없음", fontsize=8)
        # --- S2
        A = ax[i, 2]
        s2d = m.get("s2_date", "")
        wm = None
        if s2d:
            p2 = os.path.join(S2D, "S2_%s_%s_tci.tif" % (date, s2d))
            if os.path.exists(p2):
                rgb = np.stack([to_grid(p2, band=b, resamp=Resampling.nearest) for b in (1, 2, 3)], -1)
                A.imshow(np.clip(np.nan_to_num(rgb) / 255.0, 0, 1)[sl])
            nd = to_grid(os.path.join(S2D, "S2_%s_%s_ndwi.tif" % (date, s2d)))
            sm = to_grid(os.path.join(S2D, "S2_%s_%s_scl.tif" % (date, s2d)), resamp=Resampling.nearest)
            fl2 = floor & np.isfinite(sm)
            snow = 100 * (fl2 & (sm == 11)).sum() / max(fl2.sum(), 1)
            cld = 100 * (fl2 & np.isin(sm, [3, 8, 9, 10])).sum() / max(fl2.sum(), 1)
            wm = (nd > 0.1) & ~np.isin(sm, [3, 8, 9, 10, 11]) & floor
            if wm.sum() >= 3:
                A.contour(wm.astype(float)[sl], levels=[0.5], colors="cyan", linewidths=1.1)
            A.set_title("S2 %s (Δ%+d일)  눈%.0f%% 구름%.0f%%\nNDWI>0.1 수체 %d px (%.2f ha)"
                        % (s2d, int(m.get("s2_ddays", 0)), snow, cld, int(wm.sum()),
                           wm.sum() * GRID ** 2 / 1e4), fontsize=8)
        else:
            A.text(.5, .5, "없음", ha="center", va="center", transform=A.transAxes)
        for j in range(3):
            ax[i, j].contour(floor.astype(float)[sl], levels=[0.5], colors="r", linewidths=0.9)
            ax[i, j].contour(core.astype(float)[sl], levels=[0.5], colors="#ffd60a", linewidths=1.0)
            if wm is not None and wm.sum() >= 3 and j < 2:
                ax[i, j].contour(wm.astype(float)[sl], levels=[0.5], colors="cyan", linewidths=1.0)
            ax[i, j].set_xticks([]); ax[i, j].set_yticks([])
    fig.suptitle(title, fontsize=13, y=1.0 - 0.004 * (12 / n))
    plt.tight_layout(rect=[0, 0, 1, 0.985])
    os.makedirs(OUTD, exist_ok=True)
    out = os.path.join(OUTD, fname)
    plt.savefig(out, dpi=110, bbox_inches="tight"); plt.close(fig)
    print("저장:", out)


make_fig(600, "compare_3col_crater_new.png",
         "백록담 수체 검증 (최신 기하보정본, 5 m 미세정합) - N2(X-band) / S1(C-band RTC) / S2(광학)  1.2x1.2 km\n"
         "적선=분화구 바닥, 노란선=DEM 최저5%(물 고이는 자리), 청록선=S2 NDWI>0.1 수체, 회청색=무자료")
make_fig(1500, "compare_3col_context_new.png",
         "백록담 주변 3x3 km (최신 기하보정본) - N2 / S1 / S2  적선=분화구 바닥, 노란선=최저5%, 청록선=S2 수체")
