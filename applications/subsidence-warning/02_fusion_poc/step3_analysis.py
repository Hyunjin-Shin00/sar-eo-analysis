# -*- coding: utf-8 -*-
"""
STEP 3 — 싱크홀 발생지 vs 미발생지 차이분석 + (A)제약 검증
필요 입력: events.py 의 발생점 좌표(lon/lat/buffer_m/event_date).

산출:
  1) 발생점 버퍼 판정표(케이스별 4분면 라벨, PS/SBAS 최종등급, (A)충족)
  2) (A)제약 검증: 양성(①②④⑦) 중 '정상' 잔존 건수 = 0 인지
  3) 리드타임(첫 상위등급 진입 ~ 사고일; 경보 선행 시 TP)
  4) ③분면(⑧⑨) InSAR 신호 있는 그대로 보고(강제 상향 금지)
  5) 임계치 세트별 (recall / FP / 채택임계치) 표 — 사용자 최종선택용
  6) 발생 vs 미발생 그룹 분포 비교(속도/누적/α/지반등급) + 시각화
⚠️ 임계치·α·버퍼 잠정값(config.py).
"""
import os
os.environ.pop("PYTHONPATH", None)
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy.spatial import cKDTree
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir(); os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
from pyproj import Transformer

from config import CONFIG, REGIONS, POSITIVE_STRICT, QUAD3_INSAR_LIMIT
import loaders, indicators as ind
from events import EVENTS

_ORD = {"정상": 0, "주의": 1, "위험": 2}
_INV = {0: "정상", 1: "주의", 2: "위험"}
_TR_M = Transformer.from_crs(CONFIG["crs_wgs"], CONFIG["crs_metric"], always_xy=True)


def _year(datestr):
    if datestr is None:
        return None
    t = pd.Timestamp(datestr)
    return t.year + (t - pd.Timestamp(t.year, 1, 1)).days / 365.25


def _bore():
    fp = os.path.join(CONFIG["paths"]["out_dir"], "step1_borehole_grade.csv")
    b = pd.read_csv(fp, encoding="utf-8-sig")
    tree = cKDTree(np.column_stack([b["x_m"].values, b["y_m"].values]))
    return tree, b["alpha"].values, b["등급"].values


def _grade_points(data, alpha, asof=None, thr=None):
    """PS/SBAS data dict → per-point (gv,gc,gt,grade_int, rv, rc, consec)."""
    thr = thr or CONFIG["thr_base"]
    rv = ind.risk_velocity(data["vel"])
    rc = ind.risk_cumulative(data["disp"], data["years"], asof)
    tr = ind.trend_grade(data["disp"], data["years"], asof, thr)
    gv = ind.grade_velocity(rv, alpha, thr); gc = ind.grade_cumulative(rc, alpha, thr)
    gv = ind.subsidence_gate(gv, data["vel"]); gc = ind.subsidence_gate(gc, data["vel"])
    gt = ind.subsidence_gate(tr["grade"], data["vel"])
    g = ind.combine_max(gv, gc, gt)
    gi = np.array([_ORD[x] for x in g])
    return dict(gv=gv, gc=gc, gt=gt, grade=g, gi=gi, rv=rv, rc=rc, v_late=tr["v_late"])


def _leadtime(disp_row, years, alpha, event_year, thr):
    """한 점의 첫 '주의' 진입연도 — 등급과 동일한 '최근 2년창 강건 net 침하'가
    cum_watch×α 를 처음 넘는 시점(as-of 각 에폭). 초기 노이즈 transient 방어."""
    k = CONFIG.get("cum_robust_k", 3); win = CONFIG.get("cum_window_years", 2.0)
    s = -disp_row.astype(float)                    # 침하 양수 누적
    thr_cum = thr["cum_watch"] * alpha
    T = len(years)
    for e in range(T):
        te = years[e]
        if event_year is not None and te > event_year:
            break
        m = (years <= te) & (years >= te - win)
        d = s[m]; d = d[np.isfinite(d)]
        if len(d) < 2 * k:
            continue
        net = np.median(d[-k:]) - np.median(d[:k])  # 최근 2년창 net 침하
        if net >= thr_cum:
            return te
    return None


