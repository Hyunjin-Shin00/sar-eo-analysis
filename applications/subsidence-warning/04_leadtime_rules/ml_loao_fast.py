# -*- coding: utf-8 -*-
"""LOAO(사고 단위 일반화) - 점수 캐싱판. usage: ml_loao_fast.py

원래 ml_feasibility.py 의 LOAO 는 임계탐색마다 predict_proba 를 27만 번 호출해
폴드당 9분(전체 11시간)이 걸렸다. 모델 하나당 유닛 점수를 **한 번만** 계산해 캐시하고
임계·K 스윕은 캐시 배열 위에서만 하면 같은 결과를 100배 빠르게 얻는다.

LOAO 의 의미: 풀링 모델이 해당 사고만 빼고 학습한다(같은 지역의 다른 사고는 봄).
  = "감시 중인 지역에 과거 사고 이력이 있을 때, 새로 발생할 사고를 맞출 수 있는가"
  → 실제 운용 상황과 가장 가까운 검증이다.
읽기 전용 → out/verify/ml_loao.json
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
import leadtime_op2 as O2
import ml_feasibility as MF

DAYS = 365.25
H = 180
KS = [1, 2, 3, 4, 5, 6]
QS = np.linspace(0.50, 0.9995, 60)
FLOOR = 0.80


def cache_scores(mdl, D):
    """유닛별 점수 1회 계산 → {('A'|'B', region, idx): score[T]}"""
    S = {}
    for region, d in D.items():
        for i, u in enumerate(d["UA"]):
            S[("A", region, i)] = np.nan_to_num(
                MF.score_of(mdl, u["X"].T.astype(np.float32)), nan=0.0)
        for j, u in enumerate(d["UB"]):
            S[("B", region, j)] = np.nan_to_num(
                MF.score_of(mdl, u["X"].T.astype(np.float32)), nan=0.0)
    return S


def eval_cached(S, D, th, K, drop=None):
    """캐시 위에서만 평가. drop 유닛은 학습분 평가에서 제외."""
    leads, bg = [], []
    for region, d in D.items():
        for i, u in enumerate(d["UA"]):
            k = ("A", region, i)
            if k == drop:
                continue
            j = O2.bool_first_fire(S[k] >= th, K)
            leads.append(round(float((u["t_acc"] - u["t"][j]) * DAYS), 1) if j >= 0 else None)
        for jx in range(len(d["UB"])):
            bg.append(O2.bool_first_fire(S[("B", region, jx)] >= th, K) >= 0)
    dd = [x for x in leads if x is not None]
    return (len(dd) / max(1, len(leads)), float(np.median(dd)) if dd else None,
            float(np.mean(bg)) if bg else None)


def pick_th_cached(S, D, drop):
    """학습분(drop 제외)에서 탐지>=FLOOR 제약 하 리드 중앙값 최소."""
    pool = np.concatenate([S[k] for k in S if k[0] == "A" and k != drop])
    cand = np.unique(np.quantile(pool, QS))
    best = None
    for K in KS:
        for th in cand:
            det, med, fp = eval_cached(S, D, th, K, drop=drop)
            if med is None or det < FLOOR - 1e-9:
                continue
            key = (med, -det)
            if best is None or key < best[0]:
                best = (key, float(th), K)
    return (best[1], best[2]) if best else (float(np.median(cand)), 1)


def main():
    t00 = time.time()
    print("■ 자료 구성")
    D = MF.build()
    X, y, rg, kd, uid = MF.rows(D, H)
    print("  %s · 양성 %d\n" % (X.shape, int(y.sum())), flush=True)

    out = {"horizon_d": H, "floor": FLOOR, "regions": {}}
    tot_leads, tot_n = [], 0
    for region in LB.REGS:
        kr = D[region]["kr"]
        got, ths = [], []
        for i, u in enumerate(D[region]["UA"]):
            drop = ("A", region, i)
            keep = np.array([x != drop for x in uid])
            m = MF.fit(X[keep], y[keep], "gbm")
            S = cache_scores(m, D)
            th, K = pick_th_cached(S, D, drop)
            j = O2.bool_first_fire(S[drop] >= th, K)
            lead = round(float((u["t_acc"] - u["t"][j]) * DAYS), 1) if j >= 0 else None
            got.append(lead); ths.append((th, K))
            print("    %-6s %2d/%2d %s lead=%s (th=%.4f K=%d)"
                  % (kr, i + 1, len(D[region]["UA"]), u.get("date"),
                     "미발화" if lead is None else "%.0f일" % lead, th, K), flush=True)
        dd = [x for x in got if x is not None]
        out["regions"][region] = dict(kr=kr, n_acc=len(got), det=len(dd) / max(1, len(got)),
                                      med=float(np.median(dd)) if dd else None,
                                      leads=got, th_K=ths)
        tot_leads += got; tot_n += len(got)
        print("  ▶ %-6s 탐지 %5.1f%% (%d/%d) · 리드중앙 %s일  [%.0f분 경과]"
              % (kr, 100 * len(dd) / max(1, len(got)), len(dd), len(got),
                 "-" if not dd else "%.1f" % np.median(dd), (time.time() - t00) / 60), flush=True)

    d = [x for x in tot_leads if x is not None]
    out["overall"] = dict(n_acc=tot_n, det=len(d) / max(1, tot_n),
                          med=float(np.median(d)) if d else None)
    print("\n■ LOAO 전체: 탐지 %.1f%% (%d/%d) · 리드중앙 %s일"
          % (100 * out["overall"]["det"], len(d), tot_n,
             "-" if not d else "%.1f" % out["overall"]["med"]))
    p = os.path.join(C.OUT_ROOT, "verify", "ml_loao.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1, default=str)
    print("→", p)


if __name__ == "__main__":
    main()
