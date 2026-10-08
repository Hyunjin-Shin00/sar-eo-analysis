"""Step 7 실행: 대류권 보정 + DEM 지형 시뮬레이션 정합으로 편향(Δt_az, ΔR) 추정.

    python step03_bias_dem.py [h5 경로]

절차
  0. 대류권 지연 모델 켜기 (tropo=True)  — 해면/정상부 지연값 출력
  1. 실영상 멀티룩 (coarse 27x16, fine 9x5) — 캐시 ../Output/ml_<date>_<bl>x<bs>.npy
  2. DEM 블록(footprint) -> 시뮬레이션 -> 정합 -> 오프셋 -> 편향 반영
  3. 반복: 편향 반영 후 재시뮬 -> 잔차 확인. coarse 2회 -> fine 2회
  4. 4분면 검사: 편향이 위치와 무관한 상수인지
출력  ../Output/step03_bias_<date>.json, step03_match_<date>.png
"""
import sys, os, json, time
import numpy as np
from n2reader import N2Scene
from orbit import Orbit
from geometry import RangeDoppler, ecef_to_geodetic
from dem import DEM
from simulate import simulate, multilook_intensity, match
from tropo import slant_delay, zenith_delay

DEFAULT = ("<DATA_ROOT>/N2_InSAR/N2/LV1A/HALA/"
           "N2_SAR_20250611_063619_ST_BB_VV_A_R_SSC_B_NP01.h5")
DEM_PATH = "<DATA_ROOT>/N2_InSAR/DEM/cop_dem_N33E126.tif"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Output")
H_LAND_MIN = 30.0        # 이 높이 아래(해안 저지·바다)는 정합에서 제외 — 지형 신호가 없다


def footprint_box(rd, sc, margin=0.01):
    ls = np.array([0, 0, sc.n_avail - 1, sc.n_avail - 1], float)
    cs = np.array([0, sc.ncols - 1, sc.ncols - 1, 0], float)
    lat, lon, _ = ecef_to_geodetic(rd.rdr2geo(ls, cs, 0.0))
    return lat.min() - margin, lat.max() + margin, lon.min() - margin, lon.max() + margin


def real_ml_db(sc, bl, bs, date):
    fn = os.path.join(OUT, f"ml_{date}_{bl}x{bs}.npy")
    if os.path.exists(fn):
        I = np.load(fn)
    else:
        t0 = time.time()
        I = multilook_intensity(sc, bl, bs)
        np.save(fn, I)
        print(f"    멀티룩 {bl}x{bs} 완료 {time.time()-t0:.0f} s -> {os.path.basename(fn)}")
    return 10.0 * np.log10(np.where(I > 0, I, np.nan))


HP_SCALE_M = 120.0       # 고역통과 가우시안 σ 의 물리 크기. DEM(30 m) 가 표현하는 지형 스케일보다 커야 한다
AZ_M_PER_LINE = 1.112    # 모델 지상 방위 간격 (Step 6-2)
GR_M_PER_SAMPLE = 1.867  # 지상 거리 간격 @32.4° (Step 6-2)


def sigma_bins(bl, bs):
    return (HP_SCALE_M / (bl * AZ_M_PER_LINE), HP_SCALE_M / (bs * GR_M_PER_SAMPLE))


def one_pass(rd, sc, dem_blk, real_db, bl, bs, search, label):
    S = simulate(rd, dem_blk, bl, bs, sc.n_avail, sc.ncols)
    sim, hmean = S["sim"], S["hmean"]
    H = min(sim.shape[0], real_db.shape[0]); W = min(sim.shape[1], real_db.shape[1])
    sim, hmean, rdb = sim[:H, :W], hmean[:H, :W], real_db[:H, :W]
    mask = (sim > 0) & np.isfinite(hmean) & (hmean > H_LAND_MIN)
    dl, ds, r, cc, dls, dss = match(rdb, sim, mask, search, sigma=sigma_bins(bl, bs))
    print(f"  [{label}] bin {bl}x{bs}: 오프셋 dl={dl:+.3f} bins ({dl*bl:+.1f} px), "
          f"ds={ds:+.3f} bins ({ds*bs:+.1f} px)   r_peak={r:.3f}   유효 bin {mask.sum()}")
    return dl * bl, ds * bs, r, dict(sim=sim, real=rdb, mask=mask, cc=cc, dls=dls, dss=dss, bl=bl, bs=bs)