def buffer_analysis(save=True, thr=None):
    thr = thr or CONFIG["thr_base"]
    btree, balpha, bgrade = _bore()
    rows = []
    lead_rows = []
    have = {r: e for r, e in EVENTS.items() if e["lon"] is not None and e["lat"] is not None}
    if not have:
        print("⚠️ events.py에 좌표가 없습니다. 발생점 lon/lat을 채운 뒤 실행하세요.")
        return None, None

    for region, ev in have.items():
        ex, ey = _TR_M.transform(ev["lon"], ev["lat"])
        eyr = _year(ev["event_date"])
        buf = ev["buffer_m"]
        lead_cands = []  # (first_year, kind) — PS/SBAS 경보점 중 가장 이른 진입
        for kind, load in [("PS", loaders.load_ps), ("SBAS", loaders.load_sbas)]:
            d = load(region)
            xy = np.column_stack([d["x"], d["y"]])
            dist = np.hypot(xy[:, 0] - ex, xy[:, 1] - ey)
            inb = dist <= buf
            n_in = int(inb.sum())
            alpha, _, _ = _nearest(btree, balpha, bgrade, xy[inb]) if n_in else (np.array([]),)*3
            if n_in == 0:
                rows.append(dict(quad=ev["quad"], region=region, type=ev["type"], kind=kind,
                                 desc=ev["desc"], n_in_buffer=0, max_grade="데이터없음",
                                 n_주의=0, n_위험=0, alarm_ratio=0.0))
                continue
            sub = {k: (v[inb] if isinstance(v, np.ndarray) and v.shape[:1] == inb.shape else v)
                   for k, v in d.items()}
            gp = _grade_points(sub, alpha, asof=eyr, thr=thr)
            gi = gp["gi"]
            maxg = _INV[int(gi.max())] if n_in else "정상"
            rows.append(dict(quad=ev["quad"], region=region, type=ev["type"], kind=kind,
                             desc=ev["desc"], n_in_buffer=n_in, max_grade=maxg,
                             n_주의=int((gi == 1).sum()), n_위험=int((gi == 2).sum()),
                             alarm_ratio=round((gi >= 1).mean(), 3),
                             med_rv=round(float(np.nanmedian(gp["rv"])), 2),
                             p90_rv=round(float(np.nanpercentile(gp["rv"], 90)), 2),
                             med_rc=round(float(np.nanmedian(gp["rc"])), 2),
                             p90_rc=round(float(np.nanpercentile(gp["rc"], 90)), 2),
                             med_alpha=round(float(np.nanmedian(alpha)), 2)))
            # 리드타임: 경보(주의+)점 중 최근2년창 누적이 임계 넘는 첫 시점(PS/SBAS 모두)
            if eyr:
                alarmed = np.where(gi >= 1)[0]
                cand = alarmed[np.argsort(-gp["rc"][alarmed])][:30] if len(alarmed) else []
                for j in cand:
                    fy = _leadtime(sub["disp"][j], sub["years"], alpha[j], eyr, thr)
                    if fy is not None:
                        lead_cands.append((fy, kind))
        # 이벤트별 리드타임 집계
        if eyr:
            if lead_cands:
                first, fkind = min(lead_cands, key=lambda x: x[0])
                lead_days = (eyr - first) * 365.25
                lead_rows.append(dict(quad=ev["quad"], region=region, type=ev["type"],
                                      event_date=ev["event_date"], detector=fkind,
                                      first_alarm_year=round(first, 2), leadtime_days=round(lead_days, 0),
                                      TP=lead_days > 0))
            else:
                lead_rows.append(dict(quad=ev["quad"], region=region, type=ev["type"],
                                      event_date=ev["event_date"], detector="-",
                                      first_alarm_year=None, leadtime_days=None, TP=False))

    bdf = pd.DataFrame(rows); ldf = pd.DataFrame(lead_rows)
    if save:
        od = CONFIG["paths"]["out_dir"]
        bdf.to_csv(os.path.join(od, "step3_buffer_grades.csv"), index=False, encoding="utf-8-sig")
        ldf.to_csv(os.path.join(od, "step3_leadtime.csv"), index=False, encoding="utf-8-sig")
    return bdf, ldf


def _nearest(tree, alpha, grade, xy):
    if len(xy) == 0:
        return np.array([]), np.array([]), np.array([])
    d, i = tree.query(xy, k=1)
    return alpha[i], grade[i], d


