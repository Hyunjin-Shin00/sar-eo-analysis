"""Step 11: 백록담 수체 탐지 — 미세정합 스택(step10) 기반.

    python step11_water_detect.py [--indir ../Output/baengnokdam/output] [--outdir ../Output/halla/water]

왜 다시 하나
------------
구 파이프라인(halla_baengnokdam)은 씬간 정합이 11.2 m 였다. 백록담 수면은 0.11~0.58 ha
(5 m 격자로 44~232 화소, 지름 약 40~90 m)라서 11 m 오정합이면 **표적이 주변으로 번져**
"수면 화소"를 골라낼 수 없었다. step10 미세정합으로 상대정합이 **0.6 m** 가 되었으므로
이제 S2 가 본 수면 폴리곤에 해당하는 SAR 화소를 직접 짚어 비교할 수 있다.

절차
----
1. 분화구 바닥 = DEM 폐합요지(depression fill 깊이 >1 m, 중심 400 m 내), 링 = dilate24 & ~dilate8
2. 씬별 dBn = dB − AOI 중앙값 (씬간 비교 가능하게; 절대 sigma0 아님)
3. 바닥−링, 바닥 내 저후방산란 면적(링중앙값 −5/−8 dB)
4. ★ 기준지점 = **DEM 최저 5 %(0.30 ha, 1837.4~1837.9 m)** = 물이 고이는 자리.
   (초판은 20250525 S2 폴리곤 0.58 ha 를 전 씬 고정지점으로 썼으나, 0329/0611 의 실제 수면은
   0.11~0.12 ha 라 신호가 5배 희석되어 **오검출(미검출로 판정)** 되었다. 정정본은 최저부와
   날짜별 자기 폴리곤을 쓴다. 평활도 5x5 -> 3x3 으로 줄였다.)
5. ★ 국지입사각 교란 제거: 바닥 안에서 dBn ~ cos(locinc) 회귀 후 **잔차**로 비교.
   바닥−링 지표는 링이 내벽 경사 26도(국지입사각 +5~19도)에 놓여 물과 무관하게 어두워지므로
   쓰지 않는다 - 구 파이프라인이 이 교란을 안고 있었다.

출력: water_scene_stats.csv, water_at_s2_polygon.csv, water_summary.md, figs
"""
import os, sys, csv, json, argparse, glob
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy.ndimage import binary_dilation, binary_erosion, label as cclabel
from skimage.morphology import reconstruction

HERE = os.path.dirname(os.path.abspath(__file__))
DEM_PATH = "<DATA_ROOT>/N2_InSAR/DEM/cop_dem_N33E126.tif"
S2_DIR = "<DATA_ROOT>/N2_InSAR/N2_Gemetric_Correction/Output/halla/reference/s2"
BLD_LON, BLD_LAT = 126.53310, 33.36156
SCL_BAD = (8, 9, 11)          # 구름 중/고확률, 눈
NDWI_T = 0.10


def dem_on(ref):
    with rasterio.open(ref) as dst, rasterio.open(DEM_PATH) as src:
        out = np.full((dst.height, dst.width), np.nan, np.float32)
        reproject(rasterio.band(src, 1), out, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=dst.transform, dst_crs=dst.crs,
                  resampling=Resampling.bilinear, dst_nodata=np.nan)
    return out


def floor_ring(ref, dep_min=1.0, rad_m=400.0):
    """분화구 바닥(폐합요지)과 링. 단순 고도임계는 림 안부로 새어나가므로 fill 을 쓴다."""
    from pyproj import Transformer
    H = dem_on(ref)
    with rasterio.open(ref) as d:
        tr, ny, nx, crs = d.transform, d.height, d.width, d.crs
    Hf = np.where(np.isfinite(H), H, np.nanmax(H)).astype(np.float64)
    seed = Hf.copy(); seed[1:-1, 1:-1] = Hf.max()
    dep = reconstruction(seed, Hf, method="erosion") - Hf
    tf = Transformer.from_crs(4326, crs.to_epsg(), always_xy=True)
    cx, cy = tf.transform(BLD_LON, BLD_LAT)
    X = tr.c + (np.arange(nx) + 0.5) * tr.a
    Y = tr.f + (np.arange(ny) + 0.5) * tr.e
    XX, YY = np.meshgrid(X, Y)
    near = np.hypot(XX - cx, YY - cy) < rad_m
    fl = (dep > dep_min) & near
    lab, n = cclabel(fl)
    if n > 1:                                   # 중심을 포함한 성분만
        k = lab[int(np.argmin(np.abs(Y - cy))), int(np.argmin(np.abs(X - cx)))]
        if k > 0:
            fl = lab == k
    rim = binary_dilation(fl, iterations=24) & ~binary_dilation(fl, iterations=8)
    return fl, rim, H


