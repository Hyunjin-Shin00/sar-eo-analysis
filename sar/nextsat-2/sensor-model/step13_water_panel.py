"""Step 13: 백록담 수체 판독용 4열 패널 (가독성 개선판).

    python step13_water_panel.py

step12 의 3열 그림이 (1) 분화구가 작고 (2) 선이 영상을 가리고 (3) 스페클로 원본 dB 가
판독 불가라 만든 판독 전용 그림.

행 = 분화구 자료가 있는 8씬만 (결측 4씬은 각주)
열 = N2 dB(3x3 멀티룩) | N2 이상치(국지입사각 보정) | S2 트루컬러  (S1 열 제거)
범위 = 분화구 중심 ±400 m (0.8x0.8 km) -> 분화구(지름 550 m)가 화면을 채움
선 = 노랑 실선 = DEM 최저 5 %(물이 고이는 자리, SAR 와 무관한 지형 기준)
     청록 실선 = **광학(S2) NDWI>0.1 수면** (눈·구름 제외) - SAR 와 독립적인 정답 기준
     분화구 바닥 윤곽선은 판독을 가려 제거

출력: Output/halla/water/panel_water_readable.png
"""
import os, csv, glob
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from scipy.ndimage import uniform_filter, binary_dilation
from skimage.morphology import reconstruction
from pyproj import Transformer
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
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
S1D, S2D, LEG = (os.path.join(HAL, "reference", "s1"), os.path.join(HAL, "reference", "s2"),
                 os.path.join(HAL, "legacy"))
OUTD = os.path.join(HAL, "water")
DEM_PATH = "<DATA_ROOT>/N2_InSAR/DEM/cop_dem_N33E126.tif"
BLD_LON, BLD_LAT = 126.53310, 33.36156
GRID, HALF, ZOOM = 5.0, 1000.0, 400.0
EPSG = 32652

tf = Transformer.from_crs(4326, EPSG, always_xy=True)
E0, N0 = tf.transform(BLD_LON, BLD_LAT)
E0 = round(E0 / GRID) * GRID; N0 = round(N0 / GRID) * GRID
H = W = int(2 * HALF / GRID) + 1
DST_T = from_origin(E0 - HALF - GRID / 2, N0 + HALF + GRID / 2, GRID, GRID)
DST_CRS = "EPSG:%d" % EPSG
STROKE = [pe.withStroke(linewidth=2.0, foreground="white", alpha=0.85)]


def to_grid(path, band=1, resamp=Resampling.bilinear):
    out = np.full((H, W), np.nan, "float32")
    with rasterio.open(path) as s:
        reproject(s.read(band).astype("float32"), out, src_transform=s.transform, src_crs=s.crs,
                  dst_transform=DST_T, dst_crs=DST_CRS, resampling=resamp,
                  src_nodata=s.nodata if s.nodata is not None else np.nan, dst_nodata=np.nan)
    return out