def check_A_constraint(bdf):
    """(A): 양성(①②④⑦) 버퍼가 주의/위험이면 충족. ③분면(⑧⑨)은 예외 표기."""
    print("\n" + "=" * 72)
    print("(A)제약 검증 — 양성 케이스는 무조건 주의/위험이어야 함 "
          "(강동①·광명②·양양⑦·연희동⑧·사상⑨, 2026-07-09 예외 폐지)")
    print("=" * 72)
    # 케이스별 PS/SBAS 통합 최고등급
    g = bdf.groupby(["region", "quad", "type"]).agg(
        max_grade=("max_grade", lambda s: _INV[max([_ORD.get(x, 0) for x in s])]),
        n_주의=("n_주의", "sum"), n_위험=("n_위험", "sum")).reset_index()
    fail = []
    for _, r in g.iterrows():
        strict = r["region"] in POSITIVE_STRICT
        q3 = r["region"] in QUAD3_INSAR_LIMIT
        ok = _ORD.get(r["max_grade"], 0) >= 1
        tag = "✅상위" if ok else "❌정상잔존"
        note = ""
        if q3:
            note = "(③분면 InSAR한계 — (A)예외)"
        elif strict and not ok:
            fail.append(r["region"]); note = "★(A)위반"
        print(f"  {r['quad']} {r['region']:<22} 최고등급={r['max_grade']:<3} "
              f"주의{int(r['n_주의'])}/위험{int(r['n_위험'])} {tag} {note}")
    n_strict = len(POSITIVE_STRICT & set(g["region"]))
    n_fail = len(fail)
    print(f"\n  ▶ 양성(①②④⑦) 중 '정상' 잔존 건수 = {n_fail}  "
          + ("✅ (A)충족" if n_fail == 0 else f"❌ 미충족: {fail} → 임계치 하향 재판정 필요"))
    return n_fail, fail


def _collect_eval_points(thr_base=None):
    """임계치 스윕용 평가점 수집(원시 지표값 rv/rc/consec/alpha 저장 → 재판정 저렴).
       양성/③분면: 발생버퍼(as-of 사고일).  음성: 지역 전체(전기간).  (좌표 필요)"""
    btree, balpha, bgrade = _bore()
    # 양성/③분면: 좌표 필요(버퍼). 음성: 좌표 없어도 지역전체로 포함.
    have = {r: e for r, e in EVENTS.items()
            if (e["lon"] is not None) or (e["type"] == "negative")}
    pos, neg = {}, {}
    for region, ev in have.items():
        eyr = _year(ev["event_date"])
        ex = ey = None
        if ev["lon"] is not None:
            ex, ey = _TR_M.transform(ev["lon"], ev["lat"])
        # 양성/③분면 버퍼: PS+SBAS 통합.  음성 FP: SBAS 스크리닝층 기준(광역 침하 탐지 주체).
        loaders_use = (loaders.load_sbas,) if ev["type"] == "negative" else (loaders.load_ps, loaders.load_sbas)
        packs = []
        for load in loaders_use:
            d = load(region); xy = np.column_stack([d["x"], d["y"]])
            if ev["type"] == "negative":
                inb = np.ones(len(d["vel"]), bool); asof = None
            else:
                inb = np.hypot(xy[:, 0]-ex, xy[:, 1]-ey) <= ev["buffer_m"]; asof = eyr
            if inb.sum() == 0:
                continue
            alpha, _, _ = _nearest(btree, balpha, bgrade, xy[inb])
            sub = {k: (v[inb] if isinstance(v, np.ndarray) and v.shape[:1] == inb.shape else v) for k, v in d.items()}
            rv = ind.risk_velocity(sub["vel"]); rc = ind.risk_cumulative(sub["disp"], sub["years"], asof)
            tr = ind.trend_grade(sub["disp"], sub["years"], asof)
            gt = ind.subsidence_gate(tr["grade"], sub["vel"])
            gt_int = np.array([_ORD[x] for x in gt])
            up = (np.asarray(sub["vel"], float) > 0).astype(int)  # 융기(제외 대상)
            packs.append(dict(rv=rv, rc=rc, gt_int=gt_int, alpha=alpha, up=up))
        if not packs:
            continue
        merged = {k: np.concatenate([p[k] for p in packs]) for k in ("rv", "rc", "gt_int", "alpha", "up")}
        (pos if ev["type"] != "negative" else neg)[region] = merged
    return pos, neg, have


