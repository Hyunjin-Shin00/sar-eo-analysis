# -*- coding: utf-8 -*-
"""사고별 리드타임 백테스트(워크포워드). usage: leadtime_backtest.py
각 사고(일 단위 sagoDate)에 대해 지역별 최적 SBAS(coh/tcoh/R)로 버퍼 시계열을 걸어가며
(각 에폭 t_j 에서 t_j 이전 관측만 사용) 알람규칙 최초발화 시점 → 리드타임(일) 산출.
규칙 메뉴: 속도지속(v_th×K연속에폭)·가속(Δv)·역속도(Fukuzono 임박창)·누적. 배경 오경보율 병산.
물리적 하한: 사고 직전 마지막 촬영까지의 gap(일) = 어떤 방법으로도 못 줄이는 바닥."""
import os as _os
_CR = _os.environ.get("CLAB_ROOT") or _os.path.abspath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", ".."))   # 전달본 상대경로

import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
import sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CR + "/analysis/sinkhole")
import numpy as np, pandas as pd
import sweep_config as C
import discrim_eval as E
import swept_loader as SL
import indicators as ind
import make_unified_map as mum

RNG = np.random.RandomState(23)
KR = {"Busan_Sasang_Hadan": "사상", "Yangyang": "양양", "Seoul_Gangdong": "강동",
      "Gyeonggi_Gwangmyeong": "광명", "Incheon_Songdo_DSC": "송도", "Seoul_Seodaemun": "서대문",
      "Busan_Mandeok_Centum": "만덕"}
REGS = list(KR)
DAYS = 365.25
SAMEDAY_EPS = 0.5 / 365.25
N_BG = 30           # 지역별 배경(비사고) 점 — 오경보율용
MIN_EP = C.PRE_MIN_EPOCHS   # 지표 유효 최소 에폭(6)

# 알람 규칙 메뉴 -----------------------------------------------------------
VEL_TH = [5.0, 10.0]                 # 속도 임계 mm/yr(침하 양수)
K_SUS = [1, 2, 3, 4]                 # 연속 유지 에폭 수(사용자 제안: 지속기간 조건)
ACC_TH = [5.0, 10.0]                 # 가속 Δv 임계 mm/yr
IV_WIN = [90.0, 30.0]                # 역속도 예측 붕괴 임박창(일)
CUM_TH = [20.0, 40.0]                # 2년누적 임계 mm

RULES = ([f"vel{int(v)}_k{k}" for v in VEL_TH for k in K_SUS]
         + [f"acc{int(a)}" for a in ACC_TH]
         + [f"iv{int(w)}" for w in IV_WIN]
         + [f"cum{int(c)}" for c in CUM_TH])


def trailing_vel(disp, yrs, j):
    """t_j 기준 후행 1년창 속도(mm/yr, 침하 양수) 버퍼-최댓값. 관측<4 → NaN."""
    t = yrs[: j + 1]
    m = t >= (t[-1] - 1.0)
    if m.sum() < 4:
        return np.nan
    v = ind._seg_slope(t[m], -disp[:, : j + 1][:, m].astype(float))
    v = v[np.isfinite(v)]
    return float(np.max(v)) if len(v) else np.nan


def series_features(disp, yrs, t_end):
    """워크포워드: 각 에폭 t_j(≤t_end, j≥MIN_EP-1)에서의 (t_j, v_tr, dv, iv_lead, cum2)."""
    out = []
    for j in range(MIN_EP - 1, len(yrs)):
        tj = yrs[j]
        if tj > t_end:
            break
        v = trailing_vel(disp, yrs, j)
        tr = ind.trend_grade(disp, yrs, tj)
        dvv = tr["v_late"] - tr["v_early"]
        dvv = dvv[np.isfinite(dvv)]
        dv = float(np.max(dvv)) if len(dvv) else np.nan
        iv = mum.inverse_velocity(disp, yrs, tj)
        acc = iv["accel"]
        ivl = np.nan
        if acc.any():
            ld = (iv["tf_year"][acc] - tj) * DAYS
            ld = ld[np.isfinite(ld) & (ld > 0)]
            if len(ld):
                ivl = float(np.min(ld))          # 가장 임박한 예측 붕괴까지 남은 일수
        c2 = E.cum_window(disp, yrs, tj, 2.0)
        c2 = c2[np.isfinite(c2)]
        cum2 = float(np.max(c2)) if len(c2) else np.nan
        out.append((tj, v, dv, ivl, cum2))
    return out


def first_alarms(feats):
    """규칙별 최초 발화 에폭(연도) dict + 순간조건 duty(발화비율)."""
    if not feats:
        return {r: None for r in RULES}, {r: np.nan for r in RULES}
    t = np.array([f[0] for f in feats])
    v = np.array([f[1] for f in feats])
    dv = np.array([f[2] for f in feats])
    ivl = np.array([f[3] for f in feats])
    c2 = np.array([f[4] for f in feats])
    al, duty = {}, {}
    def _first(cond):
        i = np.where(cond)[0]
        return float(t[i[0]]) if len(i) else None
    for vt in VEL_TH:
        hit = np.nan_to_num(v, nan=-1) >= vt
        duty_v = float(hit.mean())
        for k in K_SUS:
            run = 0; fa = None
            for i, h in enumerate(hit):
                run = run + 1 if h else 0
                if run >= k:
                    fa = float(t[i]); break
            al[f"vel{int(vt)}_k{k}"] = fa; duty[f"vel{int(vt)}_k{k}"] = duty_v
    for at in ACC_TH:
        cond = np.nan_to_num(dv, nan=-1) >= at
        al[f"acc{int(at)}"] = _first(cond); duty[f"acc{int(at)}"] = float(cond.mean())
    for w in IV_WIN:
        cond = np.nan_to_num(ivl, nan=1e9) <= w
        al[f"iv{int(w)}"] = _first(cond); duty[f"iv{int(w)}"] = float(cond.mean())
    for ct in CUM_TH:
        cond = np.nan_to_num(c2, nan=-1) >= ct
        al[f"cum{int(ct)}"] = _first(cond); duty[f"cum{int(ct)}"] = float(cond.mean())
    return al, duty


