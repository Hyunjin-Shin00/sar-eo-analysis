"""Step 9 실행: 역방향(backward) 지오코딩 → GeoTIFF (UTM 52N).

    python step04_geocode.py [h5 경로] [--res 5] [--center 126.5292 33.3617 --size 6] [--bias step07|step03|none] [--nobias]

    --res     출력 격자 [m]. 멀티룩 크기는 이 값에 맞춰 씬별 자동 결정 (방위 res/1.11 라인, 거리 res·sin(inc)/dR 샘플)
    --center  AOI 중심 (lon lat) 과 --size (km): 북향 정사각형 타일. 생략하면 보유구간 전체 경계상자
    --bias    편향 소스. step07(창 LS, 기본) → 없으면 step03 → 없으면 0

원리
  지도 격자의 화소마다: (E,N) -> (lat,lon) -> DEM 타원체고 -> ECEF -> geo2rdr -> (line, sample)
  -> 멀티룩 강도 영상에서 bilinear 로 값을 가져온다.  영상을 지도로 '밀어 넣는' 것이 아니라
  지도에서 영상을 '당겨 오는' 방식이라 구멍이 없고 리샘플링이 한 번뿐이다.
  편향(Step 7 json) 과 대류권 모델을 켠 엄밀모델을 그대로 쓴다.

출력 (../Output/geo/)
  <date>_dB_utm<res>m.tif        상대 후방산란 [dB] (보정상수 없음 -> 씬 간 절대 비교 불가)
  <date>_locinc_utm<res>m.tif    국지입사각 [deg]
  <date>_mask_utm<res>m.tif      0 정상 / 1 레이오버 / 2 등돌린면(그림자 후보) / 255 자료없음
  같은 이름 + _nobias.tif        편향 미적용 (QGIS 에서 토글해 32 m 차이 확인용)
"""
import sys, os, json
import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer
from scipy.ndimage import map_coordinates
from n2reader import N2Scene
from orbit import Orbit
from geometry import RangeDoppler, geodetic_to_ecef, ecef_to_geodetic, _unit
from dem import DEM

DEFAULT = ("/mnt/c/N2_InSAR/N2/LV1A/HALA/"
           "N2_SAR_20250611_063619_ST_BB_VV_A_R_SSC_B_NP01.h5")
DEM_PATH = "/mnt/c/N2_InSAR/DEM/cop_dem_N33E126.tif"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Output")
EPSG_OUT = 32652
ML_BL, ML_BS = 9, 5          # step03 이 만든 fine 멀티룩 캐시 (10 m x 9 m)


def load_bias(date, source="step07"):
    """편향 (dt_bias_s, dr_bias_m, 출처). step07(창 LS) → step03(피크1개) 순으로 탐색."""
    cands = {"step07": f"step07_lsq_{date}_27x16.json", "step03": f"step03_bias_{date}.json"}
    order = ["step07", "step03"] if source == "step07" else ([source] if source in cands else [])
    for k in order:
        fn = os.path.join(OUT, cands[k])
        if os.path.exists(fn):
            j = json.load(open(fn, encoding="utf-8"))
            return float(j["dt_bias_s"]), float(j["dr_bias_m"]), k
    print(f"  [경고] {date} 편향 파일 없음 -> 0"); return 0.0, 0.0, "none"


def output_grid(rd, sc, res):
    """보유 구간 풋프린트(h=0) 의 UTM 경계상자 -> 격자 (res 배수로 스냅)"""
    ls = np.array([0, 0, sc.n_avail - 1, sc.n_avail - 1], float)
    cs = np.array([0, sc.ncols - 1, sc.ncols - 1, 0], float)
    lat, lon, _ = ecef_to_geodetic(rd.rdr2geo(ls, cs, 0.0))
    to_utm = Transformer.from_crs(4326, EPSG_OUT, always_xy=True)
    E, N = to_utm.transform(lon, lat)
    e0 = np.floor(E.min() / res) * res; e1 = np.ceil(E.max() / res) * res
    n0 = np.floor(N.min() / res) * res; n1 = np.ceil(N.max() / res) * res
    ncol = int((e1 - e0) / res); nrow = int((n1 - n0) / res)
    return e0, n1, ncol, nrow