dem = to_grid(DEM_PATH)
d0 = np.nan_to_num(dem, nan=float(np.nanmax(dem)))
seed = d0.copy(); seed[1:-1, 1:-1] = d0.max()
dep = reconstruction(seed, d0, method="erosion") - d0
yy, xx = np.mgrid[0:H, 0:W]
floor = (dep > 1.0) & (GRID * np.hypot(yy - H // 2, xx - W // 2) < 400)
SHOW = binary_dilation(floor, iterations=8)   # 바닥 + 40 m 여유만 이상치 표시
hf = np.where(floor, dem, np.nan)
core = np.isfinite(hf) & (hf <= np.nanpercentile(hf[np.isfinite(hf)], 5))

match = {r["n2_date"]: r for r in csv.DictReader(open(os.path.join(LEG, "sentinel_match.csv"), encoding="utf-8-sig"))}
s1av = {r["n2_date"]: r for r in csv.DictReader(open(os.path.join(LEG, "s1_match.csv"), encoding="utf-8-sig"))}
scn = {r["date"]: r for r in csv.DictReader(open(os.path.join(ROOT, "baengnokdam", "scenes.csv"), encoding="utf-8"))}


def n2_load(date):
    g = glob.glob(os.path.join(N2D, "%s_*_int_utm5m_aoi6km_coreg.tif" % date))
    if not g:
        return None
    f = g[0]
    I = to_grid(f)
    mk = to_grid(f.replace("_int_", "_mask_"), resamp=Resampling.nearest)
    li = to_grid(f.replace("_int_", "_locinc_"))
    good = np.isfinite(I) & (I > 0) & (mk == 0) & np.isfinite(li)
    F = floor & good
    if F.sum() < 0.3 * floor.sum():
        return None
    num = uniform_filter(np.nan_to_num(np.where(good, I, np.nan)), 3)
    den = uniform_filter(good.astype(float), 3)
    db = 10 * np.log10(np.where(den > 0.25, num / np.maximum(den, 1e-9), np.nan))
    ok = F & np.isfinite(db)
    x = np.cos(np.radians(li[ok])); y = db[ok]
    b = np.linalg.lstsq(np.column_stack([np.ones_like(x), x]), y, rcond=None)[0]
    r = np.full(db.shape, np.nan)
    allok = good & np.isfinite(db)
    r[allok] = db[allok] - (b[0] + b[1] * np.cos(np.radians(li[allok])))
    M, R = core & ok, ok & ~core
    d = float(np.nanmedian(r[M]) - np.nanmedian(r[R])) if M.sum() > 10 else np.nan
    return db, r, d, 100 * F.sum() / floor.sum()


DATES = [d for d in sorted(scn) if n2_load(d) is not None]
DROP = [d for d in sorted(set(list(match) + list(scn))) if d not in DATES]
print("행 %d씬: %s" % (len(DATES), ", ".join(DATES)))
print("제외 %d씬: %s" % (len(DROP), ", ".join(DROP)))

k = int(ZOOM / GRID); c = H // 2
sl = (slice(c - k, c + k + 1), slice(c - k, c + k + 1))
GRAY = matplotlib.colormaps["gray"].copy(); GRAY.set_bad("#7c8896")


def st(a, lo=3, hi=97):
    v = a[sl][np.isfinite(a[sl])]
    if v.size < 10:
        return a
    l, h = np.percentile(v, [lo, hi])
    return np.clip((a - l) / max(h - l, 1e-9), 0, 1)


def outlines(A, s2w=None, crater=False):
    A.contour(core.astype(float)[sl], [0.5], colors="#ffd60a", linewidths=1.6)
    if s2w is not None and s2w.sum() >= 3:
        A.contour(s2w.astype(float)[sl], [0.5], colors="#00e5ff", linewidths=1.6)
    A.set_xticks([]); A.set_yticks([])


n = len(DATES)
fig, ax = plt.subplots(n, 3, figsize=(11.6, 3.7 * n))
for i, date in enumerate(DATES):
    db, r, d, vp = n2_load(date)
    sc = scn[date]; m = match.get(date, {}); r1 = s1av.get(date, {})
    s2d = m.get("s2_date", "")
    s2w = None
    if s2d and os.path.exists(os.path.join(S2D, "S2_%s_%s_ndwi.tif" % (date, s2d))):
        nd = to_grid(os.path.join(S2D, "S2_%s_%s_ndwi.tif" % (date, s2d)))
        sm = to_grid(os.path.join(S2D, "S2_%s_%s_scl.tif" % (date, s2d)), resamp=Resampling.nearest)
        s2w = (nd > 0.1) & ~np.isin(sm, [3, 8, 9, 10, 11]) & floor
    hit = np.isfinite(d) and d < -1.0

    A = ax[i, 0]
    A.imshow(np.ma.masked_invalid(st(db)[sl]), cmap=GRAY, vmin=0, vmax=1)
    outlines(A, s2w)
    A.set_ylabel("%s  %s\ninc %.1f°" % (date, sc["tag"], float(sc["inc_center"])),
                 fontsize=12, fontweight="bold",
                 color=("#c1121f" if hit else "0.2"), rotation=0, ha="right", va="center", labelpad=14)
    if i == 0:
        A.set_title("N2 후방산란 (3×3 멀티룩)", fontsize=12, pad=8)

    A = ax[i, 1]
    rv = np.where(SHOW, r, np.nan)
    A.set_facecolor("#e9edf2")
    im = A.imshow(np.ma.masked_invalid(rv[sl]), cmap="RdBu_r", vmin=-4, vmax=4)
    outlines(A, s2w)
    A.text(0.03, 0.05, "최저부 %+.2f dB" % d, transform=A.transAxes, fontsize=13,
           fontweight="bold", color=("#c1121f" if hit else "#1d3557"), path_effects=STROKE)
    if hit:
        A.text(0.97, 0.05, "수체 후보", transform=A.transAxes, fontsize=12, ha="right",
               fontweight="bold", color="#c1121f", path_effects=STROKE)
    if i == 0:
        A.set_title("N2 이상치 (국지입사각 보정)\n파랑 = 어두움 = 물 후보", fontsize=12, pad=8)

    A = ax[i, 2]
    p2 = os.path.join(S2D, "S2_%s_%s_tci.tif" % (date, s2d)) if s2d else ""
    if p2 and os.path.exists(p2):
        rgb = np.stack([to_grid(p2, band=b, resamp=Resampling.nearest) for b in (1, 2, 3)], -1)
        A.imshow(np.clip(np.nan_to_num(rgb) / 255.0, 0, 1)[sl])
        fl2 = floor & np.isfinite(to_grid(os.path.join(S2D, "S2_%s_%s_scl.tif" % (date, s2d)),
                                          resamp=Resampling.nearest))
        sm = to_grid(os.path.join(S2D, "S2_%s_%s_scl.tif" % (date, s2d)), resamp=Resampling.nearest)
        snow = 100 * (fl2 & (sm == 11)).sum() / max(fl2.sum(), 1)
        txt = "%s (Δ%+d일) 눈 %.0f%%" % (s2d, int(m.get("s2_ddays", 0)), snow)
        if s2w is not None and s2w.sum() >= 3:
            txt += "\n수면 %.2f ha" % (s2w.sum() * GRID ** 2 / 1e4)
        A.text(0.03, 0.05, txt, transform=A.transAxes, fontsize=11, color="#0b2545",
               path_effects=STROKE)
    outlines(A, s2w)
    if i == 0:
        A.set_title("Sentinel-2 광학 트루컬러", fontsize=12, pad=8)


fig.suptitle("백록담 수체 탐지 — 분화구 중심 0.8×0.8 km · 최신 기하보정본(5 m 미세정합, 상대정합 0.6 m)\n"
             "노란선 = DEM 최저 5%%(물이 고이는 자리, 지형 기준) · "
             "청록선 = 광학(S2) NDWI>0.1 수면 — SAR 와 독립적인 정답 기준\n"
             "결측 제외 %d씬: %s" % (len(DROP), ", ".join(DROP)), fontsize=13, y=0.997)
plt.tight_layout(rect=[0.015, 0.035, 1, 0.972])
cax = fig.add_axes([0.30, 0.012, 0.22, 0.008])
cb = fig.colorbar(im, cax=cax, orientation="horizontal")
cb.set_label("N2 이상치 [dB]  (파랑 = 어두움 = 물 후보)", fontsize=11)
cb.ax.tick_params(labelsize=9)
os.makedirs(OUTD, exist_ok=True)
out = os.path.join(OUTD, "panel_water_readable.png")
plt.savefig(out, dpi=105, bbox_inches="tight"); plt.close(fig)
print("저장:", out)