def threshold_sweep(save=True):
    """임계치 세트별 (recall / FP / 채택임계치) 표 — recall우선 하향, floor 준수.
       사용자 최종선택용(클로드 단독확정 금지)."""
    pos, neg, have = _collect_eval_points()
    if not pos:
        print("⚠️ 좌표 없음 → 임계치 스윕 생략."); return None
    fl = CONFIG["thr_floor"]; base = CONFIG["thr_base"]
    # 후보 세트: (vel_watch, vel_danger, cum_watch, cum_danger) 를 base에서 floor까지 하향
    cand = []
    for scale in [1.0, 0.9, 0.8, 0.7, 0.6]:
        vw = max(fl["vel"], round(base["vel_watch"]*scale, 1))
        vd = max(fl["vel"]+2, round(base["vel_danger"]*scale, 1))
        cw = max(fl["cum"], round(base["cum_watch"]*scale, 1))
        cd = max(fl["cum"]+2, round(base["cum_danger"]*scale, 1))
        cand.append(dict(scale=scale, vel_watch=vw, vel_danger=vd, cum_watch=cw, cum_danger=cd,
                         vel_immediate=base["vel_immediate"],
                         accel_watch_consec=base["accel_watch_consec"],
                         accel_danger_consec=base["accel_danger_consec"]))

    def _grade_from(pack, thr):
        # 추세(가속)는 vel/cum 임계치와 무관 → 사전계산된 gt_int 재사용
        gv = ind.grade_velocity(pack["rv"], pack["alpha"], thr)
        gc = ind.grade_cumulative(pack["rc"], pack["alpha"], thr)
        gv = ind.subsidence_gate(gv, np.where(pack["up"] > 0, 1.0, -1.0))
        gc = ind.subsidence_gate(gc, np.where(pack["up"] > 0, 1.0, -1.0))
        gt = np.array([_INV[v] for v in pack["gt_int"]], dtype=object)  # gt_int 이미 게이트됨
        gi = ind.combine_max(gv, gc, gt)
        return np.array([_ORD[x] for x in gi])

    rows = []
    strict = [r for r in pos if r in POSITIVE_STRICT]
    for c in cand:
        # recall: 양성-strict 버퍼 중 최고등급>=주의 비율
        hit = sum(1 for r in strict if _grade_from(pos[r], c).max() >= 1)
        recall = hit/len(strict) if strict else float("nan")
        # FP: 음성 지역 전체 주의+ 비율/건수
        fp_cnt = fp_tot = 0
        for r in neg:
            gi = _grade_from(neg[r], c); fp_cnt += int((gi >= 1).sum()); fp_tot += len(gi)
        rows.append(dict(scale=c["scale"], vel_watch=c["vel_watch"], vel_danger=c["vel_danger"],
                         cum_watch=c["cum_watch"], cum_danger=c["cum_danger"],
                         pos_strict_recall=round(recall, 3), pos_hit=f"{hit}/{len(strict)}",
                         neg_FP_cnt=fp_cnt, neg_FP_ratio=round(fp_cnt/fp_tot, 3) if fp_tot else 0.0,
                         at_floor=(c["vel_watch"] <= fl["vel"] or c["cum_watch"] <= fl["cum"])))
    sdf = pd.DataFrame(rows)
    if save:
        sdf.to_csv(os.path.join(CONFIG["paths"]["out_dir"], "step3_threshold_sweep.csv"),
                   index=False, encoding="utf-8-sig")
    print("\n" + "=" * 72)
    print("임계치 세트별 recall(양성)/FP(음성) — ★사용자 최종선택 (클로드 단독확정 금지)")
    print("floor: 속도 %.0f, 누적 %.0f mm 미만 하향금지" % (fl["vel"], fl["cum"]))
    print("=" * 72)
    print(sdf.to_string(index=False))
    # recall=1.0 만족하는 가장 덜 공격적(높은 scale) 세트 추천
    ok = sdf[sdf["pos_strict_recall"] >= 0.999]
    if len(ok):
        best = ok.iloc[0]
        print(f"\n▶ recall=100% 달성 최소하향 세트: scale={best['scale']} "
              f"(vel {best['vel_watch']}/{best['vel_danger']}, cum {best['cum_watch']}/{best['cum_danger']}, "
              f"FP {best['neg_FP_cnt']}) — 확정은 사용자.")
    else:
        print("\n❌ floor 내 어떤 세트도 recall=100% 미달 → 방법론 재검토 대상(억지 하향 금지).")
    return sdf


