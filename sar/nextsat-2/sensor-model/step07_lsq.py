"""Step 7-LS: 창(타이포인트) 단위 다중 정합 → 강건 최소제곱으로 편향 모수와 표준오차 추정.

    python step07_lsq.py [h5 경로] [--bins 27x16] [--win 60] [--step 30] [--search 5] [--rmin 0.2]
    (기본 = 30 m bins, 1.8 km 창.  fine 9x5 는 창당 잡음이 커서 SE 가 5 px 로 나쁨 — 20250611 실험)

step03 과 같은 시뮬레이션·정합 규칙을 쓰되, 씬 전체 피크 1개 대신
  1) coarse 전역 정합으로 초기 편향 적용 (step03 coarse #1 과 동일)
  2) fine(9x5 bins ≈ 10 m) 격자를 win x win bins 창으로 나눠 창마다 잔여 오프셋 (dl, ds, r) 관측
  3) 씬별 강건 LS (Huber IRLS, 상관 r 가중)
       상수 모델   dl = a0,                    ds = b0
       선형 모델   dl = a0 + a1·ℓ + a2·ŝ,     ds = b0 + b1·ℓ + b2·ŝ    (ℓ, ŝ ∈ [-0.5, 0.5] 정규화 좌표)
     → 모수, 표준오차, 선형항 t-통계(|t| > 2 면 위치의존 존재), 잔차 RMS
  4) 결합조정(step08) 용 씬 기하(지상 방위/거리 방향 벡터, 입사각) 를 JSON 에 저장

출력  ../Output/step07_lsq_<date>.json, step07_lsq_<date>.png
"""
import sys, os, json
import numpy as np
from pyproj import Transformer
from n2reader import N2Scene
from orbit import Orbit
from geometry import RangeDoppler, ecef_to_geodetic
from dem import DEM
from simulate import simulate, _peak2d, _hp
from tropo import slant_delay
import step03_bias_dem as S3

DEFAULT = S3.DEFAULT
OUT = S3.OUT
BL, BS = 9, 5                    # fine bins


# ----------------------------------------------------------------------------- 창 정합
def window_offsets(a, b, m, win, step, search, min_fill=0.5, min_pts=2000):
    """고역통과된 real(a), sim(b), 마스크 m 위에서 창별 오프셋. 반환 리스트 of dict(lc, sc [bins], dl, ds [bins], r, n)"""
    H, W = a.shape
    out = []
    for r0 in range(0, H - win + 1, step):
        for c0 in range(0, W - win + 1, step):
            M0 = m[r0:r0 + win, c0:c0 + win]
            if M0.mean() < min_fill:
                continue
            A = a[r0:r0 + win, c0:c0 + win]
            S = search
            cc = np.full((2 * S + 1, 2 * S + 1), np.nan)
            for i, dl in enumerate(range(-S, S + 1)):
                for j, ds in enumerate(range(-S, S + 1)):
                    rr0, rr1 = r0 - dl, r0 - dl + win; cc0, cc1 = c0 - ds, c0 - ds + win
                    if rr0 < 0 or cc0 < 0 or rr1 > H or cc1 > W:
                        continue
                    B = b[rr0:rr1, cc0:cc1]; M = M0 & m[rr0:rr1, cc0:cc1]
                    if M.sum() < min_pts:
                        continue
                    x = A[M]; y = B[M]; x = x - x.mean(); y = y - y.mean()
                    d = np.sqrt((x * x).sum() * (y * y).sum())
                    cc[i, j] = (x * y).sum() / d if d > 0 else np.nan
            if not np.any(np.isfinite(cc)):
                continue
            k = np.nanargmax(cc); i, j = np.unravel_index(k, cc.shape)
            if i == 0 or j == 0 or i == 2 * S or j == 2 * S:       # 탐색 경계에 걸린 피크는 버림
                continue
            di, dj = _peak2d(cc, i, j, 2)
            out.append(dict(lc=r0 + win / 2, sc=c0 + win / 2, dl=(i - S) + di, ds=(j - S) + dj,
                            r=float(cc[i, j]), n=int(M0.sum())))
    return out


