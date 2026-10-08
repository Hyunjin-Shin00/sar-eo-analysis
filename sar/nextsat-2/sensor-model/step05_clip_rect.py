"""Step 9b: 지오코딩 결과를 '스트립 정렬 직사각형' 으로 클립 — 광학 정사영상처럼 반듯한 마름모 산출물.

    python step05_clip_rect.py [h5 경로] [--res 10] [--buffer 50]

원리
  유효영역 외곽은 지형 높이 h/tan(inc) 만큼 원거리 쪽으로 휘어 있다. 그 안에 완전히 들어가는
  가장 큰 스트립 정렬 직사각형을 구해 그 밖을 nodata 로 지운다.
    * 근거리 경계: h=0 경계 + (유효영역 경계의 최대 이동량) + buffer
    * 원거리 경계: h=0 경계 + (최소 이동량) − buffer   (보통 h=0 경계 안쪽)
    * 방위(early/late) 경계: 높이와 무관하게 직선 -> buffer 만
  결과 래스터는 직사각형 경계상자로 잘라 저장한다.

출력  ../Output/geo/<date>_<tag>_*_utm<res>m_clip.tif,  <date>_<tag>_cliprect.geojson
"""
import sys, os, json
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from pyproj import Transformer
from n2reader import N2Scene
from orbit import Orbit
from geometry import RangeDoppler, ecef_to_geodetic

DEFAULT = ("<DATA_ROOT>/N2_InSAR/N2/LV1A/HALA/"
           "N2_SAR_20250611_063619_ST_BB_VV_A_R_SSC_B_NP01.h5")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Output", "geo")
EPSG_OUT = 32652