def group_comparison(save=True):
    """발생 vs 미발생 그룹 분포 비교(속도/누적/α/최종등급) + 4분면 교차표 + 시각화.
       STEP2 산출물(step2_sbas_judgment_ALL.csv) 기반 — 좌표 불필요(지역 전체)."""
    od = CONFIG["paths"]["out_dir"]
    sb = pd.read_csv(os.path.join(od, "step2_sbas_judgment_ALL.csv"), encoding="utf-8-sig")
    typ = {r: REGIONS.get(r, {}).get("quad", "") for r in sb["region"].unique()}
    # 2026-07-09 케이스 재확정: ③분면 그룹 폐지. 양성={강동,광명,양양,연희동⑧,사상⑨}, 음성={송도③,만덕④}.
    tmap = {"Seoul_Gangdong": "양성", "Gyeonggi_Gwangmyeong": "양성", "Yangyang": "양성",
            "Seoul_Seodaemun": "양성", "Busan_Sasang_Hadan": "양성",
            "Incheon_Songdo": "음성", "Busan_Mandeok_Centum": "음성"}
    sb["group"] = sb["region"].map(tmap).fillna("기타")
    # 기술통계
    print("\n" + "=" * 72); print("발생 vs 미발생 그룹 분포 비교 (SBAS 판정점 기준, 지역전체)"); print("=" * 72)
    agg = sb.groupby("group").agg(
        n=("final_grade", "size"),
        주의위험율=("final_grade", lambda s: round((s != "정상").mean(), 3)),
        rv_중앙=("sbas_rv_mmyr", "median"), rv_p90=("sbas_rv_mmyr", lambda s: round(s.quantile(.9), 2)),
        cum_중앙=("sbas_cum_mm", "median"), cum_p90=("sbas_cum_mm", lambda s: round(s.quantile(.9), 2)),
        alpha_중앙=("alpha", "median"), hotspot율=("hotspot", "mean")).reset_index()
    print(agg.to_string(index=False))
    # 4분면 교차표
    ct = pd.crosstab(sb["quad"], sb["final_grade"])
    print("\n[4분면 라벨 × 최종등급 교차표 (SBAS 판정점)]")
    print(ct.to_string())
    if save:
        agg.to_csv(os.path.join(od, "step3_group_compare.csv"), index=False, encoding="utf-8-sig")
        ct.to_csv(os.path.join(od, "step3_crosstab_quad.csv"), encoding="utf-8-sig")
    # 시각화
    try:
        import matplotlib.font_manager as fm
        for fp in ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"]:
            if os.path.exists(fp):
                fm.fontManager.addfont(fp)
                plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()  # 등록 실제명 사용
                break
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.5))
    groups = ["양성", "음성"]; colors = {"양성": "#d62728", "음성": "#2166ac"}
    for g in groups:
        d = sb[sb["group"] == g]
        if not len(d):
            continue
        ax[0].hist(np.clip(d["sbas_rv_mmyr"], -10, 25), bins=40, alpha=0.5, density=True, label=g, color=colors[g])
        ax[1].hist(np.clip(d["sbas_cum_mm"], -10, 40), bins=40, alpha=0.5, density=True, label=g, color=colors[g])
    ax[0].axvline(5, ls="--", c="k", lw=.8); ax[0].axvline(10, ls="--", c="r", lw=.8)
    ax[0].set_title("침하속도 분포 (mm/yr)"); ax[0].set_xlabel("risk_vel"); ax[0].legend()
    ax[1].axvline(15, ls="--", c="k", lw=.8); ax[1].axvline(20, ls="--", c="r", lw=.8)
    ax[1].set_title("누적침하 분포 (mm)"); ax[1].set_xlabel("risk_cum"); ax[1].legend()
    gr = sb.groupby(["group", "final_grade"]).size().unstack(fill_value=0)
    gr = gr.div(gr.sum(axis=1), axis=0)
    gr = gr.reindex([g for g in groups if g in gr.index])
    gr[[c for c in ["정상", "주의", "위험"] if c in gr.columns]].plot(
        kind="bar", stacked=True, ax=ax[2], color={"정상": "#2166ac", "주의": "#ff7f0e", "위험": "#d62728"})
    ax[2].set_title("그룹별 최종등급 비율"); ax[2].set_ylabel("비율"); ax[2].tick_params(axis="x", rotation=0)
    fig.suptitle("STEP3 발생 vs 미발생 분포 비교 (잠정 임계치)", fontweight="bold")
    fig.tight_layout()
    fp = os.path.join(od, "step3_group_comparison.png"); fig.savefig(fp, dpi=110, bbox_inches="tight"); plt.close(fig)
    print(f"\n시각화 저장: {fp}")
    return agg, ct


