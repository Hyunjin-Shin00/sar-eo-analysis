# -*- coding: utf-8 -*-
"""상시 운영 최적화 규칙 탐색. usage: leadtime_op.py
운영 AUC = AUC( max_t 결합점수(사고지점, t≤사고일) vs max_t 결합점수(배경지점, 전기간) ).
점수 = 12지표 as-of 백분위(풀링 배경분포 기준·방향 자동정렬) 결합(min/mean/max) + K에폭 지속필터.
탐색: 조건 3종{지역최적·통일(0.5/0.6/200)·T2k(0.3/0.7/400)} × 조합(단일+쌍+그리디3) × K{1,2,3}.
Youden 임계 → 탐지(ever)·배경발화(ever)·최초발화 리드. 시계열은 npz로 캐시(재개 가능)."""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json
from itertools import combinations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np
import sweep_config as C
import leadtime_backtest as LB
import leadtime_region_rule as RRU

DAYS = 365.25
FEATS = RRU.FEATS
CFGS = {"best": None, "uni": (0.5, 0.6, 200.0), "t2k": (0.3, 0.7, 400.0)}
KS = [1, 2, 3]
COMB = {"min": np.nanmin, "mean": np.nanmean, "max": np.nanmax}
SD = os.path.join(C.OUT_ROOT, "leadtime", "op_series")
os.makedirs(SD, exist_ok=True)


def get_series(region, tag):
    """(A리스트, B리스트) — 캐시 npz 재사용. A: dict(t,F,t_acc,gap,no,date,cause) / B: (t,F)."""
    fp = os.path.join(SD, f"{region}__{tag}.npz")
    if os.path.exists(fp):
        z = np.load(fp, allow_pickle=True)
        return list(z["A"]), list(z["B"])
    if tag == "best":
        bc = json.load(open(os.path.join(C.OUT_ROOT, region, "best_config.json")))
        coh, tcoh, R = bc["coh"], bc["tcoh"], float(bc["R"])
    else:
        coh, tcoh, R = CFGS[tag]
    A, B = RRU.build_series(region, coh, tcoh, R)
    np.savez_compressed(fp, A=np.array(A, object), B=np.array(B, object))
    print(f"  [시계열] {LB.KR[region]}/{tag} A:{len(A)} B:{len(B)}", flush=True)
    return A, B


def auc(p, n):
    p = np.asarray(p, float); n = np.asarray(n, float)
    p = p[np.isfinite(p)]; n = n[np.isfinite(n)]
    if not len(p) or not len(n):
        return np.nan
    return (np.sum(p[:, None] > n[None, :]) + 0.5 * np.sum(p[:, None] == n[None, :])) / (len(p) * len(n))


def prep_pct(A, B):
    """풀링 배경분포 기준 백분위 시계열 + 방향정렬 → (Ap[i]:T×12, Bp[j]:T×12)."""
    pool = [np.concatenate([b[1][f][np.isfinite(b[1][f])] for b in B]) if B else np.array([]) for f in range(len(FEATS))]
    srt = [np.sort(x) for x in pool]
    def pct_mat(Fm):
        out = np.full(Fm.T.shape, np.nan)
        for f in range(len(FEATS)):
            s = srt[f]
            if not len(s):
                continue
            v = Fm[f]
            fin = np.isfinite(v)
            pj = np.full(v.shape, np.nan)
            pj[fin] = (np.searchsorted(s, v[fin], "left") + np.searchsorted(s, v[fin], "right")) / (2 * len(s))
            out[:, f] = pj
        return out
    Ap = [pct_mat(a["F"]) for a in A]; Bp = [pct_mat(b[1]) for b in B]
    # 방향: 단일피처 운영AUC<0.5 → 뒤집기
    flips = np.zeros(len(FEATS), bool)
    for f in range(len(FEATS)):
        pa = [np.nanmax(m[:, f]) if np.isfinite(m[:, f]).any() else np.nan for m in Ap]
        pb = [np.nanmax(m[:, f]) if np.isfinite(m[:, f]).any() else np.nan for m in Bp]
        if auc(pa, pb) < 0.5:
            flips[f] = True
    for m in Ap + Bp:
        m[:, flips] = 1 - m[:, flips]
    return Ap, Bp, flips


def persist_max(s, K):
    """K에폭 지속필터 후 최대: max_t min(s[t-K+1..t]) (NaN=미충족)."""
    s = np.asarray(s, float)
    if K == 1 or len(s) < K:
        v = s[np.isfinite(s)]
        return float(np.max(v)) if len(v) else np.nan
    sw = np.lib.stride_tricks.sliding_window_view(s, K)
    with np.errstate(invalid="ignore"):
        m = np.min(sw, axis=1)       # NaN 포함 창은 NaN → 미충족
    m = m[np.isfinite(m)]
    return float(np.max(m)) if len(m) else np.nan


