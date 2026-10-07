# -*- coding: utf-8 -*-
"""사고별 과적합-허용 최단 리드타임. usage: leadtime_overfit.py
사고마다 12지표 워크포워드 시계열에서 '최초 발화'가 가장 늦은 에폭이 되도록 임계 AND 규칙(≤3지표)을
역산: 목표 에폭 j의 지표값을 임계로 두면, 이전 모든 에폭이 최소 1개 조건을 위반해야 j가 최초발화점.
(= 과거 에폭 집합을 지표별 kill-set 으로 그리디 셋커버). 절대 하한 = 사고 전 마지막 촬영(gap).
규칙별 배경 오경보(그 지역 배경 30점 중 발화 비율)도 병기 — 과적합 정도의 정직한 표시."""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
import numpy as np, pandas as pd
import sweep_config as C
import discrim_eval as E
import swept_loader as SL
import indicators as ind
import make_unified_map as mum
import leadtime_backtest as LB

DAYS = 365.25
FEATS = ["cum1", "cum1a", "cum2", "cum2a", "cumF", "cumFa",
         "vel", "vela", "vtr", "dv", "ivfrac", "ivimm"]
FKR = {"cum1": "1년누적", "cum1a": "1년누적/α", "cum2": "2년누적", "cum2a": "2년누적/α",
       "cumF": "전체누적", "cumFa": "전체누적/α", "vel": "침하속도", "vela": "침하속도/α",
       "vtr": "후행1년속도", "dv": "가속Δv", "ivfrac": "역속도가속비율", "ivimm": "역속도임박도"}


def _mx(v):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    return float(np.max(v)) if len(v) else np.nan


def ff_series(disp, yrs, alpha, t_end):
    """워크포워드 12지표(버퍼-최댓값, 침하 양수·클수록 위험). 반환 t[T'], F[12,T']."""
    ts, cols = [], []
    for j in range(LB.MIN_EP - 1, len(yrs)):
        tj = yrs[j]
        if tj > t_end:
            break
        row = {}
        vf = ind._seg_slope(yrs[: j + 1], -disp[:, : j + 1].astype(float))
        row["vel"] = _mx(vf); row["vela"] = _mx(vf / alpha)
        row["vtr"] = LB.trailing_vel(disp, yrs, j)
        for nm, w in (("cum1", 1.0), ("cum2", 2.0), ("cumF", None)):
            cw = E.cum_window(disp, yrs, tj, w)
            row[nm] = _mx(cw); row[nm + "a"] = _mx(cw / alpha)
        tr = ind.trend_grade(disp, yrs, tj)
        row["dv"] = _mx(tr["v_late"] - tr["v_early"])
        iv = mum.inverse_velocity(disp, yrs, tj)
        row["ivfrac"] = float(np.mean(iv["accel"])) if len(iv["accel"]) else np.nan
        ld = (iv["tf_year"][iv["accel"]] - tj) * DAYS
        ld = ld[np.isfinite(ld) & (ld > 0)]
        row["ivimm"] = float(-np.min(ld)) if len(ld) else np.nan   # 클수록 임박
        ts.append(tj); cols.append([row[f] for f in FEATS])
    return np.array(ts), np.array(cols, float).T if cols else np.zeros((len(FEATS), 0))


def best_rule_at(Fm, j, max_c=3):
    """에폭 j를 최초발화점으로 만드는 ≤max_c 지표 AND 규칙(그리디 셋커버). 실패 시 None."""
    prev = list(range(j))
    usable = [f for f in range(len(FEATS)) if np.isfinite(Fm[f, j])]
    if not usable:
        return None
    if not prev:
        return [(usable[0], Fm[usable[0], j])]
    kills = {}
    for f in usable:
        with np.errstate(invalid="ignore"):
            kills[f] = {i for i in prev if not (Fm[f, i] >= Fm[f, j])}   # NaN→killed
    uncov = set(prev); rule = []
    while uncov and len(rule) < max_c:
        f = max(kills, key=lambda x: len(kills[x] & uncov))
        gain = len(kills[f] & uncov)
        if gain == 0:
            return None
        rule.append((f, Fm[f, j])); uncov -= kills[f]
    return rule if not uncov else None


def latest_1feat(Fm, T):
    """단일지표 러닝최대(기록점) 기준 가장 늦은 최초발화 에폭."""
    for j in range(T - 1, -1, -1):
        for f in range(len(FEATS)):
            v = Fm[f, j]
            if not np.isfinite(v):
                continue
            with np.errstate(invalid="ignore"):
                if not np.any(Fm[f, :j] >= v):
                    return j, f
    return None, None


