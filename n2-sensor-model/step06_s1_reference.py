"""Step 10 보조: 같은 위치의 Sentinel-1 RTC(지형보정 γ0) 를 받아 N2 격자에 올리고, 위치 잔차를 교차검증한다.

    python step06_s1_reference.py [--date 20250611] [--pass ascending|descending|any] [--days 30]

자료: Microsoft Planetary Computer `sentinel-1-rtc` (무료, 익명 SAS 토큰). 10 m, UTM, DEM 지형보정 완료.
출력  ../Output/geo/S1_<date>_<ASC/DES>_<pol>_utm10m.tif   (N2 지오코딩과 동일 격자, dB)
      ../Output/geo/compare_N2_S1_<n2date>.png
      콘솔: N2 vs S1 2D 정합 잔차 (동서/남북 m)  ← 독립 기준영상 기반 절대위치 교차검증
"""
import sys, os, json, datetime as dt
import numpy as np, requests, rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from pyproj import Transformer
from scipy.ndimage import gaussian_filter, zoom

PC = "https://planetarycomputer.microsoft.com/api/stac/v1"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Output", "geo")
EPSG_OUT = 32652
N2_DATE = "20250611"; N2_TAG = "AR"


def sas(href):
    from urllib.parse import urlparse
    u = urlparse(href); account = u.netloc.split(".")[0]; container = u.path.split("/")[1]
    tok = requests.get(f"https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}/{container}", timeout=30).json()["token"]
    return href + "?" + tok


def search(bbox, center, days, orbit):
    t0 = (center - dt.timedelta(days=days)).strftime("%Y-%m-%d"); t1 = (center + dt.timedelta(days=days)).strftime("%Y-%m-%d")
    q = {"collections": ["sentinel-1-rtc"], "bbox": bbox, "datetime": f"{t0}/{t1}", "limit": 100}
    items = requests.post(f"{PC}/search", json=q, timeout=60).json().get("features", [])
    rows = []
    for it in items:
        p = it["properties"]; pol = "vv" if "vv" in it["assets"] else ("hh" if "hh" in it["assets"] else None)
        if pol is None: continue
        if orbit != "any" and p.get("sat:orbit_state") != orbit: continue
        d = dt.datetime.fromisoformat(p["datetime"].replace("Z", "+00:00")).replace(tzinfo=None)
        rows.append(dict(id=it["id"], date=d, dd=abs((d - center).days), orbit=p.get("sat:orbit_state"),
                         pol=pol, href=it["assets"][pol]["href"], platform=p.get("platform"),
                         rel=p.get("sat:relative_orbit")))
    return sorted(rows, key=lambda r: r["dd"])


