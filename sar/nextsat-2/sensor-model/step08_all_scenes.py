"""Step 8: 한라산 12씬 전부 step07(창 LS) 실행 → 4모수 결합 최소제곱으로 센서 상수와 DEM 지상오프셋 분리.

    python step08_all_scenes.py [--skip-existing]

모델 (씬 i 의 편향 추정치를 관측으로)
    dt_i = Δt_s + (D · â_i) / v_i              â_i : 지상 방위 단위벡터(E,N), v_i = m_per_line/dt (지상 방위 속도)
    dR_i = ΔR_s + (D · r̂_i) · sin(inc_i)       r̂_i : 지상 거리 단위벡터(근→원), D = (dE, dN) DEM 수평오프셋
  미지수 4개 (Δt_s, ΔR_s, dE, dN), 관측 2×12, 가중 1/SE².
  상승/하강에서 â 가, 좌/우룩에서 r̂ 가 부호를 바꾸므로 센서 상수와 지상오프셋이 분리된다.

출력  ../Output/step08_joint.json, step08_joint.png, 콘솔 표
"""
import sys, os, glob, json, time, traceback
import numpy as np
import step07_lsq as S7

HALA = "<DATA_ROOT>/N2_InSAR/N2/LV1A/HALA"
OUT = S7.OUT


def run_all(skip_existing=True):
    files = sorted(glob.glob(os.path.join(HALA, "*_SSC_*.h5")))
    print(f"씬 {len(files)} 개"); t0 = time.time()
    for k, f in enumerate(files):
        date = os.path.basename(f)[7:15]
        j = os.path.join(OUT, f"step07_lsq_{date}_27x16.json")
        if skip_existing and os.path.exists(j):
            print(f"[{k+1:2d}/{len(files)}] {date} 기존 결과 사용"); continue
        print(f"\n[{k+1:2d}/{len(files)}] {date}  ({(time.time()-t0)/60:.1f} min 경과)")
        try:
            S7.main(f, win=60, step=30, search=5, bins=(27, 16), rmin=0.20)   # 구성을 명시
        except Exception as e:
            print(f"  !! {date} 실패: {e}"); traceback.print_exc()