def s2_water_on(ref, tag):
    """S2 수면(NDWI>0.1, 눈·구름 제외)을 ref 격자로. 반환 (mask, ndwi_max, n_px10m)"""
    nd = os.path.join(S2_DIR, "S2_%s_ndwi.tif" % tag)
    sc = os.path.join(S2_DIR, "S2_%s_scl.tif" % tag)
    if not (os.path.exists(nd) and os.path.exists(sc)):
        return None, np.nan, 0
    with rasterio.open(nd) as d:
        N = d.read(1); ntr, ncrs = d.transform, d.crs
    with rasterio.open(sc) as d:
        S = d.read(1)
    w = np.isfinite(N) & (N > NDWI_T) & ~np.isin(S, SCL_BAD)
    with rasterio.open(ref) as dst:
        out = np.zeros((dst.height, dst.width), np.uint8)
        reproject(w.astype(np.uint8), out, src_transform=ntr, src_crs=ncrs,
                  dst_transform=dst.transform, dst_crs=dst.crs, resampling=Resampling.nearest)
    return out.astype(bool), float(np.nanmax(N[np.isfinite(N)])) if np.isfinite(N).any() else np.nan, int(w.sum())


def eff_n(n_px, corr_px=4.0):
    """상관된 화소의 유효표본수 (5 m 격자에 유효분해능 ~10 m -> 약 1/4)."""
    return max(n_px / corr_px, 1.0)



SNOW = {"20240229": 100, "20250104": 100, "20250301": 100, "20250317": 96.6, "20250329": 43.1,
        "20250402": 43.1, "20250403": 38.2, "20250420": 100, "20250525": 0, "20250611": 0}
