# -*- coding: utf-8 -*-
"""조합별 지반침하 발생/미발생 판별 최적화. usage: discrim_eval.py <REGION>
사상(sasang_full_opt) 방법 일반화: 사고 300/200m 버퍼-최댓값 지표 vs 랜덤 비사고 배경.
자유도: 지표{누적1/2/full·속도·추세·역속도} × α{raw,/α} × 버퍼{200,300} × 범위{SBAS,PS+SBAS} × 12조합.
과적합: in-sample + LOO + 부트스트랩CI + 순열null(576설정 선택보정). 원인·규모 층화(사상 step4)."""
import os as _os
_CR = _os.environ.get("CLAB_ROOT") or _os.path.abspath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", ".."))   # 전달본 상대경로

import os
os.environ.pop("PYTHONPATH", None)
import sys, json, warnings
SINK = _CR + "/analysis/sinkhole"
for p in (SINK, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")
import indicators as ind
import make_unified_map as mum
import sweep_config as C
import swept_loader as SL
from cause_api_label import CAUSES, cause_of_reason        # 원인 5분류 단일 진실원

RNG = np.random.RandomState(11)
CUMS = {"cum_1yr": 1.0, "cum_2yr": 2.0, "cum_full": None}
# 지표(feature) 후보: (표시명 → feat dict 키)
FEATURES = ["cum_1yr", "cum_1yr_adj", "cum_2yr", "cum_2yr_adj", "cum_full", "cum_full_adj",
            "vel_raw", "vel_adj", "trend_dv", "iv_frac"]


# ---------------- 사고 로드(원인·규모 포함) ----------------
def load_accidents_full():
    df = pd.read_csv(C.ACC_CSV, dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    for c in ("lat", "lon", "sinkWidth", "sinkExtend", "sinkDepth"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df = df[df.lat.between(33, 39.5) & df.lon.between(124, 132)].copy()
    df["year"] = [mum._year_of(_fmt(d)) for d in df["sagoDate"]]
    df["vol"] = df["sinkWidth"] * df["sinkExtend"] * df["sinkDepth"]
    df["cause"] = [_cause(r) for _, r in df.iterrows()]
    return df


def _fmt(x):
    x = str(x).strip()
    return f"{x[0:4]}-{x[4:6]}-{x[6:8]}" if len(x) == 8 and x.isdigit() else x


def _cause(r):
    """원인 5분류(관로형·되메움형·굴착공사형·기타·미상) — API 실제 신고값 기준.

    2026-07-30 변경: 원인은 사고 CSV의 sagoReason(국토안전관리원 리스트 API 신고값)을
    그대로 매핑한다. 그 전까지 쓰던 복구방법(trMethod) 키워드 추정 + 수작업 원장
    (out/cause_relabel.csv)은 실제값과 AOI 93건 중 55건(59%) 불일치로 확인돼 폐기했다
    (파일은 이력용으로만 보존). 매핑 정의는 cause_api_label.REASON_TO_CAUSE가 단일 진실원.
    """
    return cause_of_reason(r.get("sagoReason"))


# ---------------- 지표 계산 ----------------
def cum_window(disp, years, asof, win):
    """indicators.risk_cumulative 의 창 매개변수화(전역 CONFIG 미변경). 침하=양수."""
    k = 3
    yend = asof if asof is not None else years[-1]
    if win is None:
        m = years <= yend
    else:
        m = (years <= yend) & (years >= yend - win)
        if m.sum() < 2 * k:
            m = years <= yend
    d = disp[:, m]; T = d.shape[1]
    if T == 0:
        return np.full(disp.shape[0], np.nan)
    kk = min(k, max(1, T // 2))
    start = np.nanmedian(d[:, :kk], axis=1); end = np.nanmedian(d[:, -kk:], axis=1)
    return -(end - start)


def feat(e, lat, lon, asof, R, kinds):
    """버퍼(R) 내 최댓값 지표(사상 feat 일반화). kinds=('SBAS',) 또는 ('PS','SBAS')."""
    ax, ay = SL.loaders._TR_M.transform([lon], [lat]); p = np.array([ax[0], ay[0]])
    rc = {c: [] for c in CUMS}; rv = []; al = []; dv = []; ivac = 0; ivn = 0
    for kind in kinds:
        k = e["kinds"].get(kind); t = k["tree"] if k else None
        if t is None:
            continue
        idx = np.array(t.query_ball_point(p, R), int)
        if not len(idx):
            continue
        yrs = k["years"]; m = ind.asof_mask(yrs, asof)
        if m.sum() < C.PRE_MIN_EPOCHS:
            continue
        disp = k["disp"][idx]; a = k["alpha"][idx]
        vel_asof = ind._seg_slope(yrs[m], disp[:, m].astype(float))
        rv += list(ind.risk_velocity(vel_asof)); al += list(a)
        for c, win in CUMS.items():
            rc[c] += list(cum_window(disp, yrs, asof, win))
        tr = ind.trend_grade(disp, yrs, asof); dv += list(tr["v_late"] - tr["v_early"])
        iv = mum.inverse_velocity(disp, yrs, asof)
        ivac += int(np.sum(iv["accel"])); ivn += len(idx)
    if not rv:
        return None
    a = np.array(al, float)
    def mx(v):
        v = np.asarray(v, float); v = v[np.isfinite(v)]
        return float(np.max(v)) if len(v) else np.nan
    def mxadj(v):
        v = np.asarray(v, float) / a; v = v[np.isfinite(v)]
        return float(np.max(v)) if len(v) else np.nan
    out = {"vel_raw": mx(rv), "vel_adj": mxadj(rv), "trend_dv": mx(dv),
           "iv_frac": float(ivac / max(1, ivn)), "alpha_min": float(np.nanmin(a)) if len(a) else np.nan,
           "n_buf": len(rv)}
    for c in CUMS:
        out[c] = mx(rc[c]); out[c + "_adj"] = mxadj(rc[c])
    return out


def auc(pos, neg):
    """Mann-Whitney AUC (사상 auc, NaN-safe). pos>neg 방향."""
    a = np.asarray(pos, float); c = np.asarray(neg, float)
    a = a[np.isfinite(a)]; c = c[np.isfinite(c)]
    if not len(a) or not len(c):
        return np.nan
    w = sum(np.sum(v > c) + 0.5 * np.sum(v == c) for v in a)
    return w / (len(a) * len(c))


# ---------------- 양성/음성 표본 ----------------
def collect(region, csv, use_ps):
    e = SL.build_bank_entry(region, csv, use_ps=use_ps)
    S, N, W, E = e["box"]
    acc = load_accidents_full()
    inbox = acc[acc.lat.between(S, N) & acc.lon.between(W, E) & acc.year.notna()].copy()
    n_inbox = len(inbox)
    n_preobs = int((inbox.year < e["y0"]).sum())
    n_postobs = int((inbox.year > e["y1"]).sum())
    # 사고 KDTree(배경이 사고와 안 겹치게)
    axr, ayr = SL.loaders._TR_M.transform(acc.lon.values, acc.lat.values)
    atree = cKDTree(np.c_[axr, ayr])
    kinds = ("PS", "SBAS") if use_ps else ("SBAS",)
    pos = {r: {} for r in C.BUFFERS}
    pos_cause = {r: [] for r in C.BUFFERS}     # feature 리스트와 정렬된 원인 라벨(원인별 AUC용)
    covr = {r: 0 for r in C.BUFFERS}
    pos_meta = []
    for _, a in inbox.iterrows():
        if a.year < e["y0"]:
            continue
        asof = min(a.year, e["y1"])
        got = False
        row = {"no": a.get("sagoNo"), "year": a.year, "cause": a.cause, "vol": a.vol,
               "d": a.sinkDepth, "post_obs": bool(a.year > e["y1"])}
        for R in C.BUFFERS:
            f = feat(e, a.lat, a.lon, asof, R, kinds)
            if f is not None:
                covr[R] += 1; got = True
                pos_cause[R].append(a.cause)
                for fk in FEATURES:
                    pos[R].setdefault(fk, []).append(f[fk])
                row.update({f"F_{int(R)}_{k}": f[k] for k in FEATURES})   # 버퍼별 저장(cause_magnitude에서 최적 R 선택)
        if got:
            pos_meta.append(row)
    # 음성: 랜덤 비사고 SBAS 점(≥R from 사고), asof=사고연도 표본
    sb = e["kinds"]["SBAS"]; Np = len(sb["lon"]); yrs_pool = inbox.year.dropna().values
    neg = {r: {} for r in C.BUFFERS}
    if Np and len(yrs_pool):
        target = min(C.N_NEG, Np)
        for R in C.BUFFERS:
            got = 0; tries = 0
            while got < target and tries < target * 40:
                tries += 1; j = RNG.randint(Np)
                pj = np.array([sb["x"][j], sb["y"][j]])
                if atree.query(pj)[0] < R:
                    continue
                f = feat(e, sb["lat"][j], sb["lon"][j], yrs_pool[RNG.randint(len(yrs_pool))], R, kinds)
                if f is None:
                    continue
                got += 1
                for fk in FEATURES:
                    neg[R].setdefault(fk, []).append(f[fk])
    n_sbas_box = Np
    return dict(pos=pos, neg=neg, pos_cause=pos_cause, covr=covr, n_inbox=n_inbox, n_preobs=n_preobs,
                n_postobs=n_postobs, n_sbas_box=n_sbas_box, pos_meta=pd.DataFrame(pos_meta),
                y0=e["y0"], y1=e["y1"])


# ---------------- 통계 ----------------
def loo_auc(pos, neg):
    pos = np.asarray(pos, float); pos = pos[np.isfinite(pos)]
    if len(pos) < 3:
        return auc(pos, neg)
    return float(np.mean([auc(np.delete(pos, i), neg) for i in range(len(pos))]))


def boot_ci(pos, neg, nb=500):
    pos = np.asarray(pos, float); pos = pos[np.isfinite(pos)]
    if len(pos) < 3:
        return (np.nan, np.nan)
    a = [auc(pos[RNG.randint(0, len(pos), len(pos))], neg) for _ in range(nb)]
    return (round(float(np.nanpercentile(a, 2.5)), 3), round(float(np.nanpercentile(a, 97.5)), 3))


def thresholds(pos, neg):
    pos = np.asarray(pos, float); pos = pos[np.isfinite(pos)]
    neg = np.asarray(neg, float); neg = neg[np.isfinite(neg)]
    if not len(pos) or not len(neg):
        return {}
    cand = np.unique(np.concatenate([pos, neg]))
    # Youden
    best = max(cand, key=lambda th: (np.mean(pos >= th) - np.mean(neg >= th)))
    cons = float(np.min(pos))                       # recall 100%
    prec_cand = [th for th in cand if np.mean(neg >= th) <= 0.05]
    prec = float(min(prec_cand)) if prec_cand else float(np.max(cand))
    def rc(th): return round(float(np.mean(pos >= th)) * 100, 1), round(float(np.mean(neg >= th)) * 100, 1)
    ry, fy = rc(best); rc_, fc = rc(cons); rp, fp = rc(prec)
    return {"youden": {"th": round(float(best), 2), "recall%": ry, "fp%": fy},
            "conservative": {"th": round(cons, 2), "recall%": rc_, "fp%": fc},
            "precise": {"th": round(prec, 2), "recall%": rp, "fp%": fp}}


# ---------------- 메인 ----------------
def main():
    region = sys.argv[1] if len(sys.argv) > 1 else None
    if region not in C.REGIONS:
        raise SystemExit(f"지역 지정 필요. 가능: {C.REGIONS}")
    od = os.path.join(C.OUT_ROOT, region); os.makedirs(od, exist_ok=True)
    print(f"■ 판별 평가: {region}", flush=True)
    rows = []; cache = {}
    for coh, tcoh in C.GRID:
        csv = os.path.join(C.sweep_dir(region, coh, tcoh), f"{region}_sbas_ps_v.csv")
        if not os.path.exists(csv):
            print(f"  [skip] 산출 없음 coh{coh}/tcoh{tcoh}"); continue
        for kname, kinds in C.KIND_SETS.items():
            D = collect(region, csv, use_ps=(kname == "PS_SBAS"))
            cache[(coh, tcoh, kname)] = D
            for R in C.BUFFERS:
                npos = len(D["pos"][R].get("cum_2yr", []))
                nneg = len(D["neg"][R].get("cum_2yr", []))
                cov = round(D["covr"][R] / max(1, D["n_inbox"] - D["n_preobs"]), 3)
                for fk in FEATURES:
                    P = D["pos"][R].get(fk, []); Ng = D["neg"][R].get(fk, [])
                    a_in = auc(P, Ng)
                    rows.append({"coh": coh, "tcoh": tcoh, "kinds": kname, "R": R, "feature": fk,
                                 "AUC_in": round(a_in, 3) if np.isfinite(a_in) else None,
                                 "n_pos": npos, "n_neg": nneg, "coverage": cov,
                                 "n_sbas_box": D["n_sbas_box"], "n_postobs": D["n_postobs"]})
        print(f"  coh{coh}/tcoh{tcoh} 완료 (SBAS점 {cache[(coh,tcoh,'SBAS')]['n_sbas_box']})", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(od, "sweep_summary.csv"), index=False, encoding="utf-8-sig")

    # ---- 최적 선정: coverage>=0.6 & n_pos>=3 중 AUC_in 최대 (LOO 병기) ----
    cand = df[(df.coverage >= 0.6) & (df.n_pos >= 3) & df.AUC_in.notna()].copy()
    if not len(cand):
        cand = df[df.AUC_in.notna()].copy()
    best = cand.sort_values("AUC_in", ascending=False).iloc[0].to_dict()
    bk = (best["coh"], best["tcoh"], best["kinds"]); R = best["R"]; fk = best["feature"]
    D = cache[bk]
    P = np.array(D["pos"][R][fk], float); Ng = np.array(D["neg"][R][fk], float)
    best_full = {**best,
                 "AUC_LOO": round(loo_auc(P, Ng), 3), "AUC_boot95": boot_ci(P, Ng),
                 "thresholds": thresholds(P, Ng),
                 "n_inbox": int(D["n_inbox"]), "n_preobs": int(D["n_preobs"]),
                 "n_postobs": int(D["n_postobs"]),
                 "obs_years": [round(D["y0"], 2), round(D["y1"], 2)],
                 "overfit_gap": round(float((best["AUC_in"] or 0) - loo_auc(P, Ng)), 3),
                 "small_sample_flag": bool(best["n_pos"] < 8)}
    # 순열 null(576설정 선택보정): 라벨 셔플 → 전 feature 최대 AUC 분포
    allP = {fk2: np.array(D["pos"][R].get(fk2, []), float) for fk2 in FEATURES}
    allN = {fk2: np.array(D["neg"][R].get(fk2, []), float) for fk2 in FEATURES}
    obs_max = max((auc(allP[f2], allN[f2]) for f2 in FEATURES if len(allP[f2]) and len(allN[f2])), default=np.nan)
    perm = []
    for _ in range(300):
        nullmax = 0.0
        for f2 in FEATURES:
            p2, n2 = allP[f2], allN[f2]
            if not (len(p2) and len(n2)):
                continue
            z = np.concatenate([p2, n2]); RNG.shuffle(z)
            nullmax = max(nullmax, auc(z[:len(p2)], z[len(p2):]))
        perm.append(nullmax)
    best_full["perm_null_max_p"] = round(float(np.mean(np.array(perm) >= obs_max)), 3) if np.isfinite(obs_max) else None
    # 원인별 정답 부분집합 AUC(최적 지표) — InSAR 탐지가능형(압밀) 분리도 정량화
    causes = np.array(D["pos_cause"][R])
    by_cause = {}
    for cz in sorted(set(causes.tolist())):
        Pc = P[causes == cz]
        by_cause[cz] = {"n": int(len(Pc)), "AUC": round(auc(Pc, Ng), 3) if len(Pc) else None}
    best_full["AUC_by_cause"] = by_cause
    cons = causes == "되메움형"
    best_full["AUC_consolidation_only"] = round(auc(P[cons], Ng), 3) if cons.any() else None
    best_full["n_consolidation"] = int(cons.sum())
    json.dump(best_full, open(os.path.join(od, "best_config.json"), "w"), ensure_ascii=False, indent=2, default=str)

    # ---- 그림: 발생 vs 배경 분포 + ROC ----
    _plot_occ_bg(P, Ng, region, fk, best, od)
    _plot_roc(cache, region, R, best, od)
    # ---- 원인·규모 층화(최적 조합·youden 임계) ----
    _cause_magnitude(D["pos_meta"], fk, best_full, region, od)

    print(f"\n■ 최적: coh{best['coh']}/tcoh{best['tcoh']} · {best['kinds']} · R{int(R)}m · {fk}")
    print(f"   AUC in={best['AUC_in']} LOO={best_full['AUC_LOO']} boot95={best_full['AUC_boot95']} "
          f"perm_p={best_full['perm_null_max_p']}  coverage={best['coverage']}  n_pos={best['n_pos']}")
    print(f"   임계치: {best_full['thresholds']}")
    print(f"   과적합gap={best_full['overfit_gap']} 소표본={best_full['small_sample_flag']}")
    print(f"→ {od}/ (sweep_summary.csv, best_config.json, *.png)")


def _plot_occ_bg(P, Ng, region, fk, best, od):
    fig, ax = plt.subplots(figsize=(6, 3.6))
    P = P[np.isfinite(P)]; Ng = Ng[np.isfinite(Ng)]
    b = np.histogram_bin_edges(np.concatenate([P, Ng]) if len(P) and len(Ng) else [0, 1], bins=25)
    if len(Ng): ax.hist(Ng, bins=b, density=True, alpha=0.55, color="#2166ac", label=f"background n={len(Ng)}")
    if len(P): ax.hist(P, bins=b, density=True, alpha=0.65, color="#c0392b", label=f"accident n={len(P)}")
    ax.set_title(f"{region} — {fk} (occ vs background)\ncoh{best['coh']}/tcoh{best['tcoh']} {best['kinds']} R{int(best['R'])} AUC={best['AUC_in']}")
    ax.set_xlabel(fk); ax.legend(fontsize=8); plt.tight_layout()
    plt.savefig(os.path.join(od, "occ_vs_background.png"), dpi=120); plt.close()


def _plot_roc(cache, region, R, best, od):
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    for kname in ("SBAS", "PS_SBAS"):
        D = cache.get((best["coh"], best["tcoh"], kname))
        if D is None: continue
        P = np.array(D["pos"][R].get(best["feature"], []), float); Ng = np.array(D["neg"][R].get(best["feature"], []), float)
        P = P[np.isfinite(P)]; Ng = Ng[np.isfinite(Ng)]
        if not len(P) or not len(Ng): continue
        th = np.unique(np.concatenate([P, Ng]))[::-1]
        tpr = [np.mean(P >= t) for t in th]; fpr = [np.mean(Ng >= t) for t in th]
        ax.plot([0] + fpr + [1], [0] + tpr + [1], marker=".", ms=3, label=f"{kname} AUC={auc(P,Ng):.3f}")
    ax.plot([0, 1], [0, 1], "k--", lw=0.7); ax.set_xlabel("FP rate"); ax.set_ylabel("recall")
    ax.set_title(f"{region} ROC ({best['feature']}, R{int(R)})"); ax.legend(fontsize=8); plt.tight_layout()
    plt.savefig(os.path.join(od, "roc_best.png"), dpi=120); plt.close()


def _cause_magnitude(pm, fk, best_full, region, od):
    col = f"F_{int(best_full['R'])}_{fk}"       # 최적 버퍼 R의 지표 컬럼
    if not len(pm) or col not in pm:
        return
    th = best_full["thresholds"].get("youden", {}).get("th")
    pm = pm.copy(); pm["alarmed"] = pm[col] >= th if th is not None else False
    rows = []
    for grp, sub in pm.groupby("cause"):
        rows.append({"strat": "cause", "group": grp, "n": len(sub),
                     "recall%": round(100 * sub["alarmed"].mean(), 1),
                     "median_feat": round(float(sub[col].median()), 1)})
    if pm["vol"].notna().sum() >= 6:
        try:
            pm["magtier"] = pd.qcut(pm["vol"], 3, labels=["소", "중", "대"])
        except ValueError:
            pm["magtier"] = pd.qcut(pm["vol"].rank(method="first"), 3, labels=["소", "중", "대"])
        for grp, sub in pm.groupby("magtier", observed=True):
            rows.append({"strat": "magnitude", "group": str(grp), "n": len(sub),
                         "recall%": round(100 * sub["alarmed"].mean(), 1),
                         "median_feat": round(float(sub[col].median()), 1)})
    pd.DataFrame(rows).to_csv(os.path.join(od, "cause_magnitude.csv"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
