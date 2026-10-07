# -*- coding: utf-8 -*-
"""사상 AOI(AOI.xlsx 박스) 한정 — 사고 버퍼 vs 비사고 대조군 판별 필터 최적화.
사용자 관찰(사고 주변에 주의/위험이 조밀·깊게 몰림)을 판별자로: 버퍼 내 주의/위험 개수·밀도·최대누적침하.
★in-sample 튜닝(사상 사례 시연). 일반화 검증 아님. asof=사고일 이전(공정 조기경보).
관측이 사고 직전 시작해 사고전 시계열이 부족한 건은 '관측이전-불가피'로 분리(억지 recall 방지)."""
import os; os.environ.pop("PYTHONPATH", None)
import sys; sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np, pandas as pd; from scipy.spatial import cKDTree
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import subsidence_list_analysis as M, loaders, make_unified_map as mum

ORD = {"정상": 0, "주의": 1, "위험": 2}
REG = "Busan_Sasang_Hadan"; R = 300.0; OUT = "<DATA_ROOT>/analysis/sinkhole/out/acclist_Busan_Sasang_Hadan_aoibox"
M.ACFG["clip_bbox"] = True; M.ACFG["regions"] = [REG]
S, N, W, E = mum.AOI_SNWE[REG]
acc = M.load_accidents(); bank = M.load_region_bank(); e = bank[REG]


def feats(lat, lon, asof, r=R):
    ax, ay = loaders._TR_M.transform([lon], [lat]); p = np.array([ax[0], ay[0]])
    n_buf = n_elev = n_dng = 0; rc = []
    for kind in ("PS", "SBAS"):
        k = e["kinds"][kind]; t = k["tree"]
        if t is None: continue
        idx = np.array(t.query_ball_point(p, r), int)
        if not len(idx): continue
        J = M.judge_points(k["disp"][idx], k["years"], k["vel"][idx], k["alpha"][idx], asof)
        if J is None: continue
        for j in range(len(idx)):
            g = J["grade"][j]; n_buf += 1
            n_elev += ORD[g] >= 1; n_dng += ORD[g] >= 2; rc.append(J["rc"][j])
    area = np.pi * (r / 1000) ** 2
    return dict(n_buf=n_buf, n_elev=int(n_elev), n_dng=int(n_dng),
                frac=n_elev / max(1, n_buf), dens=n_elev / area,
                dens_dng=n_dng / area, maxrc=max(rc) if rc else 0.0)


def auc(a, c):
    """Mann-Whitney U 기반 AUC = P(사고>대조군)."""
    a = np.asarray(a); c = np.asarray(c); wins = 0.0
    for v in a:
        wins += np.sum(v > c) + 0.5 * np.sum(v == c)
    return wins / (len(a) * len(c))