def main(path, res=10.0, with_nobias=True, center=None, size_km=None, bias_src="step07", outdir=None, quiet=False):
    global ML_BL, ML_BS
    sc = N2Scene(path)
    ob = Orbit(sc.sv_t, sc.sv_pos, sc.sv_vel, t_ref=sc.t_mid, deg=4)
    date = os.path.basename(path)[7:15]
    tag = f"{sc.orbit_dir[0]}{sc.look_side[0]}"
    dt_b, dr_b, bsrc = load_bias(date, bias_src)
    print(f"  씬 {date} {tag}   편향[{bsrc}] Δt_az={dt_b*1e3:+.4f} ms  ΔR={dr_b:+.3f} m   출력 {res:g} m")

    # ---------------- 격자
    rd = RangeDoppler(sc, ob, dt_bias=dt_b, dr_bias=dr_b, tropo=True)
    # 씬 중심 입사각 -> 출력 해상도에 맞는 멀티룩 (방위 라인수, 거리 샘플수)
    lc, cc0 = sc.n_avail // 2, sc.ncols // 2
    inc_c = float(rd.incidence_deg(rd.rdr2geo(lc, cc0, 0.0), rd.t_of_line(lc)))
    az_m = float(np.linalg.norm(rd.rdr2geo(lc + 1, cc0, 0.0) - rd.rdr2geo(lc, cc0, 0.0)))
    ML_BL = max(1, int(round(res / az_m))); ML_BS = max(1, int(round(res * np.sin(np.radians(inc_c)) / sc.dr)))
    print(f"  입사각 {inc_c:.1f}°  방위 {az_m:.2f} m/line, 거리 {sc.dr/np.sin(np.radians(inc_c)):.2f} m/sample  -> 멀티룩 {ML_BL} x {ML_BS}"
          f" = {ML_BL*az_m:.1f} x {ML_BS*sc.dr/np.sin(np.radians(inc_c)):.1f} m")
    aoi = ""
    if center is not None and size_km:
        to_utm = Transformer.from_crs(4326, EPSG_OUT, always_xy=True)
        ec, nc_ = to_utm.transform(center[0], center[1]); half = size_km * 500.0
        e0 = np.floor((ec - half) / res) * res; n1 = np.ceil((nc_ + half) / res) * res
        ncol = nrow = int(round(size_km * 1000.0 / res)); aoi = f"_aoi{size_km:g}km"
    else:
        e0, n1, ncol, nrow = output_grid(rd, sc, res)
    transform = from_origin(e0, n1, res, res)
    E = e0 + (np.arange(ncol) + 0.5) * res
    N = n1 - (np.arange(nrow) + 0.5) * res
    EE, NN = np.meshgrid(E, N)
    print(f"  격자 {nrow} x {ncol}  ({nrow*res/1000:.1f} x {ncol*res/1000:.1f} km)   좌상단 E {e0:.0f} N {n1:.0f}")

    # ---------------- DEM
    to_geo = Transformer.from_crs(EPSG_OUT, 4326, always_xy=True)
    lon, lat = to_geo.transform(EE.ravel(), NN.ravel())
    lon = lon.reshape(EE.shape); lat = lat.reshape(EE.shape)
    dem = DEM(DEM_PATH)
    dem.prepare_geoid(lat.min(), lat.max(), lon.min(), lon.max())
    h_o = dem.height_ortho(lat, lon)
    h = h_o + dem.geoid_N(lat, lon)
    # 국지 법선 (UTM 격자는 미터 단위라 gradient 가 바로 기울기)
    dz_dn, dz_de = np.gradient(h_o, -res, res)        # 행은 북->남 이므로 -res
    n_enu = np.stack([-dz_de, -dz_dn, np.ones_like(h_o)], -1)
    n_enu /= np.linalg.norm(n_enu, axis=-1, keepdims=True)
    la, lo = np.radians(lat), np.radians(lon)
    e_ = np.stack([-np.sin(lo), np.cos(lo), np.zeros_like(lo)], -1)
    n_ = np.stack([-np.sin(la) * np.cos(lo), -np.sin(la) * np.sin(lo), np.cos(la)], -1)
    u_ = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)
    n_ecef = n_enu[..., 0:1] * e_ + n_enu[..., 1:2] * n_ + n_enu[..., 2:3] * u_

    # ---------------- 멀티룩 강도 (캐시)
    fn_ml = os.path.join(OUT, f"ml_{date}_{ML_BL}x{ML_BS}.npy")
    if not os.path.exists(fn_ml):
        from simulate import multilook_intensity
        np.save(fn_ml, multilook_intensity(sc, ML_BL, ML_BS))
    I_ml = np.load(fn_ml)

    P = geodetic_to_ecef(lat, lon, h)

    def geocode(rd_, suffix):
        t, R, line, samp = rd_.geo2rdr(P)
        valid = (line >= 0) & (line <= sc.n_avail - 1) & (samp >= 0) & (samp <= sc.ncols - 1) & np.isfinite(h)
        # 멀티룩 격자 좌표 (bin 중심 기준)
        rl = line / ML_BL - 0.5; rs = samp / ML_BS - 0.5
        I = map_coordinates(I_ml, [rl, rs], order=1, mode="nearest")
        dB = np.where(valid & (I > 0), 10 * np.log10(np.where(I > 0, I, 1)), np.nan).astype(np.float32)
        # 국지입사각
        S = rd_.orb.position(t); los = _unit(S - P)
        cos_loc = np.sum(n_ecef * los, axis=-1)
        locinc = np.degrees(np.arccos(np.clip(cos_loc, -1, 1))).astype(np.float32)
        # 레이오버: 지상 거리방향으로 갈 때 sample 이 줄어드는 곳 (거리 순서 역전)
        # 거리방향 지도벡터: 같은 line 에서 sample 증가 방향
        Pn = rd_.rdr2geo(sc.n_avail // 2, 1000.0, 0.0); Pf = rd_.rdr2geo(sc.n_avail // 2, 4000.0, 0.0)
        lat_n, lon_n, _ = ecef_to_geodetic(Pn); lat_f, lon_f, _ = ecef_to_geodetic(Pf)
        to_utm = Transformer.from_crs(4326, EPSG_OUT, always_xy=True)
        en, nn = to_utm.transform(lon_n, lat_n); ef, nf = to_utm.transform(lon_f, lat_f)
        dvec = np.array([ef - en, nf - nn]); dvec /= np.linalg.norm(dvec)
        ds_dn, ds_de = np.gradient(samp, -res, res)
        dsamp_dground = ds_de * dvec[0] + ds_dn * dvec[1]
        mask = np.full(h.shape, 255, np.uint8)
        mask[valid] = 0
        mask[valid & (dsamp_dground < 0)] = 1
        mask[valid & (cos_loc <= 0)] = 2
        locinc[~valid] = np.nan

        odir = outdir or os.path.join(OUT, "geo")
        os.makedirs(odir, exist_ok=True)
        base = os.path.join(odir, f"{date}_{tag}")
        rs = f"utm{res:g}m{aoi}{suffix}"
        prof = dict(driver="GTiff", height=nrow, width=ncol, count=1, crs=f"EPSG:{EPSG_OUT}",
                    transform=transform, compress="deflate", tiled=True)
        with rasterio.open(f"{base}_dB_{rs}.tif", "w", dtype="float32", nodata=np.nan, **prof) as d:
            d.write(dB, 1); d.update_tags(scene=date, dt_bias_ms=f"{rd_.dt_bias*1e3:.4f}", dr_bias_m=f"{rd_.dr_bias:.3f}",
                                          bias_source=bsrc, multilook=f"{ML_BL}x{ML_BS}", inc_center_deg=f"{inc_c:.2f}",
                                          tropo="standard-atmosphere", note="relative dB, no calibration constant")
        with rasterio.open(f"{base}_locinc_{rs}.tif", "w", dtype="float32", nodata=np.nan, **prof) as d:
            d.write(locinc, 1)
        with rasterio.open(f"{base}_mask_{rs}.tif", "w", dtype="uint8", nodata=255, **prof) as d:
            d.write(mask, 1)
        nv = valid.sum()
        if nv == 0:
            print(f"  [{suffix or 'bias'}] 유효 화소 없음 (AOI 가 보유구간 밖)"); return dB, mask
        print(f"  [{suffix or 'bias'}] 유효 {nv} px ({nv/valid.size*100:.1f} %)   레이오버 {(mask==1).sum()/nv*100:.2f} %"
              f"   등돌린면 {(mask==2).sum()/nv*100:.2f} %   국지입사각 중앙 {np.nanmedian(locinc[valid]):.1f}°")
        print(f"       -> {os.path.normpath(base)}_{{dB,locinc,mask}}_{rs}.tif")
        return dB, mask

    dB, mask = geocode(rd, "")
    if with_nobias:
        geocode(RangeDoppler(sc, ob, 0.0, 0.0, tropo=False), "_nobias")
    summary = dict(date=date, tag=tag, inc_center=inc_c, ml=f"{ML_BL}x{ML_BS}", bias_src=bsrc, dt_bias_ms=dt_b * 1e3, dr_bias_m=dr_b,
                   valid_pct=float((mask != 255).mean() * 100), layover_pct=float((mask == 1).mean() * 100),
                   file=f"{date}_{tag}_dB_utm{res:g}m{aoi}.tif")

    # 백록담 화소 확인
    to_utm = Transformer.from_crs(4326, EPSG_OUT, always_xy=True)
    eb, nb = to_utm.transform(126.5292, 33.3617)
    c = int((eb - e0) / res); r = int((n1 - nb) / res)
    if 0 <= r < nrow and 0 <= c < ncol:
        print(f"  백록담 (E {eb:.0f}, N {nb:.0f}) -> 격자 [{r},{c}]  dB={dB[r,c]:.1f}  mask={mask[r,c]}")

    # 미리보기 PNG
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from matplotlib import font_manager
        fp = "/mnt/c/Windows/Fonts/malgun.ttf"
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp); plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        v = np.nanpercentile(dB, (2, 98))
        fig, ax = plt.subplots(figsize=(8, 8 * nrow / ncol))
        ax.imshow(dB, cmap="gray", vmin=v[0], vmax=v[1], extent=[e0, e0 + ncol * res, n1 - nrow * res, n1])
        ax.plot(eb, nb, "r+", ms=14, mew=2); ax.set_title(f"{date} {tag} 지오코딩 dB (UTM 52N, {res:g} m, 멀티룩 {ML_BL}x{ML_BS})  +: 백록담")
        ax.set_xlabel("E [m]"); ax.set_ylabel("N [m]")
        fn = os.path.join(outdir or os.path.join(OUT, "geo"), f"{date}_{tag}_preview_utm{res:g}m{aoi}.png"); plt.tight_layout(); plt.savefig(fn, dpi=110); plt.close()
        print(f"  미리보기: {os.path.normpath(fn)}")
    except Exception as e:
        print("  [미리보기 생략]", e)
    return summary


if __name__ == "__main__":
    a = sys.argv[1:]
    def opt(name, n=1, cast=float):
        if name in a:
            i = a.index(name); return [cast(x) for x in a[i + 1:i + 1 + n]] if n > 1 else cast(a[i + 1])
        return None
    res = opt("--res") or 10.0
    center = opt("--center", 2); size = opt("--size")
    bias_src = opt("--bias", cast=str) or "step07"
    consumed = set()
    for name, n in (("--res", 1), ("--center", 2), ("--size", 1), ("--bias", 1)):
        if name in a:
            i = a.index(name); consumed.update(range(i, i + 1 + n))
    pos = [x for i, x in enumerate(a) if i not in consumed and not x.startswith("--")]
    main(pos[0] if pos else DEFAULT, res=res, with_nobias="--nobias" not in a, center=center, size_km=size, bias_src=bias_src)
