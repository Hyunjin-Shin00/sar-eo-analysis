# -*- coding: utf-8 -*-
"""14절(+100점판): 1단=T2k '운영규칙' 게이트 → 2단 리드타임(오탐은 게이트 미통과 배경으로 참고만).
usage: leadtime_gate_op.py [--bg100]   (--bg100: 배경 100점 시계열 t2k100 사용)
사용자 지정 설계:
 · 1단 게이트 = 판별탭 'T2k 운영 규칙'(점수결합+지속K+점수임계, out/leadtime/op_rule.json cfgs.t2k)을
   각 에폭 as-of로 적용 → 위험구역 진입 시점. 통과한 사고만 2단 대상.
 · 2단 = 진입 이후 구간에서만 경보규칙(지표 1~3개 동시만족 K회 연속) 탐색.
   목적 = 중앙 리드 최소화, 제약 = 탐지율 ≥ 목표. 오탐은 목적함수 제외.
 · 참고 오탐 = 경보규칙을 '1단 미통과 + 사고에서 ≥400m' 배경점에 적용했을 때 발화 비율.
조건 T2k(coh0.3/tcoh0.7/R400/SBAS) 고정. 알람은 영상 에폭에서만 → 리드 ≥ gap.
출력: out/leadtime/gate_op.json"""
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
import leadtime_accident_only as AO
import leadtime_region_rule as RRU

DAYS = 365.25
FEATS = RRU.FEATS
FLOORS = AO.FLOORS
OPJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "op_rule.json")))["per_region"]


def gate_first_fire(mat, fs, comb, K, th):
    """백분위 행렬(T×12) → 운영규칙(점수 결합·K연속·≥th) 최초 성립 에폭(없으면 -1)."""
    sub = mat[:, fs]
    with np.errstate(all="ignore"):
        s = OP.COMB[comb](sub, axis=1) if len(fs) > 1 else sub[:, 0]
    ok = np.nan_to_num(s, nan=-1e18) >= th
    return O2.bool_first_fire(ok, K)


TAG = "t2k100" if "--bg100" in sys.argv else "t2k"
OUTNAME = "gate_op100.json" if "--bg100" in sys.argv else "gate_op.json"