def main():
    RNG = np.random.RandomState(23)
    rows = []
    for region in LB.REGS:
        bc = json.load(open(os.path.join(C.OUT_ROOT, region, "best_config.json")))
        coh, tcoh, R = bc["coh"], bc["tcoh"], float(bc["R"])
        csv = os.path.join(C.sweep_dir(region, coh, tcoh), f"{region}_sbas_ps_v.csv")
        e = SL.build_bank_entry(region, csv, use_ps=False)
        sb = e["kinds"]["SBAS"]; yrs = sb["years"]; tree = sb["tree"]
        S, N, W, Ebox = e["box"]
        acc = E.load_accidents_full()
        inbox = acc[acc.lat.between(S, N) & acc.lon.between(W, Ebox) & acc.year.notna()]
        inbox = inbox[inbox.year >= e["y0"]]
        from scipy.spatial import cKDTree
        axr, ayr = SL.loaders._TR_M.transform(acc.lon.values, acc.lat.values)
        atree = cKDTree(np.c_[axr, ayr])
        # 배경 시계열(규칙 FP 평가용)
        bgF = []; got = 0; tries = 0
        while got < LB.N_BG and tries < LB.N_BG * 60 and len(sb["lon"]):
            tries += 1; j = RNG.randint(len(sb["lon"]))
            if atree.query([sb["x"][j], sb["y"][j]])[0] < R:
                continue
            idx = np.array(tree.query_ball_point([sb["x"][j], sb["y"][j]], R), int)
            if not len(idx):
                continue
            _, Fb = ff_series(sb["disp"][idx], yrs, sb["alpha"][idx], yrs[-1])
            bgF.append(Fb); got += 1
        for _, a in inbox.iterrows():
            t_acc = float(a.year)
            ax, ay = SL.loaders._TR_M.transform([a.lon], [a.lat])
            idx = np.array(tree.query_ball_point([ax[0], ay[0]], R), int)
            row = {"region": LB.KR[region], "sagoNo": a.get("sagoNo"), "date": E._fmt(a.sagoDate),
                   "cause": a.cause, "n_buf": len(idx), "post_stack": bool(t_acc > e["y1"])}
            pre = yrs[yrs <= t_acc]
            row["gap_d"] = round(float((t_acc - pre[-1]) * DAYS), 1) if len(pre) else None
            if len(idx) and (yrs <= t_acc).sum() >= LB.MIN_EP:
                t, Fm = ff_series(sb["disp"][idx], yrs, sb["alpha"][idx], t_acc)
                T = len(t)
                if T:
                    j1, f1 = latest_1feat(Fm, T)
                    if j1 is not None:
                        row["lead1_d"] = round(float((t_acc - t[j1]) * DAYS), 1)
                        row["feat1"] = FKR[FEATS[f1]]
                    for j in range(T - 1, -1, -1):
                        rule = best_rule_at(Fm, j)
                        if rule is None:
                            continue
                        row["lead3_d"] = round(float((t_acc - t[j]) * DAYS), 1)
                        row["at_floor"] = bool(j == T - 1)
                        row["rule"] = " AND ".join(f"{FKR[FEATS[f]]}≥{th:.2f}" for f, th in rule)
                        fired = 0
                        for Fb in bgF:
                            ok = np.ones(Fb.shape[1], bool)
                            for f, th in rule:
                                with np.errstate(invalid="ignore"):
                                    ok &= (Fb[f] >= th)
                            fired += int(ok.any())
                        row["bg_fire%"] = round(100 * fired / max(1, len(bgF)), 1)
                        break
            rows.append(row)
        n_r = sum(1 for r in rows if r["region"] == LB.KR[region])
        print(f"■ {LB.KR[region]} 사고 {n_r} (배경 {got})", flush=True)

    od = os.path.join(C.OUT_ROOT, "leadtime")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(od, "overfit_leads.csv"), index=False, encoding="utf-8-sig")
    ok = df[df.lead3_d.notna() & ~df.post_stack]
    print("\n관측기간 내+계산가능 %d건" % len(ok))
    print("최단리드(≤3지표 AND): med=%.1fd  ≤7d:%d  ≤14d:%d  ≤30d:%d  floor달성:%d/%d" % (
        ok.lead3_d.median(), (ok.lead3_d <= 7).sum(), (ok.lead3_d <= 14).sum(),
        (ok.lead3_d <= 30).sum(), ok.at_floor.sum(), len(ok)))
    print("gap(물리하한): med=%.1fd" % ok.gap_d.median())
    print("단일지표 기록점: med=%.1fd" % ok.lead1_d.median())
    print("배경 오경보율: med=%.1f%% mean=%.1f%%" % (ok["bg_fire%"].median(), ok["bg_fire%"].mean()))
    ps = df[df.lead3_d.notna() & df.post_stack]
    if len(ps):
        print("관측종료후 사고 %d건: med lead=%.0fd (스택종료가 하한)" % (len(ps), ps.lead3_d.median()))
    print(f"→ {od}/overfit_leads.csv")


if __name__ == "__main__":
    main()