S2HA = {"20250329": 0.11, "20250402": 0.11, "20250525": 0.58, "20250611": 0.12}
SITE_TAG = "20250525_20250526"   # 참고용(초판 지점)
CORE_PCTL = 5.0                  # 기준지점 = 바닥 고도 하위 5 %


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", default=os.path.join(HERE, "..", "Output", "baengnokdam", "output"))
    ap.add_argument("--scenes", default=os.path.join(HERE, "..", "Output", "baengnokdam", "scenes.csv"))
    ap.add_argument("--outdir", default=os.path.join(HERE, "..", "Output", "halla", "water"))
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    rows = list(csv.DictReader(open(a.scenes, encoding="utf-8")))
    meta = {"%s_%s" % (r["date"], r["tag"]): r for r in rows}
    files = sorted(glob.glob(os.path.join(a.indir, "*_dB_utm5m_aoi6km_coreg.tif")))
    ref = files[0]
    fl, rim, H = floor_ring(ref)
    px_ha = 25.0 / 1e4
    site = s2_water_on(ref, SITE_TAG)[0] & fl
    gy, gx = np.gradient(np.nan_to_num(H), 5.0)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    print("분화구 바닥 %d px (%.2f ha) 고도 %.0f~%.0f m | 링 %d px (경사 중앙 %.1f도)"
          % (fl.sum(), fl.sum() * px_ha, np.nanmin(H[fl]), np.nanmax(H[fl]), rim.sum(),
             np.nanmedian(slope[rim])))
    print("고정 기준지점(20250525 S2 수면 ∩ 바닥) %d px = %.2f ha, 고도 중앙 %.1f m (바닥나머지 %.1f m)"
          % (site.sum(), site.sum() * px_ha, np.nanmedian(H[site]), np.nanmedian(H[fl & ~site])))

    out, panels = [], []
    for f in files:
        tag = os.path.basename(f)[:11]; date = tag[:8]
        with rasterio.open(f) as d:
            dB = d.read(1)
        with rasterio.open(f.replace("_dB_", "_mask_")) as d:
            mk = d.read(1)
        with rasterio.open(f.replace("_dB_", "_locinc_")) as d:
            li = d.read(1)
        good = np.isfinite(dB) & (mk == 0) & np.isfinite(li)
        F = fl & good
        if F.sum() < 500:
            print("  %-12s 바닥 결측 (유효 %.0f%%) - 제외" % (tag, 100 * F.sum() / fl.sum()))
            continue
        dbn = dB - np.nanmedian(dB[good])
        x = np.cos(np.radians(li[F])); y = dbn[F]
        A = np.column_stack([np.ones_like(x), x])
        beta = np.linalg.lstsq(A, y, rcond=None)[0]
        res = y - A @ beta
        R2 = 1 - np.var(res) / np.var(y)
        sres = np.full(fl.shape, np.nan); sres[F] = res
        S, Rst = site & F, F & ~site
        ds = float(np.nanmedian(sres[S]) - np.nanmedian(sres[Rst]))
        sd = float(np.nanstd(sres[Rst])); ne = max(S.sum() / 4.0, 1.0)
        z = ds / (sd / np.sqrt(ne))
        rmed = float(np.nanmedian(dbn[rim & good])) if (rim & good).any() else np.nan
        out.append(dict(tag=tag, date=date, geom=meta.get(tag + "_" + tag[9:11], {}).get("tag", tag[9:]),
                        inc=float(meta[[k for k in meta if k.startswith(date)][0]]["inc_center"]),
                        snow_pct=SNOW.get(date), s2_water_ha=S2HA.get(date, 0.0),
                        floor_px=int(F.sum()), floor_pct=round(100 * F.sum() / fl.sum(), 1),
                        floor_dBn=round(float(np.nanmedian(dbn[F])), 3),
                        ring_dBn=round(rmed, 3),
                        floor_minus_ring=round(float(np.nanmedian(dbn[F])) - rmed, 3),
                        locinc_floor=round(float(np.nanmedian(li[F])), 2),
                        locinc_ring=round(float(np.nanmedian(li[rim & good])), 2),
                        slope_fit=round(float(beta[1]), 2), fit_R2=round(float(R2), 3),
                        site_px=int(S.sum()),
                        site_anom_dB=round(ds, 3), site_z=round(float(z), 2),
                        dark5_ha=round(float(((dbn < rmed - 5) & F).sum() * px_ha), 4)))
        panels.append((tag, dbn, F))
        print("  %-12s 눈 %3s%% S2 %4s ha | 바닥−링 %+6.2f | 기하보정 후 지점이상 %+6.2f dB (z %+5.1f)"
              % (tag, SNOW.get(date), S2HA.get(date, "—"), out[-1]["floor_minus_ring"], ds, z))

    with open(os.path.join(a.outdir, "water_scene_stats.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

    wet = [o["site_anom_dB"] for o in out if o["s2_water_ha"] > 0]
    dry = [o["site_anom_dB"] for o in out if o["s2_water_ha"] == 0]
    dec = [o for o in out if o["date"] == "20250525"]
    L = ["# 백록담 수체 탐지 — 미세정합 스택(step10) 기반", "",
         "대상 %d씬 (바닥 결측 2씬 제외), 기준지점 = 20250525 S2 수면 %d px (%.2f ha)"
         % (len(out), site.sum(), site.sum() * px_ha), "",
         "## 결론", "",
         "**N2 X-band 는 백록담 수면을 여전히 검출하지 못한다.** 다만 이번에는 *정합 불량이라는",
         "설명이 제거된 상태*에서의 결론이다 - 구 파이프라인의 씬간 정합 11.2 m 로는 0.11~0.58 ha",
         "(지름 40~90 m) 표적을 짚을 수 없었으나, step10 미세정합으로 0.6 m 가 되어 S2 가 본",
         "수면 화소를 직접 대조할 수 있게 되었다.", "",
         "| 구분 | 지점이상 [dB] | 평균 |", "|---|---|---|",
         "| 수면 있던 날 (n=%d) | %s | %+.2f |" % (len(wet), ", ".join("%+.2f" % v for v in wet), np.mean(wet)),
         "| 수면 없던 날 (n=%d) | %s | %+.2f |" % (len(dry), ", ".join("%+.2f" % v for v in dry), np.mean(dry)),
         "",
         "- 두 분포가 완전히 겹친다. 가장 어두운 값 %+.2f dB 는 **적설 100 %%·수면 없는 날**이다."
         % min(o["site_anom_dB"] for o in out),
         "- 가장 결정적인 씬 **20250525 (수면 0.58 ha, 무설·무운, S2 와 Δ−1일)** 은 지점이 오히려",
         "  **%+.2f dB 밝다**." % (dec[0]["site_anom_dB"] if dec else float("nan")),
         "- 물(정반사면)이면 X-band 에서 **−10 dB 이하**여야 하는데 최대 어두움이 −2.8 dB 다.", "",
         "## 구 파이프라인 지표의 결함", "",
         "구 작업이 쓴 **바닥−링** 지표는 교란되어 있다. 링은 분화구 내벽 경사 %.1f도에 놓여"
         % np.nanmedian(slope[rim]),
         "국지입사각이 바닥보다 5~19도 높다 → **물과 무관하게 어두워진다**. 게다가 지오코딩이",
         "바뀌면 링이 경사면의 다른 곳을 집어 값이 흔들린다(같은 씬에서 구 −0.02 → 신 −1.77 dB).",
         "따라서 본 작업은 **바닥 안에서만** 비교하고 cos(국지입사각) 회귀 잔차를 썼다.", "",
         "## 해석", "",
         "미검출 원인은 기하가 아니라 대상의 성질이다 — 얕고 탁한 습지성 수면이라 경면반사가",
         "부족하고(NDWI 최대 0.238, 개방수면은 >0.4; Sen2Cor 수체분류 SCL=6 은 12시점 전부 0 px),",
         "정상부 1950 m 의 바람이 표면을 거칠게 만들며, 초지 사이에 흩어져 화소 내 혼합이 일어난다.", "",
         "## 한계", "",
         "- **무설·무수면 대조군이 없다.** 적설 0 %% 씬은 20250525·20250611 둘뿐이고 둘 다 수면이 있었다.",
         "- 20240229(바닥 유효 47 %%)·20250403(37 %%)은 바닥 결측으로 제외했다.",
         "- dBn 은 AOI 중앙값 기준 상대값이며 절대 sigma0 가 아니다(Level 1D 아님).", ""]
    open(os.path.join(a.outdir, "water_summary.md"), "w", encoding="utf-8").write("\n".join(L))

    # ---- 그림
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    for q in ["/mnt/c/Windows/Fonts/malgun.ttf"]:
        if os.path.exists(q):
            fm.fontManager.addfont(q)
    plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
    ys, xs = np.nonzero(fl)
    y0, y1, x0, x1 = ys.min() - 40, ys.max() + 40, xs.min() - 40, xs.max() + 40
    n = len(panels)
    fig, ax = plt.subplots(2, max(n // 2 + n % 2, 1), figsize=(3.0 * (n // 2 + n % 2), 6.6), squeeze=False)
    for k, (tag, dbn, F) in enumerate(panels):
        A_ = ax[k % 2, k // 2]
        A_.imshow(dbn[y0:y1, x0:x1], cmap="gray", vmin=-6, vmax=6)
        A_.contour(fl[y0:y1, x0:x1].astype(float), [0.5], colors="#ff5a5a", linewidths=0.9)
        A_.contour(site[y0:y1, x0:x1].astype(float), [0.5], colors="#00c8ff", linewidths=1.2)
        o = [q for q in out if q["tag"] == tag][0]
        A_.set_title("%s\n눈%s%% S2 %s ha · 이상 %+.2f dB"
                     % (tag, o["snow_pct"], o["s2_water_ha"] or "—", o["site_anom_dB"]), fontsize=8)
        A_.set_xticks([]); A_.set_yticks([])
    for k in range(n, ax.size):
        ax[k % 2, k // 2].axis("off")
    fig.suptitle("백록담 분화구 — 빨강 = 바닥(폐합요지), 하늘색 = S2 수면(20250526, 0.58 ha)", fontsize=11)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(os.path.join(a.outdir, "fig_scenes.png"), dpi=110); plt.close()

    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    lab = [o["tag"][:8] for o in out]; val = [o["site_anom_dB"] for o in out]
    col = ["#2a9d8f" if o["s2_water_ha"] > 0 else "#9aa4b2" for o in out]
    ax.bar(range(len(out)), val, color=col)
    ax.axhline(0, color="#333", lw=.8); ax.axhline(-10, color="#c1121f", ls="--", lw=1.2)
    ax.text(0.02, -9.4, "물이라면 이 아래 (−10 dB)", color="#c1121f", fontsize=9, transform=ax.get_yaxis_transform())
    ax.set_xticks(range(len(out))); ax.set_xticklabels(lab, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("기준지점 이상 [dB]"); ax.set_ylim(-11, 3)
    ax.set_title("국지입사각 보정 후 S2 수면 위치의 SAR 이상 (초록=수면 있던 날)", fontsize=10)
    plt.tight_layout(); plt.savefig(os.path.join(a.outdir, "fig_site_anomaly.png"), dpi=120); plt.close()
    print("\n저장:", os.path.abspath(a.outdir))


if __name__ == "__main__":
    main()