def main():
    inbox = [a for a in acc if a["year"] and S <= a["lat"] <= N and W <= a["lon"] <= E]
    det, undet = [], []
    for a in inbox:
        f = feats(a["lat"], a["lon"], a["year"])
        (det if f["n_buf"] > 0 else undet).append((a, f))
    print(f"박스 안 사고 {len(inbox)}건 = 관측가능 {len(det)} + 관측이전-불가피 {len(undet)}")
    for a, f in undet:
        print(f"  [관측이전-불가피] {a['no']} {M._fmt(a['date'])} (사고 전 관측 부족)")

    # 대조군: 박스 안, 사고서 ≥R, asof=랜덤 사고연도, 충분한 사고전관측
    rs = np.random.RandomState(7); yrs = [a["year"] for a, _ in det]
    axr, ayr = loaders._TR_M.transform([a["lon"] for a in acc], [a["lat"] for a in acc])
    atree = cKDTree(np.c_[axr, ayr])
    kk = e["kinds"]["SBAS"] if len(e["kinds"]["SBAS"]["lon"]) else e["kinds"]["PS"]
    Np = len(kk["lon"]); cf = []; tries = 0
    while len(cf) < 400 and tries < 12000:
        tries += 1; j = rs.randint(Np); p = np.array([kk["x"][j], kk["y"][j]])
        if atree.query(p)[0] < R: continue
        f = feats(kk["lat"][j], kk["lon"][j], yrs[rs.randint(len(yrs))])
        if f["n_buf"] > 0: cf.append(f)
    print(f"대조군 {len(cf)}지점 (박스 내, 사고서 ≥{R:.0f}m)\n")

    KEYS = [("주의+위험 개수", "n_elev"), ("위험 개수", "n_dng"),
            ("주의위험 비율", "frac"), ("주의위험 밀도/km²", "dens"),
            ("위험 밀도/km²", "dens_dng"), ("최대누적침하mm", "maxrc")]
    A = {k: np.array([f[k] for _, f in det]) for _, k in KEYS}
    C = {k: np.array([f[k] for f in cf]) for _, k in KEYS}
    print(f"{'특징':16s} {'사고중앙':>8} {'대조중앙':>8} {'AUC':>6} {'recall100임계':>12} {'대조군초과%':>9} {'Youden임계':>9} {'그때 recall/대조':>14}")
    best = None
    for nm, k in KEYS:
        a, c = A[k], C[k]; au = auc(a, c)
        thr100 = a.min(); cfp100 = 100 * np.mean(c >= thr100)
        # Youden J 최적 임계
        cand = np.unique(np.concatenate([a, c]))
        J = [(np.mean(a >= t) - np.mean(c >= t), t) for t in cand]
        jmax, tY = max(J); recY = 100 * np.mean(a >= tY); cfpY = 100 * np.mean(c >= tY)
        print(f"{nm:16s} {np.median(a):8.1f} {np.median(c):8.1f} {au:6.2f} "
              f"{thr100:12.1f} {cfp100:9.0f} {tY:9.1f} {recY:5.0f}%/{cfpY:.0f}%")
        score = (au, -cfp100)
        if best is None or score > best[0]:
            best = (score, nm, k, tY, recY, cfpY, au)

    # 2특징 복합 규칙: 위험밀도 AND 최대누적 (둘 다 대조군 상위 관점)
    print("\n■ 복합 규칙 탐색 (recall 100% of 관측가능 유지하며 대조군 최소화)")
    for (n1, k1), (n2, k2) in [(("위험 밀도", "dens_dng"), ("최대누적", "maxrc")),
                               (("주의위험 개수", "n_elev"), ("최대누적", "maxrc"))]:
        t1 = A[k1].min(); t2 = A[k2].min()   # recall100 → 각 축 사고 최솟값
        rec = 100 * np.mean((A[k1] >= t1) & (A[k2] >= t2))
        cfp = 100 * np.mean((C[k1] >= t1) & (C[k2] >= t2))
        print(f"  {n1}≥{t1:.1f} AND {n2}≥{t2:.1f}  → recall {rec:.0f}% · 대조군 {cfp:.0f}%")

    sc, nm, k, tY, recY, cfpY, au = best
    print(f"\n■ 단일 최적(AUC): [{nm}] AUC={au:.2f}, Youden 임계≥{tY:.1f}에서 recall {recY:.0f}% · 대조군 {cfpY:.0f}%")
    print(f"\n[정직 요약] 관측가능 {len(det)}/{len(inbox)}건(2018 관측이전 1건 제외) 기준.")
    t_rc = float(A['maxrc'].min()); t_dn = float(A['dens_dng'].min())
    cfp_rc = 100 * np.mean(C['maxrc'] >= t_rc)
    cfp_comb = 100 * np.mean((C['dens_dng'] >= t_dn) & (C['maxrc'] >= t_rc))
    print(f"  최대누적침하 recall100 임계={t_rc:.0f}mm → 대조군 {cfp_rc:.0f}%")

    # ---- 시각화 (2패널) ----
    os.makedirs(OUT, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    a_rc, c_rc = A['maxrc'], C['maxrc']
    ax[0].hist(c_rc, bins=30, alpha=0.6, color="#2166ac", label=f"control n={len(c_rc)}", density=True)
    ax[0].hist(a_rc, bins=15, alpha=0.7, color="#c0392b", label=f"accident n={len(a_rc)}", density=True)
    ax[0].axvline(t_rc, color="k", ls="--", lw=1.5, label=f"thr={t_rc:.0f}mm (recall100)")
    ax[0].set_title(f"max cumulative subsidence (AUC={auc(a_rc,c_rc):.2f})")
    ax[0].set_xlabel("max cumulative subsidence in buffer (mm)"); ax[0].legend(fontsize=8)
    ax[1].scatter(C['maxrc'], C['dens_dng'], s=12, c="#2166ac", alpha=0.4, label="control")
    ax[1].scatter(A['maxrc'], A['dens_dng'], s=45, c="#c0392b", edgecolor="k", label="accident(obs)")
    ax[1].axvline(t_rc, color="k", ls="--", lw=1); ax[1].axhline(t_dn, color="k", ls="--", lw=1)
    ax[1].set_title(f"rule: maxcum>={t_rc:.0f} AND danger-density>={t_dn:.0f}\nrecall 100% / control {cfp_comb:.0f}%")
    ax[1].set_xlabel("max cumulative (mm)"); ax[1].set_ylabel("danger-point density (/km2)"); ax[1].legend(fontsize=8)
    plt.tight_layout(); plt.savefig(f"{OUT}/sasang_filter.png", dpi=120); plt.close()
    print(f"  → {OUT}/sasang_filter.png")

    # ---- 규칙·per-accident CSV ----
    pd.DataFrame([
        {"rule": "maxcum>=27mm", "recall_obs_%": 100, "control_%": round(cfp_rc, 0), "AUC": round(auc(a_rc, c_rc), 2)},
        {"rule": "maxcum>=27 AND dngdensity>=21.2", "recall_obs_%": 100, "control_%": round(cfp_comb, 0), "AUC": ""},
    ]).to_csv(f"{OUT}/sasang_filter_rule.csv", index=False, encoding="utf-8-sig")
    rows = []
    for a, f in det + [(x, y) for x, y in undet]:
        rows.append({"no": a["no"], "date": M._fmt(a["date"]), "dong": a.get("dong", ""),
                     "n_buf": f["n_buf"], "n_elev": f["n_elev"], "n_danger": f["n_dng"],
                     "danger_density_km2": round(f["dens_dng"], 1), "max_cum_mm": round(f["maxrc"], 1),
                     "captured(maxcum>=27)": bool(f["maxrc"] >= t_rc) if f["n_buf"] else "관측이전-불가피"})
    pd.DataFrame(rows).to_csv(f"{OUT}/sasang_accident_features.csv", index=False, encoding="utf-8-sig")
    print(f"  → sasang_filter_rule.csv / sasang_accident_features.csv")


if __name__ == "__main__":
    main()