def quadrants(F, label):
    """4분면별 오프셋 — 편향이 위치와 무관한 상수인지 검사."""
    sim, rdb, mask, bl, bs = F["sim"], F["real"], F["mask"], F["bl"], F["bs"]
    H, W = sim.shape
    out = {}
    print(f"  [{label}] 4분면 (bin {bl}x{bs})")
    for qn, (l0, l1, s0, s1) in {"early-near": (0, H // 2, 0, W // 2), "early-far": (0, H // 2, W // 2, W),
                                 "late-near": (H // 2, H, 0, W // 2), "late-far": (H // 2, H, W // 2, W)}.items():
        m = np.zeros_like(mask); m[l0:l1, s0:s1] = mask[l0:l1, s0:s1]
        if m.sum() < 500:
            print(f"    {qn:11}: 유효 bin 부족 ({m.sum()})"); continue
        qdl, qds, qr, *_ = match(rdb, sim, m, (6, 6), sigma=sigma_bins(bl, bs))
        out[qn] = dict(dl_px=qdl * bl, ds_px=qds * bs, r=qr, n=int(m.sum()))
        print(f"    {qn:11}: dl={qdl*bl:+6.2f} px ({qdl*bl*AZ_M_PER_LINE:+5.1f} m)  ds={qds*bs:+6.2f} px  r={qr:.3f}  (bin {m.sum()})")
    if len(out) >= 2:
        dls_ = np.array([v["dl_px"] for v in out.values()]); dss_ = np.array([v["ds_px"] for v in out.values()])
        print(f"    산포: dl σ={dls_.std():.2f} px ({dls_.std()*AZ_M_PER_LINE:.1f} m)   ds σ={dss_.std():.2f} px ({dss_.std()*GR_M_PER_SAMPLE:.1f} m)")
    return out


def main(path):
    sc = N2Scene(path)
    ob = Orbit(sc.sv_t, sc.sv_pos, sc.sv_vel, t_ref=sc.t_mid, deg=4)
    date = os.path.basename(path)[7:15]
    os.makedirs(OUT, exist_ok=True)
    res = dict(scene=date, file=os.path.basename(path))

    print("=" * 70); print("Step 7-0  대류권 지연 모델"); print("=" * 70)
    inc = 32.6
    for h in (0.0, 1000.0, 1950.0):
        print(f"  h={h:6.0f} m : 천정 {zenith_delay(h, 33.4):.3f} m   슬랜트(inc {inc}°) {slant_delay(h, 33.4, inc):.3f} m")
    rd = RangeDoppler(sc, ob, tropo=True)
    res["tropo_slant_m_sea"] = float(slant_delay(0.0, 33.4, inc))
    res["tropo_slant_m_summit"] = float(slant_delay(1950.0, 33.4, inc))

    print(); print("=" * 70); print("Step 7-1  DEM 블록 / 실영상 멀티룩"); print("=" * 70)
    dem = DEM(DEM_PATH)
    lat0, lat1, lon0, lon1 = footprint_box(rd, sc)
    print(f"  footprint(+여유) : lat {lat0:.4f}~{lat1:.4f}  lon {lon0:.4f}~{lon1:.4f}")
    N = dem.prepare_geoid(lat0, lat1, lon0, lon1)
    print(f"  EGM2008 N        : {N.min():.2f} ~ {N.max():.2f} m")
    blk = dem.block(lat0, lat1, lon0, lon1, oversample=2)
    print(f"  DEM 면요소       : {blk['lat'].shape} (15 m 격자),  높이 {np.nanmin(blk['h_ortho']):.0f}~{np.nanmax(blk['h_ortho']):.0f} m,"
          f"  경사 중앙 {np.nanmedian(blk['slope_deg']):.1f}°  최대 {np.nanmax(blk['slope_deg']):.1f}°")
    real_c = real_ml_db(sc, 27, 16, date)
    real_f = real_ml_db(sc, 9, 5, date)

    print(); print("=" * 70); print("Step 7-2  시뮬레이션 정합 반복"); print("=" * 70)
    hist = []
    figs = {}
    quads = {}
    # coarse 2회 (30 m bins) — 주 추정
    for it in range(2):
        dl, ds, r, F = one_pass(rd, sc, blk, real_c, 27, 16, (25, 25), f"coarse #{it+1}")
        hist.append(dict(scale="coarse", it=it + 1, dl_px=dl, ds_px=ds, r=r,
                         dt_bias_s=rd.dt_bias, dr_bias_m=rd.dr_bias))
        if it == 0:
            figs["coarse"] = F
        rd.add_image_offset(dl, ds)
    coarse_bias = (rd.dt_bias, rd.dr_bias)
    quads["coarse"] = quadrants(F, "coarse 적용 후")
    # fine 2회 (10 m bins) — 서브빈 정밀화. 고역통과 σ 를 같은 물리 스케일(120 m)로 유지
    for it in range(2):
        dl, ds, r, F = one_pass(rd, sc, blk, real_f, 9, 5, (12, 12), f"fine   #{it+1}")
        hist.append(dict(scale="fine", it=it + 1, dl_px=dl, ds_px=ds, r=r,
                         dt_bias_s=rd.dt_bias, dr_bias_m=rd.dr_bias))
        if it == 0:
            figs["fine"] = F
        rd.add_image_offset(dl, ds)
    # 최종 잔차 확인
    dl, ds, r, F = one_pass(rd, sc, blk, real_f, 9, 5, (6, 6), "fine 잔차")
    figs["final"] = F
    hist.append(dict(scale="fine-residual", it=0, dl_px=dl, ds_px=ds, r=r,
                     dt_bias_s=rd.dt_bias, dr_bias_m=rd.dr_bias))

    print(); print("=" * 70); print("Step 7-3  4분면 검사 (편향이 상수인가)"); print("=" * 70)
    quads["fine"] = quadrants(F, "fine 적용 후")
    print(f"\n  coarse 만 적용했을 때 : Δt_az {coarse_bias[0]*1e3:+.4f} ms ({coarse_bias[0]/sc.dt:+.2f} px),  ΔR {coarse_bias[1]:+.3f} m")
    res["coarse_only"] = dict(dt_bias_ms=coarse_bias[0] * 1e3, dt_bias_px=coarse_bias[0] / sc.dt, dr_bias_m=coarse_bias[1])

    # ---------------------------------------------------------------- 결과
    az_m_per_px = AZ_M_PER_LINE
    print(); print("=" * 70); print("결과"); print("=" * 70)
    print(f"  Δt_az (방위 시각 편향) : {rd.dt_bias*1e3:+.4f} ms  = {rd.dt_bias/sc.dt:+.2f} px  = {rd.dt_bias/sc.dt*az_m_per_px:+.2f} m 지상")
    print(f"  ΔR    (슬랜트거리 편향) : {rd.dr_bias:+.3f} m  = {rd.dr_bias/sc.dr:+.2f} px   [대류권 {res['tropo_slant_m_summit']:.2f}~{res['tropo_slant_m_sea']:.2f} m 는 별도 모델링됨]")
    print(f"  최종 잔차               : dl {dl:+.2f} px, ds {ds:+.2f} px   r={r:.3f}")
    print(f"  해석: 헤더 R0 보다 실제 기하거리가 {abs(rd.dr_bias):.1f} m {'짧다' if rd.dr_bias<0 else '길다'};"
          f" 헤더 t0 보다 실제 시각이 {abs(rd.dt_bias)*1e3:.3f} ms {'이르다' if rd.dt_bias<0 else '늦다'}")
    res.update(dt_bias_s=rd.dt_bias, dt_bias_ms=rd.dt_bias * 1e3, dt_bias_px=rd.dt_bias / sc.dt,
               dt_bias_ground_m=rd.dt_bias / sc.dt * az_m_per_px,
               dr_bias_m=rd.dr_bias, dr_bias_px=rd.dr_bias / sc.dr,
               final_residual_px=dict(dl=dl, ds=ds, r=r), history=hist, quadrants=quads,
               orbit_deg=4, dem=os.path.basename(DEM_PATH), land_min_m=H_LAND_MIN)
    with open(os.path.join(OUT, f"step03_bias_{date}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    # ---------------------------------------------------------------- 그림
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        for fp in ("/mnt/c/Windows/Fonts/malgun.ttf",):
            if os.path.exists(fp):
                font_manager.fontManager.addfont(fp)
                plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        plt.rcParams["axes.unicode_minus"] = False
        fig, ax = plt.subplots(2, 3, figsize=(15, 9))
        for row, key in enumerate(("coarse", "final")):
            Fk = figs[key]; sim_db = 10 * np.log10(np.where(Fk["sim"] > 0, Fk["sim"], np.nan))
            v = np.nanpercentile(Fk["real"][Fk["mask"]], (2, 98))
            ax[row, 0].imshow(sim_db, cmap="gray", aspect="auto"); ax[row, 0].set_title(f"{key}: DEM 시뮬레이션 (dB)")
            ax[row, 1].imshow(Fk["real"], cmap="gray", vmin=v[0], vmax=v[1], aspect="auto"); ax[row, 1].set_title(f"{key}: 실영상 멀티룩 (dB)")
            im = ax[row, 2].imshow(Fk["cc"], extent=[Fk["dss"][0], Fk["dss"][-1], Fk["dls"][-1], Fk["dls"][0]], cmap="viridis", aspect="auto")
            ax[row, 2].set_title(f"{key}: 상관면 (x=ds bins, y=dl bins)"); plt.colorbar(im, ax=ax[row, 2])
        fig.suptitle(f"{date}  Δt_az={rd.dt_bias*1e3:+.3f} ms  ΔR={rd.dr_bias:+.2f} m", fontsize=13)
        plt.tight_layout(); fn = os.path.join(OUT, f"step03_match_{date}.png"); plt.savefig(fn, dpi=110); plt.close()
        print(f"  그림 저장: {os.path.normpath(fn)}")
    except Exception as e:
        print("  [그림 생략]", e)
    return rd, res


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
