# -*- coding: utf-8 -*-
"""운영 오탐(1단∩2단) 재정의·계산. usage: fp_operational.py [--bg100]
사용자 지적: 14절의 '참고 오탐'은 **1단 미통과 배경**에 2단을 적용한 값이다.
그러나 실제 운영에서 2단은 **1단을 통과한 지점에만** 적용되므로 그 값은 운영 오탐이 아니다.
본 스크립트가 계산하는 3종
  ① FP_out  : 1단 미통과 배경에 2단 적용(= 현행 '참고 오탐') → 규칙의 선택력 진단용
  ② FP_in   : 1단 통과 배경 중 2단 발화 비율(조건부) → "위험구역 안에서 헛경보 날 확률"
  ③ FP_op   : (1단 통과 AND 2단 발화) / 전체 배경  ★ 운영 오탐 = 감시 100곳당 헛경보 수
공정성: 배경도 사고와 동일하게 **자기 게이트 진입 이후 구간**에만 2단을 적용한다.
대상 규칙 3종: 현행(gate_op ≥80%) · 오탐동결 개선 · 오탐무제약 개선(shorten_*)
읽기 전용 → out/verify/fp_operational{,_bg100}.json"""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np
import sweep_config as C
import leadtime_backtest as LB
import leadtime_op as OP
import leadtime_op2 as O2
import leadtime_shorten as SH

DAYS = 365.25
BG100 = "--bg100" in sys.argv
TAG = "t2k100" if BG100 else "t2k"
NAMES = SH.NAMES


def cp_ci(k, n, a=0.05):
    from scipy.stats import beta
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return round(100 * lo, 1), round(100 * hi, 1)


def fires(X, conds, K):
    ok = np.ones(X.shape[1], bool)
    for f, th in conds:
        ok &= (X[f] >= th)
    return O2.bool_first_fire(ok, K) >= 0


def main():
    OPJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "op_rule.json")))["per_region"]
    GOJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "gate_op.json")))["regions"]
    SHJ = json.load(open(os.path.join(SH.OUTD, "shorten_floor80.json")))["regions"]
    CAP = json.load(open(os.path.join(SH.OUTD, "shorten_fpcap_floor80.json")))["regions"]
    out = {"bg_tag": TAG, "definitions": {
        "FP_out": "1단 미통과 배경에 2단 적용(현행 '참고 오탐') — 진단용",
        "FP_in": "1단 통과 배경 중 2단 발화(조건부) — 위험구역 내 헛경보 확률",
        "FP_op": "(1단 통과 AND 2단 발화)/전체 배경 — ★운영 오탐(감시 100곳당 헛경보)"},
        "regions": {}}
    for region in LB.REGS:
        kr = LB.KR[region]
        g = OPJ[region]["cfgs"]["t2k"]
        A, B = OP.get_series(region, TAG)
        Ap, Bp, _ = OP.prep_pct(A, B)
        fs = [SH.BASE.index(f) for f in g["features"]]
        K1, comb = g["K"], g["comb"]

        def sc(m):
            sub = m[:, fs]
            with np.errstate(all="ignore"):
                return OP.COMB[comb](sub, axis=1) if len(fs) > 1 else sub[:, 0]
        pa = np.array([OP.persist_max(sc(m), K1) for m in Ap], float)
        pb = np.array([OP.persist_max(sc(m), K1) for m in Bp], float)
        th1, _, _ = OP.youden_op(pa, pb)
        UA0, UB0 = O2.make_units(A, B)
        jb = [O2.bool_first_fire(np.nan_to_num(sc(m), nan=-1e18) >= th1, K1) for m in Bp]
        nbg = len(UB0)
        # 배경: 게이트 진입 이후 구간(통과) / 전 기간(미통과)
        IN, OUTB = [], []
        for u, j in zip(UB0, jb):
            if j >= 0 and j < u["F"].shape[1]:
                IN.append(SH.derive(u["F"][:, j:]))
            elif j < 0:
                OUTB.append(SH.derive(u["F"]))
        cur = GOJ[[k for k in GOJ if GOJ[k]["kr"] == kr][0]]["by_floor"].get("80")
        rec = {"kr": kr, "n_bg": nbg, "n_pass1": len(IN), "n_fail1": len(OUTB),
               "gate_bg%": round(100 * len(IN) / max(1, nbg), 1), "rules": {}}
        cand = {}
        if cur:
            cand["현행"] = ([(SH.BASE.index(f), float(t)) for f, t in cur["rule"]], int(cur["K"]),
                          cur["med_lead_d"], cur["det%_gated"])
        c = (CAP.get(region) or {}).get("capped")
        if c:
            cand["오탐동결"] = ([(NAMES.index(f), float(t)) for f, t in c["rule"]], int(c["K"]),
                             c["med_lead_d"], c["det%"])
        e = (SHJ.get(region) or {}).get("extended48")
        if e:
            cand["오탐무제약"] = ([(NAMES.index(f), float(t)) for f, t in e["rule"]], int(e["K"]),
                              e["med_lead_d"], e["det%"])
        for lab, (conds, K, med, det) in cand.items():
            n_in = sum(1 for X in IN if fires(X, conds, K))
            n_out = sum(1 for X in OUTB if fires(X, conds, K))
            rec["rules"][lab] = {
                "med_lead_d": med, "det%": det, "K": K,
                "FP_out%": round(100 * n_out / max(1, len(OUTB)), 1), "FP_out_k": n_out, "FP_out_n": len(OUTB),
                "FP_in%": round(100 * n_in / max(1, len(IN)), 1) if IN else None, "FP_in_k": n_in, "FP_in_n": len(IN),
                "FP_op%": round(100 * n_in / max(1, nbg), 1), "FP_op_k": n_in, "FP_op_n": nbg,
                "FP_op_CI%": cp_ci(n_in, nbg)}
        out["regions"][region] = rec
        s = " | ".join(f"{lab} 리드{v['med_lead_d']:.0f}d FPout {v['FP_out%']}% FPin {v['FP_in%']}% "
                       f"**FPop {v['FP_op%']}%({v['FP_op_k']}/{v['FP_op_n']})**"
                       for lab, v in rec["rules"].items())
        print(f"[{kr}] 배경 {nbg}점 중 1단통과 {len(IN)}({rec['gate_bg%']}%)\n    {s}", flush=True)
    p = os.path.join(SH.OUTD, f"fp_operational{'_bg100' if BG100 else ''}.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=2, default=str)
    print("\n→", p)


if __name__ == "__main__":
    main()
