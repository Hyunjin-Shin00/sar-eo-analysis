# -*- coding: utf-8 -*-
"""규칙기반 1·2단의 LOAO(사고 단위 일반화) 측정. usage: rule_loao.py

왜 필요한가
  현행 규칙기반 성능(발표자료 73.2%)은 **in-sample 값**이다. 2단 임계를 사고 분위수에서
  뽑았고 1단 Youden 임계도 그 사고를 포함해 정했다. 그래서 GBM 의 LOAO(16.9% / 71.8%)와
  직접 비교하면 불공정하다. 규칙기반도 같은 LOAO 로 재보아야 결판이 난다.

폴드마다 하는 일 (사고 i 를 완전히 제외)
  1) 1단 게이트 임계 th1 재적합 — Youden(사고 i 제외 vs 배경 전체)
  2) 게이트 진입 에폭 재계산 (남은 사고 + 배경)
  3) 2단 규칙 재탐색 — leadtime_last.search() 를 사고 i 제외 집합으로 (floor 0.80)
  4) 사고 i 에 그 게이트·규칙을 적용해 발화 여부·리드 산출
  게이트 탈락 사고는 미탐으로 계산(end-to-end).
비교 기준: ml_feasibility.py 와 동일하게 t2k100 풀 · 전체 71 사고 · 700 배경
읽기 전용 → out/verify/rule_loao.json
"""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np
import sweep_config as C
import leadtime_backtest as LB
import leadtime_op as OP
import leadtime_op2 as O2
import leadtime_last as LL

DAYS = 365.25
TAG = "t2k100"
FLOOR = 0.80


def gate_scores(region):
    """1단 점수 시계열 + persist_max 스칼라. (사고·배경)"""
    OPJ = json.load(open(os.path.join(C.OUT_ROOT, "leadtime", "op_rule.json")))["per_region"]
    g = OPJ[region]["cfgs"]["t2k"]
    A, B = OP.get_series(region, TAG)
    Ap, Bp, _ = OP.prep_pct(A, B)
    fs = [OP.FEATS.index(f) for f in g["features"]]
    K1, comb = g["K"], g["comb"]

    def sc(m):
        sub = m[:, fs]
        with np.errstate(all="ignore"):
            return OP.COMB[comb](sub, axis=1) if len(fs) > 1 else sub[:, 0]
    sa = [np.nan_to_num(sc(m), nan=-1e18) for m in Ap]
    sb = [np.nan_to_num(sc(m), nan=-1e18) for m in Bp]
    pa = np.array([OP.persist_max(sc(m), K1) for m in Ap], float)
    pb = np.array([OP.persist_max(sc(m), K1) for m in Bp], float)
    return A, B, sa, sb, pa, pb, K1, g


def units_from_gate(A, B, sa, sb, th1, K1, skip=None):
    """게이트 통과분만 진입 이후 구간으로 → 2단 탐색 입력 형태"""
    UA, UB = [], []
    for i, (a, s) in enumerate(zip(A, sa)):
        if i == skip:
            continue
        j = O2.bool_first_fire(s >= th1, K1)
        if 0 <= j < a["F"].shape[1]:
            UA.append(dict(X=LL.derive(a["F"][:, j:]), t=np.asarray(a["t"], float)[j:],
                           t_acc=float(a["t_acc"]), gap=a.get("gap_d"), date=a.get("date"),
                           cause=a.get("cause"), no=a.get("no")))
    for (t, F), s in zip(B, sb):
        j = O2.bool_first_fire(s >= th1, K1)
        if 0 <= j < F.shape[1]:
            UB.append(dict(X=LL.derive(F[:, j:]), t=np.asarray(t, float)[j:]))
    return UA, UB