def joint():
    rows = []
    for j in sorted(glob.glob(os.path.join(OUT, "step07_lsq_*_27x16.json"))):
        r = json.load(open(j, encoding="utf-8")); g = r["geom"]
        rows.append(dict(date=r["scene"], tag=r["tag"], inc=g["inc_deg"], n=r["n_obs"],
                         dt=r["dt_bias_s"], dt_se=r["dt_bias_se_ms"] / 1e3, dR=r["dr_bias_m"], dR_se=r["dr_bias_se_m"],
                         a=np.array(g["az_dir_EN"]), rhat=np.array(g["rg_dir_EN"]), v=g["m_per_line"] / g["dt_s"],
                         t_az_slope=r["fit"]["dl"]["linear"]["t"][1], t_rg_slope=r["fit"]["ds"]["linear"]["t"][2],
                         az_m_per_line=g["m_per_line"], r_med=float(np.median([o["r"] for o in r["obs"]]))))
    n = len(rows)
    print("\n" + "=" * 100); print("씬별 편향 (창 LS)"); print("=" * 100)
    print(f"{'날짜':10}{'궤도':5}{'입사각':>7}{'창':>5}{'r중앙':>7}{'Δt_az ms':>11}{'±':>7}{'방위 m':>8}{'ΔR m':>9}{'±':>6}{'t(방위기울기)':>13}{'t(거리기울기)':>13}")
    for r in rows:
        print(f"{r['date']:10}{r['tag']:5}{r['inc']:7.1f}{r['n']:5d}{r['r_med']:7.2f}{r['dt']*1e3:11.4f}{r['dt_se']*1e3:7.4f}"
              f"{r['dt']*r['v']:8.2f}{r['dR']:9.3f}{r['dR_se']:6.3f}{r['t_az_slope']:13.1f}{r['t_rg_slope']:13.1f}")
    dts = np.array([r["dt"] for r in rows]); dRs = np.array([r["dR"] for r in rows])
    print(f"\n  단순 통계  Δt_az 평균 {dts.mean()*1e3:+.4f} ms  σ {dts.std()*1e3:.4f} ms   |  ΔR 평균 {dRs.mean():+.3f} m  σ {dRs.std():.3f} m")

    # ---- 4모수 결합 LS
    A = []; y = []; w = []
    for r in rows:
        # dt 식: [1, 0, a_E/v, a_N/v]
        A.append([1.0, 0.0, r["a"][0] / r["v"], r["a"][1] / r["v"]]); y.append(r["dt"]); w.append(1.0 / max(r["dt_se"], 1e-6) ** 2)
        # dR 식: [0, 1, r_E·sin, r_N·sin]
        s = np.sin(np.radians(r["inc"]))
        A.append([0.0, 1.0, r["rhat"][0] * s, r["rhat"][1] * s]); y.append(r["dR"]); w.append(1.0 / max(r["dR_se"], 1e-3) ** 2)
    A = np.array(A); y = np.array(y); w = np.array(w)
    # 단위 스케일: dt 는 초, dR 은 m — 가중으로 처리되므로 그대로
    Aw = A * np.sqrt(w)[:, None]; yw = y * np.sqrt(w)
    x, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
    e = y - A @ x
    dof = len(y) - 4
    chi2 = float((w * e * e).sum()); s0 = np.sqrt(chi2 / dof)
    cov = np.linalg.inv(Aw.T @ Aw) * max(s0 ** 2, 1.0)        # s0>1 이면 SE 과소평가 보정
    se = np.sqrt(np.diag(cov))
    Dt, DR, dE, dN = x
    print("\n" + "=" * 100); print("4모수 결합 최소제곱  (센서 상수 + DEM 지상오프셋)"); print("=" * 100)
    print(f"  Δt_s (센서 방위 시각편향) = {Dt*1e3:+.4f} ± {se[0]*1e3:.4f} ms   ≈ {Dt*np.mean([r['v'] for r in rows]):+.2f} m 지상")
    print(f"  ΔR_s (센서 거리편향)      = {DR:+.3f} ± {se[1]:.3f} m")
    print(f"  D    (DEM 지상오프셋)      = 동 {dE:+.2f} ± {se[2]:.2f} m,  북 {dN:+.2f} ± {se[3]:.2f} m   (크기 {np.hypot(dE,dN):.2f} m)")
    print(f"  단위분산 s0 = {s0:.2f}  (1 이면 SE 가 산포를 정확히 설명, >1 이면 씬별 추가 오차 존재)   dof={dof}")
    print("\n  씬별 잔차 (관측 − 모델):")
    print(f"  {'날짜':10}{'궤도':5}{'dt 잔차 ms':>12}{'(px)':>7}{'dR 잔차 m':>11}{'표준화 dt':>10}{'표준화 dR':>10}")
    res_rows = []
    for k, r in enumerate(rows):
        et, eR = e[2 * k], e[2 * k + 1]
        zt = et / r["dt_se"]; zR = eR / r["dR_se"]
        print(f"  {r['date']:10}{r['tag']:5}{et*1e3:12.4f}{et/(r['az_m_per_line']/r['v']):7.2f}{eR:11.3f}{zt:10.1f}{zR:10.1f}")
        res_rows.append(dict(date=r["date"], tag=r["tag"], e_dt_ms=et * 1e3, e_dR_m=eR, z_dt=zt, z_dR=zR))
    # 비교: 2모수(지상오프셋 없이)
    A2 = A[:, :2]; A2w = A2 * np.sqrt(w)[:, None]
    x2, *_ = np.linalg.lstsq(A2w, yw, rcond=None); e2 = y - A2 @ x2; chi2_2 = float((w * e2 * e2).sum())
    print(f"\n  비교  2모수(센서만) χ² = {chi2_2:.1f} (dof {len(y)-2})  →  4모수 χ² = {chi2:.1f} (dof {dof})."
          f"  감소량 {chi2_2-chi2:.1f} (자유도 2 추가; 6 이상이면 DEM 오프셋이 유의)")

    out = dict(n_scenes=n, joint=dict(dt_s=Dt, dt_ms=Dt * 1e3, dt_se_ms=se[0] * 1e3, dR_m=DR, dR_se_m=se[1],
                                      dE_m=dE, dE_se=se[2], dN_m=dN, dN_se=se[3], s0=s0, chi2=chi2, dof=dof, chi2_2param=chi2_2),
               scenes=[dict(date=r["date"], tag=r["tag"], inc=r["inc"], n=r["n"], dt_ms=r["dt"] * 1e3, dt_se_ms=r["dt_se"] * 1e3,
                            dR_m=r["dR"], dR_se_m=r["dR_se"], t_az_slope=r["t_az_slope"], t_rg_slope=r["t_rg_slope"]) for r in rows],
               residuals=res_rows)
    json.dump(out, open(os.path.join(OUT, "step08_joint.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- 그림
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from matplotlib import font_manager
        fp = "/mnt/c/Windows/Fonts/malgun.ttf"
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp); plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        plt.rcParams["axes.unicode_minus"] = False
        col = {"AR": "C0", "AL": "C1", "DR": "C2", "DL": "C3"}
        fig, ax = plt.subplots(1, 2, figsize=(14, 6))
        xs = np.arange(n); labels = [f"{r['date'][4:]}\n{r['tag']}" for r in rows]
        for k, r in enumerate(rows):
            ax[0].errorbar(k, r["dt"] * 1e3, yerr=r["dt_se"] * 1e3, fmt="o", color=col.get(r["tag"], "k"), capsize=3)
            ax[0].plot(k, (A @ x)[2 * k] * 1e3, "k_", ms=14, mew=2)
            ax[1].errorbar(k, r["dR"], yerr=r["dR_se"], fmt="o", color=col.get(r["tag"], "k"), capsize=3)
            ax[1].plot(k, (A @ x)[2 * k + 1], "k_", ms=14, mew=2)
        ax[0].axhline(Dt * 1e3, color="gray", ls="--", label=f"센서 Δt_s = {Dt*1e3:+.3f} ms"); ax[1].axhline(DR, color="gray", ls="--", label=f"센서 ΔR_s = {DR:+.2f} m")
        for a_, t_ in zip(ax, ("방위 시각편향 Δt_az [ms]  (○ 씬 추정 ± SE, — 4모수 모델)", "거리편향 ΔR [m]")):
            a_.set_xticks(xs); a_.set_xticklabels(labels, fontsize=8); a_.set_title(t_); a_.grid(alpha=.3); a_.legend()
        from matplotlib.lines import Line2D
        ax[0].legend(handles=[Line2D([], [], marker="o", color=c, ls="", label=t) for t, c in col.items() if any(r["tag"] == t for r in rows)]
                     + [Line2D([], [], color="gray", ls="--", label=f"Δt_s {Dt*1e3:+.3f} ms")], fontsize=9)
        fig.suptitle(f"한라산 {n}씬 결합조정:  DEM 오프셋 동 {dE:+.1f} m / 북 {dN:+.1f} m,  s0={s0:.2f}")
        plt.tight_layout(); fn = os.path.join(OUT, "step08_joint.png"); plt.savefig(fn, dpi=110); plt.close()
        print(f"  그림: {os.path.normpath(fn)}")
    except Exception as ex:
        print("  [그림 생략]", ex)
    return out


if __name__ == "__main__":
    if "--joint-only" not in sys.argv:
        run_all(skip_existing="--skip-existing" in sys.argv or True)
    joint()