def main():
    rows, bg_rows = [], []
    for region in REGS:
        bc = json.load(open(os.path.join(C.OUT_ROOT, region, "best_config.json")))
        coh, tcoh, R = bc["coh"], bc["tcoh"], float(bc["R"])
        csv = os.path.join(C.sweep_dir(region, coh, tcoh), f"{region}_sbas_ps_v.csv")
        e = SL.build_bank_entry(region, csv, use_ps=False)
        sb = e["kinds"]["SBAS"]; yrs = sb["years"]; tree = sb["tree"]
        rev = float(np.median(np.diff(yrs)) * DAYS)
        S, N, W, Ebox = e["box"]
        acc = E.load_accidents_full()
        inbox = acc[acc.lat.between(S, N) & acc.lon.between(W, Ebox) & acc.year.notna()]
        inbox = inbox[inbox.year >= e["y0"]]
        print(f"■ {KR[region]} coh{coh}/tcoh{tcoh}/R{int(R)} 사고 {len(inbox)}건 revisit {rev:.1f}d", flush=True)
        from scipy.spatial import cKDTree
        axr, ayr = SL.loaders._TR_M.transform(acc.lon.values, acc.lat.values)
        atree = cKDTree(np.c_[axr, ayr])
        # ---- 사고별 ----
        for _, a in inbox.iterrows():
            t_acc = float(a.year)
            ax, ay = SL.loaders._TR_M.transform([a.lon], [a.lat])
            idx = np.array(tree.query_ball_point([ax[0], ay[0]], R), int)
            row = {"region": KR[region], "sagoNo": a.get("sagoNo"), "date": E._fmt(a.sagoDate),
                   "cause": a.cause, "n_buf": len(idx), "revisit_d": round(rev, 1)}
            pre = yrs[yrs < t_acc - SAMEDAY_EPS]
            row["gap_d"] = round(float((t_acc - pre[-1]) * DAYS), 1) if len(pre) else None
            row["post_stack"] = bool(t_acc > e["y1"])
            if len(idx) and len(pre) >= MIN_EP:
                feats = series_features(sb["disp"][idx], yrs, t_acc)
                al, duty = first_alarms(feats)
                for r in RULES:
                    row[f"lead_{r}"] = round((t_acc - al[r]) * DAYS, 1) if al[r] is not None else None
                    row[f"duty_{r}"] = round(duty[r], 3)
            rows.append(row)
        # ---- 배경(오경보) ----
        Np = len(sb["lon"]); got = 0; tries = 0
        while got < N_BG and tries < N_BG * 60 and Np:
            tries += 1; j = RNG.randint(Np)
            if atree.query([sb["x"][j], sb["y"][j]])[0] < R:
                continue
            idx = np.array(tree.query_ball_point([sb["x"][j], sb["y"][j]], R), int)
            if not len(idx):
                continue
            feats = series_features(sb["disp"][idx], yrs, yrs[-1])
            al, duty = first_alarms(feats)
            b = {"region": KR[region]}
            for r in RULES:
                b[f"alarm_{r}"] = al[r] is not None
                b[f"duty_{r}"] = duty[r]
            bg_rows.append(b); got += 1
        print(f"   배경 {got}점 완료", flush=True)

    od = os.path.join(C.OUT_ROOT, "leadtime"); os.makedirs(od, exist_ok=True)
    df = pd.DataFrame(rows); df.to_csv(os.path.join(od, "leadtime_per_accident.csv"),
                                       index=False, encoding="utf-8-sig")
    bg = pd.DataFrame(bg_rows); bg.to_csv(os.path.join(od, "leadtime_background.csv"),
                                          index=False, encoding="utf-8-sig")
    # ---- 요약 ----
    summ = {}
    ok = df[df.n_buf > 0]
    for r in RULES:
        ld = ok[f"lead_{r}"].dropna() if f"lead_{r}" in ok else pd.Series(dtype=float)
        summ[r] = {"det%": round(100 * len(ld) / max(1, len(ok)), 1),
                   "lead_med_d": round(float(ld.median()), 1) if len(ld) else None,
                   "lead_min_d": round(float(ld.min()), 1) if len(ld) else None,
                   "lead_p10_d": round(float(ld.quantile(0.1)), 1) if len(ld) else None,
                   "n_le_30d": int((ld <= 30).sum()), "n_le_7d": int((ld <= 7).sum()),
                   "bg_alarm%": round(100 * float(bg[f"alarm_{r}"].mean()), 1) if len(bg) else None,
                   "bg_duty_med": round(float(bg[f"duty_{r}"].median()), 3) if len(bg) else None}
    gap = df.gap_d.dropna()
    summ["_floor"] = {"n_acc": len(df), "n_with_sbas": int((df.n_buf > 0).sum()),
                      "gap_med_d": round(float(gap.median()), 1),
                      "gap_max_d": round(float(gap.max()), 1),
                      "gap_le_7d%": round(100 * float((gap <= 7).mean()), 1),
                      "revisit_med_d": round(float(df.revisit_d.median()), 1),
                      "post_stack_n": int(df.post_stack.sum())}
    json.dump(summ, open(os.path.join(od, "leadtime_summary.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summ["_floor"], ensure_ascii=False))
    for r in RULES:
        print(r, summ[r])
    print(f"→ {od}/")


if __name__ == "__main__":
    main()