def main():
    t00 = time.time()
    out = {"tag": TAG, "floor": FLOOR, "regions": {}}
    tot_leads, tot_n, tot_insample = [], 0, []
    for region in LB.REGS:
        kr = LB.KR[region]
        A, B, sa, sb, pa, pb, K1, g = gate_scores(region)
        n_all = len(A)
        print("\n■ %s (%s) 사고 %d · 배경 %d · 게이트 %s[%s] K=%d"
              % (kr, region, n_all, len(B), "+".join(g["features"]), g["comb"], K1), flush=True)

        # 참고: in-sample (전체 사고로 게이트·규칙 적합) — 기준선
        th1_full, _, _ = OP.youden_op(pa, pb)
        UA_f, UB_f = units_from_gate(A, B, sa, sb, th1_full, K1)
        res_f = LL.search(UA_f) if len(UA_f) >= 2 else None
        rule_f = res_f.get(FLOOR) if res_f else None
        ins_lead = []
        if rule_f:
            conds = [(int(f), float(t)) for f, t in rule_f["conds"]]
            for u in UA_f:
                k = LL.fire_idx(u["X"], conds, rule_f["K"])
                if k >= 0:
                    ins_lead.append(round(float((u["t_acc"] - u["t"][k]) * DAYS), 1))
        print("   in-sample: 게이트 %d/%d · 탐지 %d/%d (%.1f%%) · 리드중앙 %s일"
              % (len(UA_f), n_all, len(ins_lead), n_all, 100 * len(ins_lead) / n_all,
                 "-" if not ins_lead else "%.1f" % np.median(ins_lead)), flush=True)
        tot_insample += ins_lead

        # LOAO
        leads = []
        for i in range(n_all):
            # 1) 게이트 임계 재적합 (사고 i 제외)
            m = np.ones(n_all, bool); m[i] = False
            th1, _, _ = OP.youden_op(pa[m], pb)
            # 2) 2단 규칙 재탐색 (사고 i 제외)
            UA_i, _ = units_from_gate(A, B, sa, sb, th1, K1, skip=i)
            if len(UA_i) < 2:
                leads.append(None); continue
            res = LL.search(UA_i)
            r = res.get(FLOOR) or res.get(0.70)
            if not r:
                leads.append(None); continue
            conds = [(int(f), float(t)) for f, t in r["conds"]]
            # 3) 남긴 사고에 적용
            j = O2.bool_first_fire(sa[i] >= th1, K1)
            if not (0 <= j < A[i]["F"].shape[1]):
                leads.append(None)                       # 게이트 탈락 → 미탐
            else:
                X = LL.derive(A[i]["F"][:, j:]); t = np.asarray(A[i]["t"], float)[j:]
                k = LL.fire_idx(X, conds, r["K"])
                leads.append(round(float((A[i]["t_acc"] - t[k]) * DAYS), 1) if k >= 0 else None)
            print("     %2d/%2d %s → %s" % (i + 1, n_all, A[i].get("date"),
                  "미발화" if leads[-1] is None else "%.0f일" % leads[-1]), flush=True)
        d = [x for x in leads if x is not None]
        out["regions"][region] = dict(kr=kr, n_all=n_all,
                                      in_sample_det=len(ins_lead) / n_all,
                                      in_sample_med=float(np.median(ins_lead)) if ins_lead else None,
                                      loao_det=len(d) / n_all,
                                      loao_med=float(np.median(d)) if d else None,
                                      leads=leads)
        tot_leads += d; tot_n += n_all
        print("   ▶ LOAO 탐지 %.1f%% (%d/%d) · 리드중앙 %s일  [%.0f분]"
              % (100 * len(d) / n_all, len(d), n_all,
                 "-" if not d else "%.1f" % np.median(d), (time.time() - t00) / 60), flush=True)

    out["overall"] = dict(n_all=tot_n,
                          in_sample_det=len(tot_insample) / max(1, tot_n),
                          loao_det=len(tot_leads) / max(1, tot_n),
                          loao_med=float(np.median(tot_leads)) if tot_leads else None)
    print("\n■ 전체  in-sample %.1f%% (%d/%d)  ·  LOAO %.1f%% (%d/%d) 리드중앙 %s일"
          % (100 * out["overall"]["in_sample_det"], len(tot_insample), tot_n,
             100 * out["overall"]["loao_det"], len(tot_leads), tot_n,
             "-" if not tot_leads else "%.1f" % out["overall"]["loao_med"]))
    p = os.path.join(C.OUT_ROOT, "verify", "rule_loao.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1, default=str)
    print("→", p)


if __name__ == "__main__":
    main()