def case_verification(bdf, ldf, save=True):
    """사례 검증 테이블: 케이스별 TP/TN/FP/FN + ③분면 예외 + 리드타임.
       PoC 평가지표(정탐수·평균리드타임·오탐·재현율)."""
    # 케이스별 통합 최고등급(PS/SBAS)
    g = bdf.groupby(["quad", "region", "type"]).agg(
        max_grade=("max_grade", lambda s: _INV[max([_ORD.get(x, 0) for x in s])]),
        buf_n=("n_in_buffer", "sum"), n_주의=("n_주의", "sum"), n_위험=("n_위험", "sum")).reset_index()
    lead = {r: (row["leadtime_days"], row["detector"]) for r, row in ldf.set_index("region").iterrows()} if ldf is not None and len(ldf) else {}
    rows = []
    for _, r in g.iterrows():
        reg = r["region"]; typ = r["type"]; alarmed = _ORD.get(r["max_grade"], 0) >= 1
        q3 = reg in QUAD3_INSAR_LIMIT
        lt, det = lead.get(reg, (None, "-"))
        if typ == "negative":
            verdict = "FP" if alarmed else "TN"
        elif q3:  # ③분면: (A)예외 — 정성 판정
            verdict = "③분면-신호있음(InSAR한계 주의해석)" if alarmed else "③분면-미탐(InSAR한계, 예상됨)"
        else:  # 양성 strict
            if alarmed and lt is not None and lt > 0:
                verdict = "TP"
            elif alarmed:
                verdict = "TP(리드타임불명)"
            else:
                verdict = "FN(★(A)위반)"
        rows.append(dict(quad=r["quad"], region=reg, type=typ, max_grade=r["max_grade"],
                         buffer_n=int(r["buf_n"]), n_주의=int(r["n_주의"]), n_위험=int(r["n_위험"]),
                         detector=det, leadtime_days=lt, verdict=verdict))
    cv = pd.DataFrame(rows)
    if save:
        cv.to_csv(os.path.join(CONFIG["paths"]["out_dir"], "step3_case_verification.csv"),
                  index=False, encoding="utf-8-sig")
    print("\n" + "=" * 72); print("사례 검증 테이블 (케이스별 TP/TN/FP/FN — 발생 전건 양성, 예외 없음)"); print("=" * 72)
    print(cv.to_string(index=False))
    strict = cv[cv["type"] == "positive"]
    tp = int(strict["verdict"].str.startswith("TP").sum())
    fn = int(strict["verdict"].str.startswith("FN").sum())
    lts = [x for x in strict["leadtime_days"] if x is not None and x > 0]
    print(f"\n[PoC 평가지표] 정탐 TP={tp}/{len(strict)}  FN={fn}  "
          f"평균리드타임={np.mean(lts):.0f}일 (중앙 {np.median(lts):.0f}일)" if lts else "")
    neg = cv[cv["type"] == "negative"]
    print(f"  음성 FP 케이스={int((neg['verdict']=='FP').sum())}/{len(neg)} "
          f"(송도=실제 광역압밀 침하, InSAR '침하≠붕괴' 한계 baseline)")
    shallow = cv[cv.region.isin({"Seoul_Seodaemun", "Busan_Sasang_Hadan"})]
    print(f"  천층 사고(연희동⑧·사상⑨, 예외 폐지→양성): {list(zip(shallow['region'], shallow['verdict']))}")
    return cv


if __name__ == "__main__":
    import sys
    # 그룹 분포 비교 + 4분면 교차표 (좌표 불필요, STEP2 산출물 기반)
    group_comparison(save=True)
    # 발생점 버퍼 판정 + (A)검증 + 리드타임 + 임계치 스윕 (좌표 필요)
    bdf, ldf = buffer_analysis(save=True)
    if bdf is not None:
        print("\n[발생점 버퍼 판정표]")
        print(bdf.to_string(index=False))
        check_A_constraint(bdf)
        if ldf is not None and len(ldf):
            print("\n[리드타임] (양수=경보가 사고 선행 → TP)")
            print(ldf.to_string(index=False))
        case_verification(bdf, ldf, save=True)
        threshold_sweep(save=True)
