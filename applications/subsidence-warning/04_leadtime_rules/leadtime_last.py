# -*- coding: utf-8 -*-
"""[최종절] 1단 통과 구역 전용 · 최단 리드 경보조건 탐색. usage: leadtime_last.py
설계(사용자 지정)
  · 1단 = T2k 운영규칙 게이트(기존과 동일, 변경 없음). 통과한 사고·배경만 2단 대상.
  · 2단 = 게이트 진입 이후 구간에서 **리드 중앙값 최소화**만 추구.
    제약은 탐지율 ≥ 목표 하나뿐. **게이트 미통과 배경 발화(FP_out)는 목적함수·제약에서 완전 제외.**
  · 오탐은 운영 관점 지표만 참고 병기: FP_in(통과 배경 중 발화) · FP_op(전체 배경 대비 1단∩2단).
후보 지표 72종 = base12(절대수준) + d1/d3/d6(증가량 36) + z3/z6(자기이력 표준화 24)
  → 누적량의 단조성(임계를 한 번 넘으면 계속 참 → 조기 발화)을 제거해 발화를 사고 쪽으로 당김.
임계 격자는 **사고 분포 분위수**(과적합 허용, 사용자 지시)에서 생성. K는 1~6 연속.
읽기 전용 → out/verify/last_section.json"""
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
import leadtime_op2 as O2
import leadtime_region_rule as RRU

DAYS = 365.25
BASE = RRU.FEATS
KS = [1, 2, 3, 4, 5, 6]
QS = list(np.linspace(0.05, 0.995, 20))
FLOORS = [0.70, 0.80, 0.90, 1.00]
OUTD = os.path.join(C.OUT_ROOT, "verify")
DW = (1, 3, 6)          # 증가량 창(에폭)
ZW = (3, 6)             # 표준화 창(에폭)
NAMES = list(BASE) + [f"{b}_d{m}" for m in DW for b in BASE] + [f"{b}_z{m}" for m in ZW for b in BASE]
KRF = {"사상": "부산 사상~하단", "양양": "강원 양양 낙산", "강동": "서울 강동 명일동",
       "광명": "경기 광명", "송도": "인천 송도", "서대문": "서울 서대문 연희동", "만덕": "부산 만덕~센텀"}


def derive(F):
    """F[12,T] → X[72,T]. 창 부족 구간·무한값은 -1e18(미충족)."""
    F = np.where(np.asarray(F, float) <= -1e17, np.nan, np.asarray(F, float))
    T = F.shape[1]
    parts = [F]
    for m in DW:
        D = np.full_like(F, np.nan)
        if T > m:
            D[:, m:] = F[:, m:] - F[:, :-m]
        parts.append(D)
    for m in ZW:
        Z = np.full_like(F, np.nan)
        for t in range(m, T):
            w = F[:, t - m:t]
            with np.errstate(all="ignore"):
                mu = np.nanmean(w, axis=1); sd = np.nanstd(w, axis=1)
            sd = np.where(np.isfinite(sd) & (sd > 1e-6), sd, np.nan)
            Z[:, t] = (F[:, t] - mu) / sd
        parts.append(Z)
    X = np.vstack(parts)
    return np.where(np.isfinite(X), X, -1e18)


def fire_idx(X, conds, K):
    ok = np.ones(X.shape[1], bool)
    for f, th in conds:
        ok &= (X[f] >= th)
    return O2.bool_first_fire(ok, K)


def evaluate(UA, conds, K):
    leads = []
    for u in UA:
        j = fire_idx(u["X"], conds, K)
        leads.append(round(float((u["t_acc"] - u["t"][j]) * DAYS), 1) if j >= 0 else None)
    d = [x for x in leads if x is not None]
    return (len(d) / max(1, len(UA)), leads,
            float(np.median(d)) if d else None)


def grid_acc(UA):
    """사고 분포 분위수 기반 임계 후보(지표별)."""
    G = []
    for f in range(len(NAMES)):
        v = np.concatenate([u["X"][f] for u in UA])
        v = v[v > -1e17]
        G.append(list(np.unique(np.quantile(v, QS))) if len(v) else [])
    return G


def search(UA):
    """후보 풀 1회 생성 → 모든 floor에 대해 '리드 중앙값 최소' 선택."""
    G = grid_acc(UA)
    best = {f: None for f in FLOORS}

    def offer(conds, K):
        det, leads, med = evaluate(UA, conds, K)
        if med is None:
            return 9e9
        for fl in FLOORS:
            if det >= fl - 1e-9:
                b = best[fl]
                if b is None or med < b["med"] - 1e-9 or (abs(med - b["med"]) < 1e-9 and det > b["det"]):
                    best[fl] = {"conds": [(int(f), float(t)) for f, t in conds], "K": K,
                                "det": det, "med": med, "leads": leads}
        return med if det >= FLOORS[0] - 1e-9 else 9e9
    singles = []
    for f in range(len(NAMES)):
        bm = 9e9
        for th in G[f]:
            for K in KS:
                bm = min(bm, offer([(f, th)], K))
        singles.append((bm, f))
    top = [f for m, f in sorted(singles) if m < 9e9][:10]
    for f1, f2 in combinations(top, 2):
        for t1 in G[f1]:
            for t2 in G[f2]:
                for K in KS:
                    offer([(f1, t1), (f2, t2)], K)
    for fl in FLOORS:                        # floor별 최적 쌍에서 3번째 그리디
        b = best[fl]
        if not b or len(b["conds"]) != 2:
            continue
        base = [tuple(c) for c in b["conds"]]
        for f3 in range(len(NAMES)):
            if f3 in [c[0] for c in base]:
                continue
            for t3 in G[f3]:
                for K in KS:
                    offer(base + [(f3, t3)], K)
    return best


