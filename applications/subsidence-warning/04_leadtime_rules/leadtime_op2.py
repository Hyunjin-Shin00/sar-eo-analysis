# -*- coding: utf-8 -*-
"""리드타임 최소화 + 배경발화 억제 규칙 재탐색(지역별 맞춤·사건별 규칙 금지). usage: leadtime_op2.py
규칙 = 「지표 1~3개가 각자 임계 이상을 <b>동시에</b> 만족한 상태가 K에폭 연속 지속」 → 그 시점 발화.
  (K=1이면 단순 동시만족, K≥2면 '동시 만족이 K회 연속' = 사용자 요청한 지속/동시-기간 조건)
목적: 탐지율 ≥ DET_FLOOR 하에서 J = 중앙리드(년) + W·배경발화율 최소화(리드 짧게·배경 낮게).
조건 3종(지역최적·통일·T2k) 전부 탐색해 지역별 최선 선택. 파레토 프런티어도 저장.
현실성: 알람은 영상 에폭에서만 → 리드 ≥ gap(마지막 사전영상~사고) 자동 보장(검증 출력)."""
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
import leadtime_op as OP
import leadtime_region_rule as RRU

DAYS = 365.25
FEATS = RRU.FEATS
KS = [1, 2, 3, 4]
DET_FLOOR = 0.70
W_BG = 2.0
QS_SINGLE = [0.50, 0.70, 0.80, 0.875, 0.925, 0.95, 0.97, 0.98, 0.99, 0.995, 0.998, 0.999]
QS_PAIR = [0.70, 0.85, 0.925, 0.95, 0.98, 0.99, 0.995, 0.999]


def bool_first_fire(Bmat, K):
    """Bmat: bool[T] → K연속 최초 성립 인덱스(없으면 -1)."""
    if K == 1:
        i = np.argmax(Bmat) if Bmat.any() else -1
        return int(i) if Bmat.any() else -1
    if len(Bmat) < K:
        return -1
    sw = np.lib.stride_tricks.sliding_window_view(Bmat, K).all(axis=1)
    if not sw.any():
        return -1
    return int(np.argmax(sw)) + K - 1


def make_units(A, B):
    """A: 사고 [(F[12,T], t, t_acc, gap, meta)], B: 배경 [(F, t)]. NaN → -inf 처리."""
    UA, UB = [], []
    for a in A:
        F = np.where(np.isfinite(a["F"]), a["F"], -1e18)
        UA.append({"F": F, "t": a["t"], "t_acc": a["t_acc"], "gap": a["gap_d"],
                   "no": a["no"], "date": a["date"], "cause": a["cause"]})
    for (t, F) in B:
        UB.append({"F": np.where(np.isfinite(F), F, -1e18), "t": t})
    return UA, UB


def eval_rule(UA, UB, conds, K):
    leads = []
    for u in UA:
        ok = np.ones(u["F"].shape[1], bool)
        for f, th in conds:
            ok &= (u["F"][f] >= th)
        j = bool_first_fire(ok, K)
        leads.append(round(float((u["t_acc"] - u["t"][j]) * DAYS), 1) if j >= 0 else None)
    fired = 0
    for u in UB:
        ok = np.ones(u["F"].shape[1], bool)
        for f, th in conds:
            ok &= (u["F"][f] >= th)
        fired += int(bool_first_fire(ok, K) >= 0)
    d = [x for x in leads if x is not None]
    det = len(d) / max(1, len(UA))
    med = float(np.median(d)) if d else None
    bg = fired / max(1, len(UB))
    J = (med / DAYS if med is not None else 99) + W_BG * bg
    return {"conds": [(int(f), float(th)) for f, th in conds], "K": int(K),
            "det": det, "med": med, "bg": bg, "J": J, "leads": leads,
            "le90": sum(1 for x in d if x <= 90), "le30": sum(1 for x in d if x <= 30)}


def grids(UB, qs):
    """배경 분포 분위수 기반 임계 격자(피처별)."""
    out = {}
    for f in range(len(FEATS)):
        v = np.concatenate([u["F"][f] for u in UB])
        v = v[v > -1e17]
        out[f] = list(np.unique(np.quantile(v, qs))) if len(v) else []
    return out