# ----------------------------------------------------------------------------- 강건 LS
def robust_ls(X, y, w0, iters=10, c=1.345):
    """Huber IRLS. 반환 beta, se, resid, w(최종 가중), sigma"""
    w = w0.copy()
    for _ in range(iters):
        Wx = X * w[:, None]
        beta, *_ = np.linalg.lstsq(Wx.T @ X, Wx.T @ y, rcond=None)
        e = y - X @ beta
        s = 1.4826 * np.median(np.abs(e - np.median(e))) + 1e-9
        wh = np.minimum(1.0, c * s / np.maximum(np.abs(e), 1e-9))
        w = w0 * wh
    Wx = X * w[:, None]
    dof = max(1, w.sum() / w.max() - X.shape[1])            # 유효 자유도 근사
    sigma2 = (w * e * e).sum() / (w.sum() * (dof / (dof + X.shape[1])))
    cov = sigma2 * np.linalg.inv(Wx.T @ X)
    return beta, np.sqrt(np.diag(cov)), e, w, np.sqrt(sigma2)


def fit_scene(obs, nbl, nbs):
    L = np.array([o["lc"] for o in obs]) / nbl - 0.5
    Sm = np.array([o["sc"] for o in obs]) / nbs - 0.5
    r = np.array([o["r"] for o in obs]); w0 = np.clip(r, 0.05, None) ** 2
    res = {}
    for key in ("dl", "ds"):
        y = np.array([o[key] for o in obs])
        X0 = np.ones((len(y), 1))
        X1 = np.stack([np.ones_like(y), L, Sm], 1)
        b0, se0, e0, w_, s0 = robust_ls(X0, y, w0)
        b1, se1, e1, _, s1 = robust_ls(X1, y, w0)
        res[key] = dict(const=dict(beta=b0.tolist(), se=se0.tolist(), rms=float(np.sqrt(np.average(e0 ** 2, weights=w_)))),
                        linear=dict(beta=b1.tolist(), se=se1.tolist(), t=(b1 / se1).tolist(),
                                    rms=float(np.sqrt(np.average(e1 ** 2, weights=w_)))),
                        weights=w_.tolist())
    return res