def main():
    OPJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "op_rule.json")))["per_region"]
    GOJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "gate_op.json")))["regions"]
    out = {"design": "1단=T2k 운영규칙 게이트(불변) · 2단=리드 중앙값 최소화(제약: 탐지율만) · "
                     "게이트 미통과 배경 발화는 목적함수·제약에서 제외",
           "feature_set": NAMES, "K_range": KS, "floors": FLOORS, "regions": {}}
    for region in LB.REGS:
        kr = LB.KR[region]
        g = OPJ[region]["cfgs"]["t2k"]
        rec = {"kr": kr, "full": KRF.get(kr, kr), "gate_rule": g, "by_floor": {}}
        for bgtag, key in (("t2k", "bg30"), ("t2k100", "bg100")):
            A, B = OP.get_series(region, bgtag)
            Ap, Bp, _ = OP.prep_pct(A, B)
            fs = [BASE.index(f) for f in g["features"]]
            K1, comb = g["K"], g["comb"]

            def sc(m):
                sub = m[:, fs]
                with np.errstate(all="ignore"):
                    return OP.COMB[comb](sub, axis=1) if len(fs) > 1 else sub[:, 0]
            pa = np.array([OP.persist_max(sc(m), K1) for m in Ap], float)
            pb = np.array([OP.persist_max(sc(m), K1) for m in Bp], float)
            th1, _, _ = OP.youden_op(pa, pb)
            UA0, UB0 = O2.make_units(A, B)
            ja = [O2.bool_first_fire(np.nan_to_num(sc(m), nan=-1e18) >= th1, K1) for m in Ap]
            jb = [O2.bool_first_fire(np.nan_to_num(sc(m), nan=-1e18) >= th1, K1) for m in Bp]
            UA = [{**u, "X": derive(u["F"][:, j:]), "t": u["t"][j:]}
                  for u, j in zip(UA0, ja) if 0 <= j < u["F"].shape[1]]
            IN = [derive(u["F"][:, j:]) for u, j in zip(UB0, jb) if 0 <= j < u["F"].shape[1]]
            OUTB = [derive(u["F"]) for u, j in zip(UB0, jb) if j < 0]
            nbg = len(UB0)
            if key == "bg30":
                if len(UA) < 2:
                    rec["note"] = "게이트 통과 사고 <2건 → 탐색 불가"
                    break
                res = search(UA)                      # 탐색은 배경과 무관 → 1회만
                rec["n_gate_acc"] = len(UA)
                cur = GOJ[[k for k in GOJ if GOJ[k]["kr"] == kr][0]]["by_floor"]
                for fl in FLOORS:
                    fk = f"{int(fl*100)}"
                    b = res[fl]
                    rec["by_floor"][fk] = None if b is None else {
                        "rule": [(NAMES[f], round(t, 3)) for f, t in b["conds"]], "K": b["K"],
                        "det%": round(100 * b["det"], 1), "med_lead_d": round(b["med"], 1),
                        "leads": [{"date": u["date"], "cause": u["cause"], "gap_d": u["gap"], "lead_d": x}
                                  for u, x in zip(UA, b["leads"])],
                        "current_med_lead_d": (cur.get(fk) or {}).get("med_lead_d")}
                    if b:
                        d = [x for x in b["leads"] if x is not None]
                        rec["by_floor"][fk].update({
                            "min_lead_d": min(d), "max_lead_d": max(d),
                            "p90_lead_d": round(float(np.percentile(d, 90)), 1),
                            "le30": sum(1 for x in d if x <= 30), "le90": sum(1 for x in d if x <= 90),
                            "le180": sum(1 for x in d if x <= 180),
                            "gap_viol": sum(1 for u, x in zip(UA, b["leads"])
                                            if x is not None and u["gap"] is not None and x < u["gap"] - 0.01)})
            # 배경 지표(30·100점 각각)
            for fl in FLOORS:
                fk = f"{int(fl*100)}"
                r = rec["by_floor"].get(fk)
                if not r:
                    continue
                conds = [(NAMES.index(f), float(t)) for f, t in r["rule"]]
                n_in = sum(1 for X in IN if fire_idx(X, conds, r["K"]) >= 0)
                n_out = sum(1 for X in OUTB if fire_idx(X, conds, r["K"]) >= 0)
                r[key] = {"n_bg": nbg, "n_pass1": len(IN),
                          "FP_in%": round(100 * n_in / max(1, len(IN)), 1) if IN else None,
                          "FP_op%": round(100 * n_in / max(1, nbg), 1),
                          "FP_out%": round(100 * n_out / max(1, len(OUTB)), 1) if OUTB else None}
        out["regions"][region] = rec
        r80 = rec["by_floor"].get("80")
        if r80:
            print(f"[{kr}] ≥80%: 현행 {r80['current_med_lead_d']}일 → **{r80['med_lead_d']}일** "
                  f"(최단 {r80['min_lead_d']} · ≤30d {r80['le30']} ≤90d {r80['le90']}) "
                  f"K={r80['K']} {' AND '.join(f'{f}≥{t}' for f, t in r80['rule'])} "
                  f"| 탐지 {r80['det%']}% · FP_op {r80.get('bg100',{}).get('FP_op%')}%(100점) · gap위반 {r80['gap_viol']}", flush=True)
    p = os.path.join(OUTD, "last_section.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=2, default=str)
    print("\n→", p)


if __name__ == "__main__":
    main()