def main(n2_date=N2_DATE, orbit="ascending", days=30, s1date=None, n2suffix=""):
    # N2 격자 (step04 출력에서 그대로). n2suffix="_nobias" 면 편향 미적용본과 비교
    n2_db_path = os.path.join(OUT, f"{n2_date}_{N2_TAG}_dB_utm10m{n2suffix}.tif")
    if n2suffix:
        print(f"  [N2 입력: {os.path.basename(n2_db_path)}]")
    with rasterio.open(n2_db_path) as d:
        n2 = d.read(1); T = d.transform; H, W = n2.shape; prof = d.profile
    to_geo = Transformer.from_crs(EPSG_OUT, 4326, always_xy=True)
    lon0, lat0 = to_geo.transform(T.c, T.f + H * T.e); lon1, lat1 = to_geo.transform(T.c + W * T.a, T.f)
    bbox = [lon0, lat0, lon1, lat1]
    center = dt.datetime.strptime(n2_date, "%Y%m%d")

    print("=" * 70); print(f"Sentinel-1 RTC 검색  bbox {np.round(bbox,3)}  {n2_date} ±{days}일  궤도 {orbit}"); print("=" * 70)
    rows = search(bbox, center, days, orbit)
    if s1date:
        rows = [r for r in rows if r["date"].strftime("%Y%m%d") == s1date]
        rows = [r for r in rows if r["pol"] == "vv"] or rows        # 같은 날 VV 우선
    if not rows:
        print("  후보 없음"); return
    for r in rows[:8]:
        print(f"  {r['date']:%Y-%m-%d %H:%M}  Δ{r['dd']:3d}일  {r['orbit']:10}  {r['pol'].upper()}  {r['platform']}  rel.orbit {r['rel']}")
    pick = rows[0]
    print(f"  -> 선택: {pick['id']}")

    # 다운로드 + N2 격자로 리샘플
    dst = np.full((H, W), np.nan, np.float32)
    with rasterio.open(sas(pick["href"])) as src:
        print(f"  원본: {src.crs}  {src.width}x{src.height}  res {src.res}")
        reproject(rasterio.band(src, 1), dst, dst_transform=T, dst_crs=f"EPSG:{EPSG_OUT}",
                  resampling=Resampling.bilinear, src_nodata=src.nodata, dst_nodata=np.nan)
    dst[dst <= 0] = np.nan
    s1_db = (10 * np.log10(dst)).astype(np.float32)
    tag = "ASC" if pick["orbit"] == "ascending" else "DES"
    fn = os.path.join(OUT, f"S1_{pick['date']:%Y%m%d}_{tag}_{pick['pol'].upper()}_utm10m.tif")
    p2 = prof.copy(); p2.update(dtype="float32", nodata=np.nan)
    with rasterio.open(fn, "w", **p2) as d:
        d.write(s1_db, 1); d.update_tags(source=pick["id"], product="Sentinel-1 RTC gamma0 dB (Planetary Computer)")
    print(f"  저장: {os.path.normpath(fn)}   유효 {np.isfinite(s1_db).mean()*100:.1f} %")

    # ---- 교차검증: N2 vs S1 2D 정합 (30 m 로 낮춰 스펙클 억제)
    print(); print("=" * 70); print("N2 지오코딩 vs S1 RTC 위치 잔차 (독립 교차검증)"); print("=" * 70)
    k = 3
    def down(a):
        Hh, Ww = a.shape[0] // k * k, a.shape[1] // k * k
        return np.nanmean(a[:Hh, :Ww].reshape(Hh // k, k, Ww // k, k), axis=(1, 3))
    A = down(n2); B = down(s1_db)
    m = np.isfinite(A) & np.isfinite(B)
    # 바다 제외: S1 γ0 < -18 dB 영역 (잔잔한 바다) 을 뺌
    m &= B > -18
    sig = 4.0
    def hp(x):
        x = np.where(m, x, np.nanmean(x[m])); return x - gaussian_filter(x, sig)
    a, b = hp(A), hp(B)
    S = 12
    cc = np.full((2 * S + 1, 2 * S + 1), np.nan)
    Hh, Ww = a.shape
    for i, di in enumerate(range(-S, S + 1)):
        for j, dj in enumerate(range(-S, S + 1)):
            r0, r1 = max(0, di), min(Hh, Hh + di); c0, c1 = max(0, dj), min(Ww, Ww + dj)
            X = a[r0:r1, c0:c1]; Y = b[r0 - di:r1 - di, c0 - dj:c1 - dj]
            M = m[r0:r1, c0:c1] & m[r0 - di:r1 - di, c0 - dj:c1 - dj]
            x = X[M] - X[M].mean(); y = Y[M] - Y[M].mean()
            cc[i, j] = (x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum())
    i, j = np.unravel_index(np.nanargmax(cc), cc.shape)
    from simulate import _peak2d
    di, dj = _peak2d(cc, i, j, 2)
    drow = (i - S) + di; dcol = (j - S) + dj          # N2(r,c) ≈ S1(r-drow, c-dcol): N2 가 S1 보다 (drow, dcol) 만큼 아래/오른쪽
    dE = dcol * k * 10.0; dN = -drow * k * 10.0
    print(f"  상관 피크 r = {cc[i,j]:.3f}   (유효 30 m 셀 {m.sum()})")
    print(f"  N2 가 S1 대비 : 동쪽 {dE:+.1f} m,  북쪽 {dN:+.1f} m   (S1 RTC 자체 정확도 ~10 m 이내이므로 |값| < 10~20 m 면 일치)")
    json.dump(dict(n2=n2_date, s1=pick["id"], r=float(cc[i, j]), dE_m=float(dE), dN_m=float(dN)),
              open(os.path.join(OUT, f"compare_N2_S1_{n2_date}_{pick['date']:%Y%m%d}{tag}.json"), "w"), indent=1)

    # ---- 그림
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from matplotlib import font_manager
        fp = "/mnt/c/Windows/Fonts/malgun.ttf"
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp); plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        ext = [T.c, T.c + W * T.a, T.f + H * T.e, T.f]
        fig, ax = plt.subplots(1, 2, figsize=(12, 10))
        v = np.nanpercentile(n2, (2, 98)); ax[0].imshow(n2, cmap="gray", vmin=v[0], vmax=v[1], extent=ext); ax[0].set_title(f"NEXTSat-2 {n2_date} {N2_TAG}  X-band ~3 m→10 m")
        v = np.nanpercentile(s1_db, (2, 98)); ax[1].imshow(s1_db, cmap="gray", vmin=v[0], vmax=v[1], extent=ext); ax[1].set_title(f"Sentinel-1 {pick['date']:%Y-%m-%d} {tag} {pick['pol'].upper()}  C-band 10 m RTC")
        for a_ in ax: a_.plot(270106, 3694113, "r+", ms=12, mew=2); a_.set_xlabel("E [m]")
        fig.suptitle(f"동일 격자 (UTM 52N 10 m).  N2−S1 위치 잔차: 동 {dE:+.0f} m / 북 {dN:+.0f} m  (r={cc[i,j]:.2f})", fontsize=12)
        plt.tight_layout(); fn = os.path.join(OUT, f"compare_N2_S1_{n2_date}_{pick['date']:%Y%m%d}{tag}.png"); plt.savefig(fn, dpi=100); plt.close()
        print(f"  그림: {os.path.normpath(fn)}")
    except Exception as e:
        print("  [그림 생략]", e)


if __name__ == "__main__":
    a = sys.argv[1:]
    d = a[a.index("--date") + 1] if "--date" in a else N2_DATE
    o = a[a.index("--pass") + 1] if "--pass" in a else "ascending"
    n = int(a[a.index("--days") + 1]) if "--days" in a else 30
    s = a[a.index("--s1date") + 1] if "--s1date" in a else None
    sfx = a[a.index("--n2suffix") + 1] if "--n2suffix" in a else ""
    main(d, o, n, s, sfx)