# ----------------------------------------------------------------------------- 메인
def main(path, win=60, step=30, search=5, bins=(27, 16), rmin=0.20):   # 기본 = 30 m bins 최적 구성
    global BL, BS
    BL, BS = bins
    sc = N2Scene(path)
    ob = Orbit(sc.sv_t, sc.sv_pos, sc.sv_vel, t_ref=sc.t_mid, deg=4)
    date = os.path.basename(path)[7:15]; tag = f"{sc.orbit_dir[0]}{sc.look_side[0]}"
    rd = RangeDoppler(sc, ob, tropo=True)
    os.makedirs(OUT, exist_ok=True)

    print("=" * 70); print(f"Step 7-LS  {date} {tag}   창 {win} bins ({win*BL*S3.AZ_M_PER_LINE/1000:.1f} x {win*BS*S3.GR_M_PER_SAMPLE/1000:.1f} km), 간격 {step}"); print("=" * 70)
    dem = DEM(S3.DEM_PATH)
    lat0, lat1, lon0, lon1 = S3.footprint_box(rd, sc)
    dem.prepare_geoid(lat0, lat1, lon0, lon1)
    blk = dem.block(lat0, lat1, lon0, lon1, oversample=2)
    real_c = S3.real_ml_db(sc, 27, 16, date)
    real_f = S3.real_ml_db(sc, BL, BS, date)
    print(f"  정합 격자 bins {BL}x{BS} = {BL*S3.AZ_M_PER_LINE:.0f} x {BS*S3.GR_M_PER_SAMPLE:.0f} m,  피크탐색 ±{search} bins")

    # 1) 초기 편향: coarse 전역 (step03 과 동일)
    dl, ds, r, _ = S3.one_pass(rd, sc, blk, real_c, 27, 16, (25, 25), "coarse 초기")
    rd.add_image_offset(dl, ds)
    init = dict(dt_bias_s=rd.dt_bias, dr_bias_m=rd.dr_bias, dl_px=dl, ds_px=ds, r=r)

    # 2) fine 시뮬 + 창 정합
    S = simulate(rd, blk, BL, BS, sc.n_avail, sc.ncols)
    sim, hmean = S["sim"], S["hmean"]
    H = min(sim.shape[0], real_f.shape[0]); W = min(sim.shape[1], real_f.shape[1])
    sim, hmean, rdb = sim[:H, :W], hmean[:H, :W], real_f[:H, :W]
    mask = (sim > 0) & np.isfinite(hmean) & (hmean > S3.H_LAND_MIN) & np.isfinite(rdb)
    sig = S3.sigma_bins(BL, BS)
    sim_db = 10 * np.log10(np.where(sim > 0, sim, np.nan))
    a = _hp(np.nan_to_num(rdb, nan=np.nanmean(rdb)), sig)
    b = _hp(np.nan_to_num(sim_db, nan=np.nanmean(sim_db)), sig)
    obs = window_offsets(a, b, mask, win, step, search)
    n_all = len(obs)
    obs = [o for o in obs if o["r"] > rmin]
    print(f"  창 관측 {len(obs)} / {n_all} 개 (r > {rmin})   r 중앙 {np.median([o['r'] for o in obs]):.3f}")
    if len(obs) < 8:
        print("  관측 부족"); return

    # 3) 강건 LS
    fit = fit_scene(obs, H, W)
    print(f"\n  {'':6} {'상수모델 a0/b0 [px]':>22} {'±SE':>7} {'RMS':>6} | {'선형모델 a0':>11} {'a1(방위기울기)':>16} {'a2(거리기울기)':>16} {'RMS':>6}")
    for key, bl_, name in (("dl", BL, "방위"), ("ds", BS, "거리")):
        c_ = fit[key]["const"]; l_ = fit[key]["linear"]
        print(f"  {name:6} {c_['beta'][0]*bl_:>22.2f} {c_['se'][0]*bl_:>7.2f} {c_['rms']*bl_:>6.2f} | "
              f"{l_['beta'][0]*bl_:>11.2f} {l_['beta'][1]*bl_:>8.2f} (t={l_['t'][1]:+4.1f}) {l_['beta'][2]*bl_:>8.2f} (t={l_['t'][2]:+4.1f}) {l_['rms']*bl_:>6.2f}")
    print("   (선형항 값은 '씬 한쪽 끝에서 반대쪽 끝까지의 변화량' [px].  |t| < 2 면 0 과 구분 안 됨 → 상수모델로 충분)")

    # 4) 최종 편향 = 초기 + 상수모델 잔여
    a0 = fit["dl"]["const"]["beta"][0] * BL; b0 = fit["ds"]["const"]["beta"][0] * BS
    se_a0 = fit["dl"]["const"]["se"][0] * BL; se_b0 = fit["ds"]["const"]["se"][0] * BS
    rd.add_image_offset(a0, b0)
    az_m = S3.AZ_M_PER_LINE
    print(f"\n  최종  Δt_az = {rd.dt_bias*1e3:+.4f} ± {se_a0*sc.dt*1e3:.4f} ms   ({rd.dt_bias/sc.dt:+.2f} ± {se_a0:.2f} px = {rd.dt_bias/sc.dt*az_m:+.2f} ± {se_a0*az_m:.2f} m 지상)")
    print(f"        ΔR    = {rd.dr_bias:+.3f} ± {se_b0*sc.dr:.3f} m")
    j3 = os.path.join(OUT, f"step03_bias_{date}.json")
    if os.path.exists(j3):
        s3 = json.load(open(j3, encoding="utf-8"))
        print(f"  step03 (피크 1개)  Δt_az {s3['dt_bias_ms']:+.4f} ms,  ΔR {s3['dr_bias_m']:+.3f} m   → 차이 {(rd.dt_bias*1e3-s3['dt_bias_ms']):+.4f} ms / {(rd.dr_bias-s3['dr_bias_m']):+.3f} m")

    # 씬 기하 (결합조정용): 중심에서 방위/거리 지상 방향과 입사각
    to_utm = Transformer.from_crs(4326, 32652, always_xy=True)
    lc, cc_ = sc.n_avail // 2, sc.ncols // 2
    def EN(l, s):
        lat, lon, _ = ecef_to_geodetic(rd.rdr2geo(l, s, 0.0)); return np.array(to_utm.transform(lon, lat))
    P0, Pa, Pr = EN(lc, cc_), EN(lc + 1000, cc_), EN(lc, cc_ + 1000)
    az_vec = (Pa - P0) / 1000.0; rg_vec = (Pr - P0) / 1000.0            # m per line / m per sample (지상)
    inc = float(rd.incidence_deg(rd.rdr2geo(lc, cc_, 0.0), rd.t_of_line(lc)))
    geom = dict(az_dir_EN=(az_vec / np.linalg.norm(az_vec)).tolist(), m_per_line=float(np.linalg.norm(az_vec)),
                rg_dir_EN=(rg_vec / np.linalg.norm(rg_vec)).tolist(), m_per_sample_ground=float(np.linalg.norm(rg_vec)),
                inc_deg=inc, orbit_dir=sc.orbit_dir, look_side=sc.look_side, dt_s=sc.dt, dr_m=sc.dr)

    res = dict(scene=date, tag=tag, win_bins=win, step_bins=step, bins=[BL, BS], n_obs=len(obs), init=init,
               fit=fit, dt_bias_s=rd.dt_bias, dt_bias_ms=rd.dt_bias * 1e3, dt_bias_px=rd.dt_bias / sc.dt,
               dt_bias_se_ms=se_a0 * sc.dt * 1e3, dr_bias_m=rd.dr_bias, dr_bias_se_m=se_b0 * sc.dr,
               geom=geom, obs=obs)
    with open(os.path.join(OUT, f"step07_lsq_{date}_{BL}x{BS}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    # 그림: 창별 잔여 오프셋 벡터 + 히스토그램
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from matplotlib import font_manager
        fp = "/mnt/c/Windows/Fonts/malgun.ttf"
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp); plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        fig, ax = plt.subplots(1, 3, figsize=(16, 8), gridspec_kw=dict(width_ratios=[1.2, 1, 1]))
        v = np.nanpercentile(rdb[mask], (2, 98))
        ax[0].imshow(rdb, cmap="gray", vmin=v[0], vmax=v[1], aspect="auto")
        xs = [o["sc"] for o in obs]; ys = [o["lc"] for o in obs]
        u = [o["ds"] * BS for o in obs]; vv = [o["dl"] * BL for o in obs]; rr = [o["r"] for o in obs]
        q = ax[0].quiver(xs, ys, u, vv, rr, cmap="viridis", angles="xy", scale_units="xy", scale=0.5, width=0.004)   # 1 px 오프셋 = 2 bins 길이
        plt.colorbar(q, ax=ax[0], label="창 상관 r"); ax[0].set_title(f"{date} 창별 잔여 오프셋 [px] (초기 coarse 편향 적용 후)")
        ax[0].set_xlabel(f"sample bins ({BS} px)"); ax[0].set_ylabel(f"line bins ({BL} px)")
        for k, (key, bl_, name) in enumerate((("dl", BL, "방위"), ("ds", BS, "거리"))):
            y = np.array([o[key] for o in obs]) * bl_
            ax[k + 1].hist(y, bins=30, color="C0", alpha=.8)
            c_ = fit[key]["const"]
            ax[k + 1].axvline(c_["beta"][0] * bl_, color="r", label=f"강건평균 {c_['beta'][0]*bl_:+.2f} ± {c_['se'][0]*bl_:.2f} px")
            ax[k + 1].set_title(f"{name} 잔여 오프셋 분포 (n={len(y)})"); ax[k + 1].set_xlabel("px"); ax[k + 1].legend()
        plt.tight_layout(); fn = os.path.join(OUT, f"step07_lsq_{date}_{BL}x{BS}.png"); plt.savefig(fn, dpi=100); plt.close()
        print(f"  그림: {os.path.normpath(fn)}")
    except Exception as e:
        print("  [그림 생략]", e)
    return res


if __name__ == "__main__":
    a = sys.argv[1:]
    # 기본값 = 20250611 실험에서 SE 가 가장 작았던 구성 (30 m bins, 1.8 km 창, 50 % 중첩)
    win = int(a[a.index("--win") + 1]) if "--win" in a else 60
    stp = int(a[a.index("--step") + 1]) if "--step" in a else 30
    srch = int(a[a.index("--search") + 1]) if "--search" in a else 5
    bins = tuple(int(x) for x in a[a.index("--bins") + 1].split("x")) if "--bins" in a else (27, 16)
    rmin = float(a[a.index("--rmin") + 1]) if "--rmin" in a else 0.20
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or not a[i - 1].startswith("--"))]
    main(pos[0] if pos else DEFAULT, win, stp, srch, bins, rmin)