def search(UA, UB):
    G1, G2 = grids(UB, QS_SINGLE), grids(UB, QS_PAIR)
    all_ok = []
    best = None
    def upd(r):
        nonlocal best
        if r["det"] >= DET_FLOOR:
            all_ok.append(r)
            if best is None or r["J"] < best["J"]:
                best = r
    singles = []
    for f in range(len(FEATS)):
        for th in G1[f]:
            for K in KS:
                r = eval_rule(UA, UB, [(f, th)], K)
                upd(r); singles.append((r["J"] if r["det"] >= DET_FLOOR else 999, f))
    top = [f for _, f in sorted(singles)[:8]]
    top = list(dict.fromkeys(top))[:6]
    for f1, f2 in combinations(top, 2):
        for t1 in G2[f1]:
            for t2 in G2[f2]:
                for K in KS:
                    upd(eval_rule(UA, UB, [(f1, t1), (f2, t2)], K))
    if best is not None and len(best["conds"]) == 2:
        base = best
        for f3 in range(len(FEATS)):
            if f3 in [c[0] for c in base["conds"]]:
                continue
            for t3 in G2[f3]:
                for K in KS:
                    upd(eval_rule(UA, UB, [tuple(c) for c in base["conds"]] + [(f3, t3)], K))
    # 파레토(리드↓·배경↓·탐지↑)
    pareto = []
    for r in all_ok:
        dom = any((o["med"] is not None and r["med"] is not None and o["med"] <= r["med"]
                   and o["bg"] <= r["bg"] and o["det"] >= r["det"]
                   and (o["med"] < r["med"] or o["bg"] < r["bg"] or o["det"] > r["det"]))
                  for o in all_ok)
        if not dom:
            pareto.append(r)
    pareto = sorted(pareto, key=lambda x: (x["med"] if x["med"] is not None else 9e9))[:8]
    # 고탐지(≥0.9) 대안
    hi = [r for r in all_ok if r["det"] >= 0.9]
    best_hi = min(hi, key=lambda x: x["J"]) if hi else None
    # 저오탐(배경≤10%) 중 리드 최단 대안
    lo = [r for r in all_ok if r["bg"] <= 0.10 and r["med"] is not None]
    best_lo = min(lo, key=lambda x: x["med"]) if lo else None
    return best, best_hi, pareto, len(all_ok), best_lo


def main():
    out = {"det_floor": DET_FLOOR, "w_bg": W_BG, "feats": FEATS, "per_region": {}}
    viol = 0
    for region in LB.REGS:
        rbest = None
        for tag in ["best", "uni", "t2k"]:
            A, B = OP.get_series(region, tag)
            if not A or not B:
                continue
            UA, UB = make_units(A, B)
            b, bhi, par, ncand, blo = search(UA, UB)
            if b is None:
                continue
            rec = {"cfg": tag, "rule": [(FEATS[f], round(th, 2)) for f, th in b["conds"]], "K": b["K"],
                   "det%": round(100 * b["det"], 1), "med_lead_d": b["med"], "bg_fire%": round(100 * b["bg"], 1),
                   "le90": b["le90"], "le30": b["le30"], "J": round(b["J"], 3), "n": len(UA),
                   "n_cand": ncand,
                   "leads": [{"no": u["no"], "date": u["date"], "cause": u["cause"], "gap_d": u["gap"],
                              "lead_d": ld} for u, ld in zip(UA, b["leads"])],
                   "alt_det90": (None if bhi is None else
                                 {"rule": [(FEATS[f], round(th, 2)) for f, th in bhi["conds"]], "K": bhi["K"],
                                  "det%": round(100 * bhi["det"], 1), "med_lead_d": bhi["med"],
                                  "bg_fire%": round(100 * bhi["bg"], 1)}),
                   "alt_lowbg": (None if blo is None else
                                 {"rule": [(FEATS[f], round(th, 2)) for f, th in blo["conds"]], "K": blo["K"],
                                  "det%": round(100 * blo["det"], 1), "med_lead_d": blo["med"],
                                  "bg_fire%": round(100 * blo["bg"], 1), "le90": blo["le90"]}),
                   "pareto": [{"rule": [(FEATS[f], round(th, 2)) for f, th in p["conds"]], "K": p["K"],
                               "det%": round(100 * p["det"], 1), "med_lead_d": p["med"],
                               "bg_fire%": round(100 * p["bg"], 1)} for p in par]}
            out["per_region"].setdefault(region, {"cfgs": {}})["cfgs"][tag] = {
                k: v for k, v in rec.items() if k not in ("leads", "pareto", "alt_det90", "alt_lowbg")}
            if rbest is None or rec["J"] < rbest["J"]:
                rbest = rec
        out["per_region"][region]["winner"] = rbest
        for L in rbest["leads"]:
            if L["lead_d"] is not None and L["gap_d"] is not None and L["lead_d"] < L["gap_d"] - 0.01:
                viol += 1
        print(f"[op2] {LB.KR[region]:3s} {rbest['cfg']:4s} K={rbest['K']} "
              f"{' AND '.join(f'{f}≥{t}' for f, t in rbest['rule'])} | 탐지{rbest['det%']}% "
              f"med={rbest['med_lead_d']}d ≤90d:{rbest['le90']} 배경{rbest['bg_fire%']}% (후보{rbest['n_cand']})", flush=True)
    out["gap_violations"] = viol
    print(f"현실성 검증: 리드<gap 위반 {viol}건")
    json.dump(out, open(os.path.join(C.OUT_ROOT, "leadtime", "op2_rule.json"), "w"),
              ensure_ascii=False, indent=2, default=str)
    print("→ out/leadtime/op2_rule.json")


if __name__ == "__main__":
    main()