def main(path, res=10.0, buffer=50.0):
    sc = N2Scene(path)
    ob = Orbit(sc.sv_t, sc.sv_pos, sc.sv_vel, t_ref=sc.t_mid, deg=4)
    rd = RangeDoppler(sc, ob)
    date = os.path.basename(path)[7:15]; tag = f"{sc.orbit_dir[0]}{sc.look_side[0]}"
    base = os.path.join(OUT, f"{date}_{tag}")
    to_utm = Transformer.from_crs(4326, EPSG_OUT, always_xy=True)

    # ---- h=0 풋프린트를 스트립 좌표계(u=방위, v=거리)로
    L = sc.n_avail - 1.0; C = sc.ncols - 1.0
    def utm(l, s):
        lat, lon, _ = ecef_to_geodetic(rd.rdr2geo(l, s, 0.0)); return np.array(to_utm.transform(lon, lat))
    A, B, Cc, D = utm(0, 0), utm(0, C), utm(L, C), utm(L, 0)      # early-near, early-far, late-far, late-near
    u_hat = (D - A) / np.linalg.norm(D - A)                        # 방위 방향 (early -> late)
    v_hat = (B - A) / np.linalg.norm(B - A)                        # 거리 방향 (near -> far)
    def to_uv(E, N):
        d = np.stack([E - A[0], N - A[1]], -1); return d @ u_hat, d @ v_hat
    u_len = np.linalg.norm(D - A); v_len = np.linalg.norm(B - A)

    # ---- 유효영역(마스크) 의 u,v 범위
    with rasterio.open(f"{base}_mask_utm{res:.0f}m.tif") as d:
        m = d.read(1); T = d.transform; prof = d.profile
    rows, cols = np.where(m != 255)
    E = T.c + (cols + 0.5) * T.a; N = T.f + (rows + 0.5) * T.e
    u, v = to_uv(E, N)
    # 방위 bin 별로 유효 v 의 최소/최대 -> 전체에 공통으로 들어가는 v 구간
    nb = 200
    ub = np.clip((u / u_len * nb).astype(int), 0, nb - 1)
    vmin_b = np.full(nb, np.nan); vmax_b = np.full(nb, np.nan)
    for b in range(nb):
        sel = ub == b
        if sel.sum() > 10:
            vmin_b[b] = v[sel].min(); vmax_b[b] = v[sel].max()
    v_lo = np.nanmax(vmin_b) + buffer          # 가장 많이 밀린 근거리 경계
    v_hi = np.nanmin(vmax_b) - buffer          # 가장 덜 나온 원거리 경계
    u_lo = 0.0 + buffer; u_hi = u_len - buffer
    print(f"  h=0 직사각형        : 방위 {u_len/1e3:.2f} km x 거리 {v_len/1e3:.2f} km")
    print(f"  유효영역 근거리 경계 이동: 최소 {np.nanmin(vmin_b):+.0f} m  최대 {np.nanmax(vmin_b):+.0f} m   (지형 h/tan(inc))")
    print(f"  유효영역 원거리 경계 이동: 최소 {np.nanmin(vmax_b)-v_len:+.0f} m  최대 {np.nanmax(vmax_b)-v_len:+.0f} m")
    print(f"  내접 직사각형       : 방위 {(u_hi-u_lo)/1e3:.2f} km x 거리 {(v_hi-v_lo)/1e3:.2f} km   (폭 손실 {(v_len-(v_hi-v_lo))/1e3:.2f} km, 근거리 쪽)")

    # ---- 폴리곤 (UTM) 과 마스크
    corners_uv = [(u_lo, v_lo), (u_lo, v_hi), (u_hi, v_hi), (u_hi, v_lo), (u_lo, v_lo)]
    poly = [tuple(A + uu * u_hat + vv * v_hat) for uu, vv in corners_uv]
    gj_poly = {"type": "Polygon", "coordinates": [[list(map(float, p)) for p in poly]]}
    with rasterio.open(f"{base}_mask_utm{res:.0f}m.tif") as d:
        inside = ~geometry_mask([gj_poly], out_shape=m.shape, transform=T, invert=False)
    # 경계상자로 잘라내기
    Es = [p[0] for p in poly]; Ns = [p[1] for p in poly]
    win = from_bounds(min(Es), min(Ns), max(Es), max(Ns), T).round_offsets().round_lengths()
    r0, r1 = int(win.row_off), int(win.row_off + win.height); c0, c1 = int(win.col_off), int(win.col_off + win.width)
    T2 = rasterio.windows.transform(win, T)

    lost = ((m != 255) & ~inside).sum() / (m != 255).sum() * 100
    print(f"  클립으로 버려지는 유효 화소: {lost:.1f} %")

    for kind, dtype, nd in (("dB", "float32", np.nan), ("locinc", "float32", np.nan), ("mask", "uint8", 255)):
        with rasterio.open(f"{base}_{kind}_utm{res:.0f}m.tif") as d:
            arr = d.read(1)
        arr = np.where(inside, arr, nd).astype(dtype)[r0:r1, c0:c1]
        p2 = prof.copy(); p2.update(height=r1 - r0, width=c1 - c0, transform=T2, dtype=dtype, nodata=nd)
        with rasterio.open(f"{base}_{kind}_utm{res:.0f}m_clip.tif", "w", **p2) as d:
            d.write(arr, 1)
    lat_c, lon_c = [], []
    to_geo = Transformer.from_crs(EPSG_OUT, 4326, always_xy=True)
    ring = [list(map(float, to_geo.transform(p[0], p[1]))) for p in poly]
    with open(f"{base}_cliprect.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [{"type": "Feature",
                   "properties": {"scene": date, "u_km": (u_hi - u_lo) / 1e3, "v_km": (v_hi - v_lo) / 1e3},
                   "geometry": {"type": "Polygon", "coordinates": [ring]}}]}, f, indent=1)
    print(f"  -> {os.path.normpath(base)}_{{dB,locinc,mask}}_utm{res:.0f}m_clip.tif,  _cliprect.geojson")

    # 미리보기
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from matplotlib import font_manager
        fp = "/mnt/c/Windows/Fonts/malgun.ttf"
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp); plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        with rasterio.open(f"{base}_dB_utm{res:.0f}m_clip.tif") as d:
            dB = d.read(1); b = d.bounds
        v = np.nanpercentile(dB, (2, 98))
        fig, ax = plt.subplots(figsize=(7, 7 * dB.shape[0] / dB.shape[1]))
        ax.imshow(np.nan_to_num(dB, nan=v[0] - 5), cmap="gray", vmin=v[0], vmax=v[1], extent=[b.left, b.right, b.bottom, b.top])
        ax.plot(Es, Ns, "r-", lw=1); ax.set_title(f"{date} {tag} 스트립 정렬 직사각형 클립 ({(u_hi-u_lo)/1e3:.1f} x {(v_hi-v_lo)/1e3:.1f} km)")
        fn = f"{base}_preview_clip.png"; plt.tight_layout(); plt.savefig(fn, dpi=110); plt.close()
        print(f"  미리보기: {os.path.normpath(fn)}")
    except Exception as e:
        print("  [미리보기 생략]", e)


if __name__ == "__main__":
    a = sys.argv[1:]
    res = float(a[a.index("--res") + 1]) if "--res" in a else 10.0
    buf = float(a[a.index("--buffer") + 1]) if "--buffer" in a else 50.0
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or not a[i - 1].startswith("--"))]
    main(pos[0] if pos else DEFAULT, res=res, buffer=buf)
