# -*- coding: utf-8 -*-
"""지역 단일규칙 리드타임(현실화). usage: leadtime_region_rule.py
사건별 맞춤규칙 폐기 → 지역당 규칙 1개(지표 ≤3 AND + 고정 임계)를 전 기간 워크포워드 적용.
알람은 영상 획득 에폭에서만 발화 → 리드 ≥ (사고일−마지막 사전영상일) 자동 보장.
목표: 탐지 최대 → (중앙 리드, 배경발화) 파레토 무릎점(med/180d + bg%/30 최소).
A안=지역별 최적 coh/tcoh/R + 지표·임계 자유 / B안=통일 coh0.5/tcoh0.6/R200 + 공통 지표조합(임계만 지역별)."""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json
from itertools import combinations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np, pandas as pd
import sweep_config as C
import discrim_eval as E
import swept_loader as SL
import leadtime_backtest as LB
import leadtime_overfit as LO

DAYS = 365.25
SAMEDAY_EPS = 0.5 / 365.25      # 반일: 사고 당일 영상 배제용
FEATS = LO.FEATS            # 12지표(누적3±α·속도2±α·최근1년±α·가속·거칠기 아님 — LO 정의) 사용
NBG = 30
UNI = (0.5, 0.6, 200.0)


def build_series(region, coh, tcoh, R):
    """지역의 (사고별·배경별) 워크포워드 12지표 시계열."""
    csv = os.path.join(C.sweep_dir(region, coh, tcoh), f"{region}_sbas_ps_v.csv")
    e = SL.build_bank_entry(region, csv, use_ps=False)
    sb = e["kinds"]["SBAS"]; yrs = sb["years"]; tree = sb["tree"]
    S, N, W, Ebox = e["box"]
    acc = E.load_accidents_full()
    inbox = acc[acc.lat.between(S, N) & acc.lon.between(W, Ebox) & acc.year.notna()]
    inbox = inbox[(inbox.year >= e["y0"]) & (inbox.year <= e["y1"])]
    from scipy.spatial import cKDTree
    axr, ayr = SL.loaders._TR_M.transform(acc.lon.values, acc.lat.values)
    atree = cKDTree(np.c_[axr, ayr])
    A = []
    for _, a in inbox.iterrows():
        t_acc = float(a.year)
        ax, ay = SL.loaders._TR_M.transform([a.lon], [a.lat])
        idx = np.array(tree.query_ball_point([ax[0], ay[0]], R), int)
        if not len(idx) or (yrs <= t_acc).sum() < LB.MIN_EP:
            continue
        # 사고 당일 영상 제외(시각 정보 없어 사고 전/후 불명) → 직전 획득일까지만 사용
        t, Fm = LO.ff_series(sb["disp"][idx], yrs, sb["alpha"][idx], t_acc - SAMEDAY_EPS)
        if not len(t):
            continue
        pre = yrs[yrs < t_acc - SAMEDAY_EPS]
        A.append({"no": str(a.get("sagoNo")), "date": E._fmt(a.sagoDate), "cause": a.cause,
                  "t_acc": t_acc, "gap_d": round(float((t_acc - pre[-1]) * DAYS), 1),
                  "t": t, "F": Fm})
    RNG = np.random.RandomState(23)
    B = []
    got = tries = 0
    while got < NBG and tries < NBG * 60 and len(sb["lon"]):
        tries += 1; j = RNG.randint(len(sb["lon"]))
        if atree.query([sb["x"][j], sb["y"][j]])[0] < R:
            continue
        idx = np.array(tree.query_ball_point([sb["x"][j], sb["y"][j]], R), int)
        if not len(idx):
            continue
        t, Fm = LO.ff_series(sb["disp"][idx], yrs, sb["alpha"][idx], yrs[-1])
        B.append((t, Fm)); got += 1
    return A, B


def eval_rule(A, B, fs, ths):
    """규칙(AND: F[f]≥th 전부) → (leads[또는 None], bg_fire%)."""
    leads = []
    for a in A:
        ok = np.ones(a["F"].shape[1], bool)
        for f, th in zip(fs, ths):
            with np.errstate(invalid="ignore"):
                ok &= (np.nan_to_num(a["F"][f], nan=-1e18) >= th)
        j = np.argmax(ok) if ok.any() else -1
        leads.append(round(float((a["t_acc"] - a["t"][j]) * DAYS), 1) if j >= 0 else None)
    fired = 0
    for (t, Fm) in B:
        ok = np.ones(Fm.shape[1], bool)
        for f, th in zip(fs, ths):
            with np.errstate(invalid="ignore"):
                ok &= (np.nan_to_num(Fm[f], nan=-1e18) >= th)
        fired += int(ok.any())
    bg = 100.0 * fired / max(1, len(B))
    return leads, bg


def metrics(leads, bg):
    d = [x for x in leads if x is not None]
    det = 100.0 * len(d) / max(1, len(leads))
    med = float(np.median(d)) if d else None
    score = (med / 180.0 if med is not None else 99) + bg / 30.0 + (100 - det) * 0.1
    return det, med, score


def grid_for(A, f, nq):
    v = np.concatenate([a["F"][f][np.isfinite(a["F"][f])] for a in A]) if A else np.array([])
    if not len(v):
        return []
    return list(np.unique(np.quantile(v, np.linspace(0.30, 0.995, nq))))