def main():
    out = {"series_tag": TAG, "design": "1단=T2k 운영규칙 게이트 / 2단=리드 최소(탐지제약) / 참고오탐=게이트 미통과·≥400m 배경",
           "floors": FLOORS, "regions": {}}
    for region in LB.REGS:
        g = OPJ.get(region, {}).get("cfgs", {}).get("t2k")
        if not g:
            continue
        A, B = OP.get_series(region, TAG)
        if not A or not B:
            continue
        Ap, Bp, flips = OP.prep_pct(A, B)                      # 운영규칙과 동일한 백분위 기준
        fs = [FEATS.index(f) for f in g["features"]]
        K, comb = g["K"], g["comb"]
        # ⚠ op_rule.json의 th는 소수 3자리 반올림값 → 그대로 쓰면 경계 사고가 전부 탈락(양양 사례).
        #   운영규칙과 동일한 절차(persist_max + Youden)로 '정확한' 임계를 재계산해 사용.
        def _pmax(m):
            sub = m[:, fs]
            with np.errstate(all="ignore"):
                s = OP.COMB[comb](sub, axis=1) if len(fs) > 1 else sub[:, 0]
            return OP.persist_max(s, K)
        pa = np.array([_pmax(m) for m in Ap], float)
        pb = np.array([_pmax(m) for m in Bp], float)
        th, det_chk, bg_chk = OP.youden_op(pa, pb)
        if abs(det_chk - g["det%"]) > 0.15:
            print(f"  [경고] {LB.KR[region]} 게이트 재현 불일치: det {det_chk} vs 저장 {g['det%']}", flush=True)
        UA, UB = O2.make_units(A, B)
        # 1단: 사고(사고 이전 구간) · 배경(전 기간)
        ja = [gate_first_fire(m, fs, comb, K, th) for m in Ap]
        jb = [gate_first_fire(m, fs, comb, K, th) for m in Bp]
        UA_in = [{**u, "F": u["F"][:, j:], "t": u["t"][j:]}
                 for u, j in zip(UA, ja) if j >= 0 and j < u["F"].shape[1]]
        UB_out = [u for u, j in zip(UB, jb) if j < 0]           # ★ 게이트 미통과 배경만
        UB_in = [u for u, j in zip(UB, jb) if j >= 0]
        rec = {"kr": LB.KR[region],
               "gate_rule": {"features": [f for f in g["features"]], "comb": comb, "K": K,
                             "th": round(float(th), 5), "th_json": g["th"], "opAUC": g["opAUC"],
                             "gate_det%": det_chk, "gate_bg%": bg_chk},
               "gate_acc_pass": len(UA_in), "gate_acc_total": len(UA),
               "gate_bg_pass": len(UB_in), "gate_bg_fail": len(UB_out), "gate_bg_total": len(UB),
               "by_floor": {}}
        if len(UA_in) < 2:
            rec["note"] = "게이트 통과 사고 <2건 → 2단 탐색 불가"
            out["regions"][region] = rec
            print(f"[14절·{TAG}] {LB.KR[region]:3s} 게이트 사고 {len(UA_in)}/{len(UA)} → 표본부족", flush=True)
            continue
        ref = UB_out if UB_out else UB                          # 임계 격자·참고오탐 기준
        for fl in FLOORS:
            b = AO.search_acc(UA_in, ref, fl)
            if not b:
                continue
            fp_out = AO.bg_info(UB_out, b["conds"], b["K"]) if UB_out else (None, 0)
            fp_in = AO.bg_info(UB_in, b["conds"], b["K"]) if UB_in else (None, 0)
            leads = [{"no": u["no"], "date": u["date"], "cause": u["cause"], "gap_d": u["gap"], "lead_d": ld}
                     for u, ld in zip(UA_in, b["leads"])]
            viol = sum(1 for L in leads if L["lead_d"] is not None and L["gap_d"] is not None
                       and L["lead_d"] < L["gap_d"] - 0.01)
            d = [x for x in b["leads"] if x is not None]
            rec["by_floor"][f"{int(fl*100)}"] = {
                "rule": [(FEATS[f], round(t, 2)) for f, t in b["conds"]], "K": b["K"],
                "det%_gated": round(100 * b["det"], 1),
                "det%_overall": round(100 * b["det"] * len(UA_in) / max(1, len(UA)), 1),
                "med_lead_d": round(b["med"], 1), "min_lead_d": min(d, default=None),
                "le30": sum(1 for x in d if x <= 30), "le90": sum(1 for x in d if x <= 90),
                "fp_outside%": fp_out[0], "n_outside": fp_out[1],
                "fp_inside%": fp_in[0], "n_inside": fp_in[1],
                "gap_violations": viol, "leads": leads}
        out["regions"][region] = rec
        c = rec["by_floor"].get("80") or (list(rec["by_floor"].values())[0] if rec["by_floor"] else None)
        if c:
            print(f"[14절·{TAG}] {LB.KR[region]:3s} 게이트 사고{len(UA_in)}/{len(UA)}·배경 미통과{len(UB_out)}/{len(UB)} → "
                  f"탐지≥80%: K={c['K']} {' AND '.join(f'{f}≥{t}' for f, t in c['rule'])} | "
                  f"탐지 {c['det%_gated']}%(전체 {c['det%_overall']}%) 중앙리드 {c['med_lead_d']}d "
                  f"(최소 {c['min_lead_d']}d, ≤30d {c['le30']}) 참고오탐(미통과배경) {c['fp_outside%']}% gap위반{c['gap_violations']}", flush=True)
    json.dump(out, open(os.path.join(C.OUT_ROOT, "leadtime", OUTNAME), "w"),
              ensure_ascii=False, indent=2, default=str)
    print(f"→ out/leadtime/{OUTNAME}")


if __name__ == "__main__":
    main()