def op_search(Ap, Bp):
    """조합(단일+쌍+그리디3) × 결합 × K → 운영AUC 최대."""
    def scores(mats, fs, cn, K):
        out = []
        for m in mats:
            sub = m[:, fs]
            with np.errstate(all="ignore"):
                s = COMB[cn](sub, axis=1) if len(fs) > 1 else sub[:, 0]
            out.append(persist_max(s, K))
        return np.array(out, float)
    best = None
    def try_rule(fs, cn, K):
        nonlocal best
        pa = scores(Ap, fs, cn, K); pb = scores(Bp, fs, cn, K)
        a = auc(pa, pb)
        if np.isfinite(a) and (best is None or a > best["AUC"]):
            best = {"fs": list(fs), "comb": cn, "K": K, "AUC": float(a), "_pa": pa, "_pb": pb}
    for f in range(len(FEATS)):
        for K in KS:
            try_rule([f], "min", K)
    for f1, f2 in combinations(range(len(FEATS)), 2):
        for cn in COMB:
            for K in KS:
                try_rule([f1, f2], cn, K)
    base = dict(best)
    for f3 in range(len(FEATS)):
        if f3 in base["fs"]:
            continue
        for cn in COMB:
            for K in KS:
                try_rule(base["fs"] + [f3], cn, K)
    return best


def youden_op(pa, pb):
    p = pa[np.isfinite(pa)]; n = pb[np.isfinite(pb)]
    cand = np.unique(np.concatenate([p, n]))
    th = max(cand, key=lambda t: np.mean(p >= t) - np.mean(n >= t))
    return float(th), round(100 * float(np.mean(pa >= th) if len(pa) else 0), 1), \
        round(100 * float(np.mean(pb >= th) if len(pb) else 0), 1)


def leads_at(A, Ap, fs, cn, K, th):
    out = []
    for a, m in zip(A, Ap):
        sub = m[:, fs]
        with np.errstate(all="ignore"):
            s = COMB[cn](sub, axis=1) if len(fs) > 1 else sub[:, 0]
        fire = None
        if K == 1:
            ok = np.nan_to_num(s, nan=-1) >= th
            j = int(np.argmax(ok)) if ok.any() else -1
            fire = j if j >= 0 else None
        else:
            for j in range(K - 1, len(s)):
                w = s[j - K + 1: j + 1]
                if np.isfinite(w).all() and (w >= th).all():
                    fire = j; break
        out.append(round(float((a["t_acc"] - a["t"][fire]) * DAYS), 1) if fire is not None else None)
    return out


def main():
    res = {"per_region": {}, "cfg_summary": {}}
    for region in LB.REGS:
        rbest = None
        for tag in CFGS:
            A, B = get_series(region, tag)
            if not A or not B:
                continue
            Ap, Bp, flips = prep_pct(A, B)
            b = op_search(Ap, Bp)
            th, det, bg = youden_op(b["_pa"], b["_pb"])
            ld = leads_at(A, Ap, b["fs"], b["comb"], b["K"], th)
            d = [x for x in ld if x is not None]
            rec = {"cfg": tag, "features": [FEATS[f] for f in b["fs"]], "comb": b["comb"], "K": b["K"],
                   "flips": [FEATS[i] for i in range(len(FEATS)) if flips[i] and i in b["fs"]],
                   "opAUC": round(b["AUC"], 3), "th": round(th, 3), "det%": det, "bg_fire%": bg,
                   "n": len(A), "med_lead_d": (round(float(np.median(d)), 1) if d else None),
                   "le90": sum(1 for x in d if x <= 90)}
            res["per_region"].setdefault(region, {"cfgs": {}})["cfgs"][tag] = rec
            if rbest is None or rec["opAUC"] > rbest["opAUC"]:
                rbest = rec
        res["per_region"][region]["winner"] = rbest
        print(f"[운영] {LB.KR[region]:3s} {rbest['cfg']} {'+'.join(rbest['features'])} [{rbest['comb']}] K={rbest['K']} "
              f"opAUC={rbest['opAUC']} 탐지{rbest['det%']}%/배경{rbest['bg_fire%']}% med={rbest['med_lead_d']}d", flush=True)
    for tag in CFGS:
        vals = [res["per_region"][r]["cfgs"][tag]["opAUC"] for r in LB.REGS
                if tag in res["per_region"].get(r, {}).get("cfgs", {})]
        res["cfg_summary"][tag] = round(float(np.mean(vals)), 3) if vals else None
    res["cfg_summary"]["region_pick"] = round(float(np.mean(
        [res["per_region"][r]["winner"]["opAUC"] for r in LB.REGS])), 3)
    print("[조건별 평균 opAUC]", res["cfg_summary"], flush=True)
    json.dump(res, open(os.path.join(C.OUT_ROOT, "leadtime", "op_rule.json"), "w"),
              ensure_ascii=False, indent=2, default=str)
    print("→ out/leadtime/op_rule.json")


if __name__ == "__main__":
    main()