def search_region(A, B):
    """단일(24레벨) + 쌍(12×12) + 그리디 3번째. det 최대 우선 → knee 점수 최소."""
    best = None
    cand_top = []
    for f in range(len(FEATS)):
        for th in grid_for(A, f, 24):
            leads, bg = eval_rule(A, B, [f], [th])
            det, med, sc = metrics(leads, bg)
            rec = {"fs": [f], "ths": [float(th)], "det": det, "med": med, "bg": bg, "score": sc, "leads": leads}
            cand_top.append(rec)
            if best is None or (det, -sc) > (best["det"], -best["score"]):
                best = rec
    for f1, f2 in combinations(range(len(FEATS)), 2):
        g1, g2 = grid_for(A, f1, 12), grid_for(A, f2, 12)
        for t1 in g1:
            for t2 in g2:
                leads, bg = eval_rule(A, B, [f1, f2], [t1, t2])
                det, med, sc = metrics(leads, bg)
                if best is None or (det, -sc) > (best["det"], -best["score"]):
                    best = {"fs": [f1, f2], "ths": [float(t1), float(t2)], "det": det, "med": med,
                            "bg": bg, "score": sc, "leads": leads}
    base = dict(best)
    if len(base["fs"]) == 2:
        for f3 in range(len(FEATS)):
            if f3 in base["fs"]:
                continue
            for t3 in grid_for(A, f3, 12):
                fs = base["fs"] + [f3]; ths = base["ths"] + [float(t3)]
                leads, bg = eval_rule(A, B, fs, ths)
                det, med, sc = metrics(leads, bg)
                if (det, -sc) > (best["det"], -best["score"]):
                    best = {"fs": fs, "ths": ths, "det": det, "med": med, "bg": bg, "score": sc, "leads": leads}
    return best


def search_common(SER):
    """B안: 공통 지표조합(단일+쌍), 임계는 지역별 그리드 → 지역 knee점수 평균 최소."""
    combos = [[f] for f in range(len(FEATS))] + [list(c) for c in combinations(range(len(FEATS)), 2)]
    best = None
    for fs in combos:
        tot = 0; per = {}
        ok = True
        for region, (A, B) in SER.items():
            bb = None
            grids = [grid_for(A, f, 12) for f in fs]
            if any(not g for g in grids):
                ok = False; break
            import itertools
            for ths in itertools.product(*grids):
                leads, bg = eval_rule(A, B, fs, list(ths))
                det, med, sc = metrics(leads, bg)
                if bb is None or (det, -sc) > (bb["det"], -bb["score"]):
                    bb = {"ths": [float(x) for x in ths], "det": det, "med": med, "bg": bg,
                          "score": sc, "leads": leads}
            tot += bb["score"]; per[region] = bb
        if not ok:
            continue
        if best is None or tot < best["tot"]:
            best = {"fs": fs, "tot": tot, "per": per}
    return best


def main():
    SER_A, SER_B = {}, {}
    for region in LB.REGS:
        bc = json.load(open(os.path.join(C.OUT_ROOT, region, "best_config.json")))
        SER_A[region] = build_series(region, bc["coh"], bc["tcoh"], float(bc["R"]))
        SER_B[region] = build_series(region, *UNI)
        print(f"[시계열] {LB.KR[region]} A:{len(SER_A[region][0])}사고 B:{len(SER_B[region][0])}사고", flush=True)

    out = {"A_free": {}, "B_unified": {}, "feat_names": FEATS}
    rows = []
    for region in LB.REGS:
        A, B = SER_A[region]
        r = search_region(A, B)
        out["A_free"][region] = {"kr": LB.KR[region],
                                 "rule": [(FEATS[f], round(t, 2)) for f, t in zip(r["fs"], r["ths"])],
                                 "det%": round(r["det"], 1), "med_lead_d": r["med"], "bg_fire%": round(r["bg"], 1),
                                 "n": len(A)}
        for a, ld in zip(A, r["leads"]):
            rows.append({"region": LB.KR[region], "no": a["no"], "date": a["date"], "cause": a["cause"],
                         "gap_d": a["gap_d"], "leadA_d": ld})
        d = [x for x in r["leads"] if x is not None]
        print(f"[A안] {LB.KR[region]:3s} 규칙 {out['A_free'][region]['rule']} 탐지{r['det']:.0f}% "
              f"med={r['med']}d ≤90d:{sum(1 for x in d if x<=90)} bg={r['bg']:.0f}%", flush=True)

    cb = search_common(SER_B)
    out["B_unified"]["features"] = [FEATS[f] for f in cb["fs"]]
    dfA = pd.DataFrame(rows)
    for region, bb in cb["per"].items():
        A, B = SER_B[region]
        out["B_unified"][region] = {"kr": LB.KR[region], "ths": [round(t, 2) for t in bb["ths"]],
                                    "det%": round(bb["det"], 1), "med_lead_d": bb["med"],
                                    "bg_fire%": round(bb["bg"], 1), "n": len(A)}
        m = {(a["no"]): ld for a, ld in zip(A, bb["leads"])}
        sel = dfA.region == LB.KR[region]
        dfA.loc[sel, "leadB_d"] = dfA.loc[sel, "no"].map(m)
        print(f"[B안] {LB.KR[region]:3s} 임계 {bb['ths']} 탐지{bb['det']:.0f}% med={bb['med']}d bg={bb['bg']:.0f}%", flush=True)
    print(f"[B안 공통조합] {out['B_unified']['features']}", flush=True)

    od = os.path.join(C.OUT_ROOT, "leadtime")
    dfA.to_csv(os.path.join(od, "region_rule_leads.csv"), index=False, encoding="utf-8-sig")
    json.dump(out, open(os.path.join(od, "region_rule.json"), "w"), ensure_ascii=False, indent=2)
    # 현실성 검증: 리드 ≥ gap
    v = dfA.dropna(subset=["leadA_d"])
    bad = int((v.leadA_d < v.gap_d - 0.01).sum())
    print(f"검증: 리드<gap 위반 {bad}건 (0이어야 정상)")
    print(f"→ {od}/region_rule.json, region_rule_leads.csv")


if __name__ == "__main__":
    main()
