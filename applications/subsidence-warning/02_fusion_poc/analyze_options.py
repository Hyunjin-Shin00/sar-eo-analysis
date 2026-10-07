# -*- coding: utf-8 -*-
"""
의사결정용 비교표 생성 — ★최종 선택은 사용자(클로드 단독확정 금지).
====================================================================
한 번 로드(캐시 npz)해 메모리에 올려두고 아래 스윕을 재사용한다.

  A-2  trend_methods   : 추세(가속) 방법별 recall(양성5)/FP(음성2)
  A-1  combine_rules   : SBAS 단독 결합규칙(i/ii/iii)별 recall/FP + 클러스터(DBSCAN) 단위
  B-1  buffer          : 발생버퍼 반경(250/500/1000m)별 TP/FP
  B-4  cum_window      : 누적변위 산정기간(1/2/3년)별 recall/FP 민감도
  C    discriminator   : 발생 vs 미발생 판별자(가속/공간국소성/시계열형상) 분포비교

공통 평가 규약(기존 step3 threshold_sweep과 정합):
  · 양성(5): 발생버퍼(as-of 사고일) PS+SBAS. recall = 버퍼 내 최고등급>=주의 케이스 비율.
  · 음성(2): SBAS 지역전체(광역침하 탐지 주체). FP = 주의+ 점 수(지표수준, hotspot 게이팅 前).
  · 등급 = combine_max(gv,gc,gt) 후 subsidence_gate(vel>=0→정상). 지표수준 비교(step3와 동일).
사용법:  python analyze_options.py [a2|a1|b1|b4|c|all]
"""
import os, sys
os.environ.pop("PYTHONPATH", None)
import numpy as np, pandas as pd
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir(); os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
from pyproj import Transformer
from scipy.spatial import cKDTree

from config import CONFIG, REGIONS, POSITIVE_STRICT, NEGATIVE_CASES
import loaders, indicators as ind
from events import EVENTS

_ORD = {"정상": 0, "주의": 1, "위험": 2}
_INV = {0: "정상", 1: "주의", 2: "위험"}
_TR_M = Transformer.from_crs(CONFIG["crs_wgs"], CONFIG["crs_metric"], always_xy=True)
OUT = CONFIG["paths"]["out_dir"]

POS = [r for r in EVENTS if EVENTS[r]["type"] == "positive" and EVENTS[r]["lon"] is not None]
NEG = [r for r in EVENTS if EVENTS[r]["type"] == "negative"]


# ---------------- 공통 로드 (1회) ----------------
_CACHE = {}
def _bore():
    if "bore" not in _CACHE:
        b = pd.read_csv(os.path.join(OUT, "step1_borehole_grade.csv"), encoding="utf-8-sig")
        _CACHE["bore"] = (cKDTree(np.column_stack([b["x_m"].values, b["y_m"].values])),
                          b["alpha"].values)
    return _CACHE["bore"]


def _alpha_for(xy):
    tree, alpha = _bore()
    if len(xy) == 0:
        return np.array([])
    _, i = tree.query(xy, k=1)
    return alpha[i]


def _load(region, kind):
    key = (region, kind)
    if key not in _CACHE:
        _CACHE[key] = (loaders.load_ps if kind == "ps" else loaders.load_sbas)(region)
    return _CACHE[key]


def _year(datestr):
    if datestr is None:
        return None
    t = pd.Timestamp(datestr)
    return t.year + (t - pd.Timestamp(t.year, 1, 1)).days / 365.25


def _buffer_sub(region, kind, buffer_m):
    """양성 버퍼 내 부분집합 dict + alpha + asof."""
    ev = EVENTS[region]
    d = _load(region, kind)
    ex, ey = _TR_M.transform(ev["lon"], ev["lat"])
    inb = np.hypot(d["x"] - ex, d["y"] - ey) <= buffer_m
    if inb.sum() == 0:
        return None
    sub = {k: (v[inb] if isinstance(v, np.ndarray) and v.shape[:1] == inb.shape else v)
           for k, v in d.items()}
    return sub, _alpha_for(np.column_stack([sub["x"], sub["y"]])), _year(ev["event_date"])


def _grade_int(sub, alpha, thr, trend_method, asof=None, cum_window=None):
    """지표수준 최종등급 정수배열 (combine_max + subsidence_gate)."""
    if cum_window is not None:
        old = CONFIG["cum_window_years"]; CONFIG["cum_window_years"] = cum_window
    rv = ind.risk_velocity(sub["vel"]); rc = ind.risk_cumulative(sub["disp"], sub["years"], asof)
    if cum_window is not None:
        CONFIG["cum_window_years"] = old
    tr = ind.trend_grade(sub["disp"], sub["years"], asof, thr, method=trend_method)
    gv = ind.grade_velocity(rv, alpha, thr); gc = ind.grade_cumulative(rc, alpha, thr)
    gv = ind.subsidence_gate(gv, sub["vel"]); gc = ind.subsidence_gate(gc, sub["vel"])
    gt = ind.subsidence_gate(tr["grade"], sub["vel"])
    g = ind.combine_max(gv, gc, gt)
    gt_int = np.array([_ORD[x] for x in gt])
    return np.array([_ORD[x] for x in g]), gt_int


# =================================================================
# A-2  추세(가속) 방법별 recall / FP
# =================================================================
def sweep_trend_methods(thr=None, save=True):
    thr = thr or CONFIG["thr_base"]
    methods = ["2seg", "slidewin", "quad", "inflection"]
    rows = []
    # 양성: 버퍼(PS+SBAS). 어떤 지표든 >=주의면 hit. + '추세 단독 hit'(가속만으로 잡히는지) 병기
    pos_detail = {m: {} for m in methods}
    for m in methods:
        hit = 0; trend_dep = 0
        for r in POS:
            gmax = 0; gmax_notrend = 0; tmax = 0
            for kind in ("ps", "sbas"):
                bs = _buffer_sub(r, kind, EVENTS[r]["buffer_m"])
                if bs is None:
                    continue
                sub, alpha, asof = bs
                gi, gti = _grade_int(sub, alpha, thr, m, asof=asof)
                # 추세 제거 등급(vel/cum만)
                rv = ind.risk_velocity(sub["vel"]); rc = ind.risk_cumulative(sub["disp"], sub["years"], asof)
                gv = ind.subsidence_gate(ind.grade_velocity(rv, alpha, thr), sub["vel"])
                gc = ind.subsidence_gate(ind.grade_cumulative(rc, alpha, thr), sub["vel"])
                gnt = np.array([_ORD[x] for x in ind.combine_max(gv, gc)])
                gmax = max(gmax, int(gi.max())); tmax = max(tmax, int(gti.max()))
                gmax_notrend = max(gmax_notrend, int(gnt.max()))
            pos_detail[m][r] = (gmax, tmax, gmax_notrend)
            if gmax >= 1:
                hit += 1
            if gmax >= 1 and gmax_notrend == 0:   # 추세 없으면 못 잡는 케이스
                trend_dep += 1
        # 음성 FP: SBAS 지역전체
        fp = 0; fp_trend = 0; ntot = 0
        for r in NEG:
            d = _load(r, "sbas"); alpha = _alpha_for(np.column_stack([d["x"], d["y"]]))
            gi, gti = _grade_int(d, alpha, thr, m)
            fp += int((gi >= 1).sum()); fp_trend += int((gti >= 1).sum()); ntot += len(gi)
        rows.append(dict(method=m,
                         recall=round(hit / len(POS), 3), hit=f"{hit}/{len(POS)}",
                         추세필수케이스=trend_dep,
                         음성FP_combined=fp, 음성FP_추세만=fp_trend,
                         음성FP율=round(fp / ntot, 4)))
    df = pd.DataFrame(rows)
    print("\n" + "=" * 92)
    print("[A-2] 추세(가속) 방법별 recall(양성5)/FP(음성2) — ★최종선택 사용자")
    print("  '추세필수케이스'=추세 빼면 정상되는 양성 수(가속지표 의존도). vel/cum=base 고정.")
    print("=" * 92)
    print(df.to_string(index=False))
    # 케이스별 상세(각 방법이 어떤 양성을 무슨 등급으로 잡는지)
    print("\n[방법×양성케이스 최고등급 (combined / 추세만)]")
    hdr = "case".ljust(22) + "".join(m.ljust(16) for m in methods)
    print(hdr)
    for r in POS:
        line = r.ljust(22)
        for m in methods:
            g, tg, _ = pos_detail[m][r]
            line += f"{_INV[g]}/{_INV[tg]}".ljust(16)
        print(line)
    if save:
        df.to_csv(os.path.join(OUT, "opt_A2_trend_methods.csv"), index=False, encoding="utf-8-sig")
    return df


# =================================================================
# A-1  SBAS 단독 결합규칙(i/ii/iii) + 클러스터(DBSCAN) 판정단위별 recall/FP
# =================================================================
def _cluster_labels(xy, eps_m, min_samples):
    from sklearn.cluster import DBSCAN
    if len(xy) == 0:
        return np.array([], int)
    return DBSCAN(eps=eps_m, min_samples=min_samples).fit(xy).labels_


def _sbas_pack(d, thr, trend_method):
    """SBAS 지역 팩: gi(지표등급),gti(추세등급),rc(누적),subs(침하스크린),xy,tcoh."""
    alpha = _alpha_for(np.column_stack([d["x"], d["y"]]))
    gi, gti = _grade_int(d, alpha, thr, trend_method)
    rc = ind.risk_cumulative(d["disp"], d["years"])
    subs = ind.risk_velocity(d["vel"]) >= CONFIG["sbas"]["screen_vel_mmyr"]
    xy = np.column_stack([d["x"], d["y"]])
    tcoh = np.nan_to_num(d.get("tcoh", np.zeros(len(gi))), nan=0.0)
    return dict(gi=gi, gti=gti, rc=rc, subs=subs, xy=xy, tcoh=tcoh)


def _eff_mask(pk, rule, thr):
    """규칙별 'SBAS 단독 채택' 마스크(effective alarm 후보 = 상위등급이 살아남는 점)."""
    gi, subs, xy = pk["gi"], pk["subs"], pk["xy"]
    alarm = gi >= 1
    cr = CONFIG["combine_rule"]["cand"]; cl = CONFIG["cluster"]
    if rule == "i_standalone":
        return alarm
    if rule == "ii_neighbor":
        p = cr["ii_neighbor"]
        if not subs.any():
            return np.zeros(len(gi), bool)
        cnt = cKDTree(xy[subs]).query_ball_point(xy, p["R_m"], return_length=True)
        return alarm & (np.asarray(cnt) >= p["min_cnt"])
    if rule == "iii_cluster":
        p = cr["iii_cluster"]; eff = np.zeros(len(gi), bool)
        idx = np.where(alarm)[0]
        if len(idx) == 0:
            return eff
        labels = _cluster_labels(xy[idx], cl["eps_m"], cl["min_samples"])
        for lab in set(labels):
            if lab == -1:
                continue
            mem = idx[labels == lab]
            if len(mem) >= p["min_pts"]:
                eff[mem] = True
        return eff
    if rule == "hotspot_rescue":     # 현행(step2) 참조
        sc = CONFIG["sbas"]
        tot = cKDTree(xy).query_ball_point(xy, sc["neighbor_R_m"], return_length=True)
        hot = np.zeros(len(gi), bool)
        if subs.any():
            subc = cKDTree(xy[subs]).query_ball_point(xy, sc["neighbor_R_m"], return_length=True)
            with np.errstate(invalid="ignore", divide="ignore"):
                frac = np.where(np.asarray(tot) > 0, np.asarray(subc) / np.asarray(tot), 0.0)
            hot = subs & (np.asarray(subc) >= sc["neighbor_min_cnt"]) & (frac >= sc["neighbor_min_frac"])
        resc = np.zeros(len(gi), bool)
        if sc.get("rescue_enable", False):
            strong = (pk["gi"] == 2) & ((pk["gti"] == 2) | (pk["rc"] >= thr["cum_danger"]))
            resc = strong & (pk["tcoh"] >= sc.get("rescue_tcoh", 0.7))
        return alarm & (hot | resc)
    return alarm


def sweep_combine_rules(thr=None, save=True):
    thr = thr or CONFIG["thr_base"]
    cl = CONFIG["cluster"]
    rules = ["i_standalone", "ii_neighbor", "iii_cluster", "hotspot_rescue"]
    label = {"i_standalone": "(i)SBAS단독", "ii_neighbor": "(ii)이웃≥N동방향",
             "iii_cluster": "(iii)클러스터≥min_pts", "hotspot_rescue": "현행(hotspot+구제)"}
    # 사전계산: 음성 SBAS 팩, 양성 버퍼 SBAS 팩 + PS 버퍼 등급
    neg_pk = {r: _sbas_pack(_load(r, "sbas"), thr, "2seg") for r in NEG}
    pos_sb = {}; pos_ps_hit = {}
    for r in POS:
        d = _load(r, "sbas"); pos_sb[r] = (_sbas_pack(d, thr, "2seg"), d)
        # 버퍼 마스크(SBAS)
        ev = EVENTS[r]; ex, ey = _TR_M.transform(ev["lon"], ev["lat"])
        pos_sb[r] = (pos_sb[r][0], np.hypot(d["x"] - ex, d["y"] - ey) <= ev["buffer_m"])
        # PS 버퍼 최고등급(참조: 결합 시 PS가 잡는지)
        bs = _buffer_sub(r, "ps", ev["buffer_m"])
        if bs is None:
            pos_ps_hit[r] = 0
        else:
            sub, alpha, asof = bs
            gi, _ = _grade_int(sub, alpha, thr, "2seg", asof=asof)
            pos_ps_hit[r] = int(gi.max()) if len(gi) else 0

    rows = []
    for rule in rules:
        # 양성: SBAS단독 recall + PS결합 recall (클러스터 단위)
        sb_hit = 0; comb_hit = 0
        for r in POS:
            pk, inb = pos_sb[r]
            eff = _eff_mask(pk, rule, thr)
            eff_in = eff & inb
            sb_ok = eff_in.any() and int(pk["gi"][eff_in].max()) >= 1
            sb_hit += int(sb_ok)
            comb_hit += int(sb_ok or pos_ps_hit[r] >= 1)
        # 음성 FP: effective alarm 점 수 + 클러스터 수(판정단위)
        fp_pts = 0; fp_cl = 0; ntot = 0
        for r in NEG:
            pk = neg_pk[r]; eff = _eff_mask(pk, rule, thr)
            fp_pts += int(eff.sum()); ntot += len(pk["gi"])
            if eff.sum():
                lab = _cluster_labels(pk["xy"][eff], cl["eps_m"], cl["min_samples"])
                fp_cl += len(set(lab) - {-1})
        rows.append(dict(rule=label[rule],
                         SBAS단독_recall=f"{sb_hit}/{len(POS)}",
                         PS결합_recall=f"{comb_hit}/{len(POS)}",
                         음성FP_점수=fp_pts, 음성FP_클러스터수=fp_cl,
                         음성FP_점율=round(fp_pts / ntot, 4)))
    df = pd.DataFrame(rows)
    print("\n" + "=" * 96)
    print("[A-1] SBAS 단독 결합규칙별 recall(양성5)/FP(음성2) — 판정단위=DBSCAN 클러스터. ★최종선택 사용자")
    print(f"  DBSCAN eps={cl['eps_m']:.0f}m min_samples={cl['min_samples']} | "
          f"(ii)이웃 R={CONFIG['combine_rule']['cand']['ii_neighbor']['R_m']:.0f}m·N={CONFIG['combine_rule']['cand']['ii_neighbor']['min_cnt']} | "
          f"(iii)클러스터≥{CONFIG['combine_rule']['cand']['iii_cluster']['min_pts']}점")
    print("  SBAS단독_recall=PS 없이 SBAS만으로 잡는 양성 / PS결합_recall=현 2단 결합(PS∪SBAS규칙)")
    print("=" * 96)
    print(df.to_string(index=False))
    print("\n  주: ⑧연희동은 SBAS 버퍼가 정상(천층 노후관)이라 SBAS단독으론 미탐 → PS 확인단계가 recall의 핵심.")
    if save:
        df.to_csv(os.path.join(OUT, "opt_A1_combine_rules.csv"), index=False, encoding="utf-8-sig")
    return df


# =================================================================
# B-1  발생버퍼 반경별 TP + 경보 국소성 + 음성 기대 FP(면적밀도)
# =================================================================
def sweep_buffer(save=True):
    thr = CONFIG["thr_base"]; radii = [100, 150, 200, 250, 500, 1000]
    # 양성: 1000m 내 경보점 거리분포 사전계산(as-of 사고일)
    det = {}
    for r in POS:
        ev = EVENTS[r]; ex, ey = _TR_M.transform(ev["lon"], ev["lat"]); asof = _year(ev["event_date"])
        ad = []
        for kind in ("ps", "sbas"):
            d = _load(r, kind); dist = np.hypot(d["x"] - ex, d["y"] - ey); near = dist <= 1000
            if near.sum() == 0:
                continue
            sub = {k: (v[near] if isinstance(v, np.ndarray) and v.shape[:1] == near.shape else v) for k, v in d.items()}
            alpha = _alpha_for(np.column_stack([sub["x"], sub["y"]]))
            gi, _ = _grade_int(sub, alpha, thr, "2seg", asof=asof)
            ad.append(dist[near][gi >= 1])
        det[r] = np.concatenate(ad) if ad else np.array([])
    # 음성: 경보 면적밀도(경보수/㎢) → 반경별 기대 FP = 밀도×πR²
    from shapely.geometry import MultiPoint
    neg_dens = {}
    for r in NEG:
        d = _load(r, "sbas"); alpha = _alpha_for(np.column_stack([d["x"], d["y"]]))
        gi, _ = _grade_int(d, alpha, thr, "2seg")
        area = MultiPoint(list(map(tuple, np.column_stack([d["x"], d["y"]])))).convex_hull.area
        neg_dens[r] = int((gi >= 1).sum()) / max(area, 1.0)   # 경보/㎡
    rows = []
    for R in radii:
        hit = 0; nn = []
        for r in POS:
            inb = det[r][det[r] <= R]
            if len(inb):
                hit += 1; nn.append(inb.min())
        exp_fp = {r: round(neg_dens[r] * np.pi * R**2, 1) for r in NEG}
        rows.append(dict(buffer_m=R, 양성recall=f"{hit}/{len(POS)}",
                         최근접경보_중앙m=round(float(np.median(nn)), 0) if nn else None,
                         **{f"기대FP_{r.split('_')[0]}": exp_fp[r] for r in NEG}))
    df = pd.DataFrame(rows)
    print("\n" + "=" * 92)
    print("[B-1] 발생버퍼 반경별 recall + 경보 국소성 + 음성 기대FP(면적밀도×πR²) — ★버퍼 최종선택 사용자")
    print("  기대FP=음성지역 경보 면적밀도로 추정한 '동일 반경 버퍼를 임의 배치 시' 기대 경보수.")
    print("=" * 92)
    print(df.to_string(index=False))
    print("\n  주: 양성은 200m 이상 전건 recall 유지(경보가 사고점 부근에 존재). 버퍼↑는 TP 불변·국소성↓·기대FP∝R².")
    if save:
        df.to_csv(os.path.join(OUT, "opt_B1_buffer.csv"), index=False, encoding="utf-8-sig")
    return df


# =================================================================
# B-4  누적변위 산정기간(년)별 recall / FP 민감도
# =================================================================
def sweep_cum_window(save=True):
    thr = CONFIG["thr_base"]; wins = [1.0, 1.5, 2.0, 3.0, 99.0]  # 99=전체스택
    rows = []
    for w in wins:
        hit = 0
        for r in POS:
            ev = EVENTS[r]; gmax = 0
            for kind in ("ps", "sbas"):
                bs = _buffer_sub(r, kind, ev["buffer_m"])
                if bs is None:
                    continue
                sub, alpha, asof = bs
                gi, _ = _grade_int(sub, alpha, thr, "2seg", asof=asof, cum_window=w)
                gmax = max(gmax, int(gi.max()))
            hit += int(gmax >= 1)
        fp = 0; ntot = 0; fp_cum = 0
        for r in NEG:
            d = _load(r, "sbas"); alpha = _alpha_for(np.column_stack([d["x"], d["y"]]))
            gi, _ = _grade_int(d, alpha, thr, "2seg", cum_window=w)
            # 누적단독 경보(누적지표만)
            old = CONFIG["cum_window_years"]; CONFIG["cum_window_years"] = w
            rc = ind.risk_cumulative(d["disp"], d["years"]); CONFIG["cum_window_years"] = old
            gc = ind.subsidence_gate(ind.grade_cumulative(rc, alpha, thr), d["vel"])
            gc_int = np.array([_ORD[x] for x in gc])
            fp += int((gi >= 1).sum()); fp_cum += int((gc_int >= 1).sum())
            ntot += len(gi)
        rows.append(dict(cum_window_yr=("전체" if w == 99.0 else w),
                         양성recall=f"{hit}/{len(POS)}",
                         음성FP_combined=fp, 음성FP_누적만=fp_cum,
                         음성FP율=round(fp / ntot, 4)))
    df = pd.DataFrame(rows)
    print("\n" + "=" * 92)
    print("[B-4] 누적변위 산정기간(년)별 recall(양성5)/FP(음성2) — ★기간 최종선택 사용자")
    print("  현행 2년은 잠정(스택 7년 팽창 방지 목적). 근거표는 README §B-4 참조.")
    print("=" * 92)
    print(df.to_string(index=False))
    if save:
        df.to_csv(os.path.join(OUT, "opt_B4_cum_window.csv"), index=False, encoding="utf-8-sig")
    return df


# =================================================================
# C  발생 vs 미발생 판별자 — 정직한 분리가능성 검증
# =================================================================
def _accel_stats(disp, years, asof=None):
    """점별 (가속도 2a[mm/yr²], t통계 t_a, 2구간 Δv)."""
    tr = CONFIG["trend"]
    prep = ind._trend_prep(disp, years, asof, tr)
    if prep is None:
        return None
    t, s, N, T = prep
    tc = t - t.mean(); X = np.column_stack([tc**2, tc, np.ones(T)])
    XtX_inv = np.linalg.inv(X.T @ X); P = XtX_inv @ X.T
    beta = s @ P.T; a = beta[:, 0]
    resid = s - beta @ X.T; dof = max(1, T - 3); sigma2 = np.sum(resid**2, axis=1) / dof
    se_a = np.sqrt(np.clip(XtX_inv[0, 0] * sigma2, 1e-12, None))
    mid = T // 2
    d2 = ind._seg_slope(t[mid:], s[:, mid:]) - ind._seg_slope(t[:mid], s[:, :mid])
    return 2.0 * a, a / se_a, d2


def _alarm_accel(region, positive):
    """지역 경보점(주의/위험)의 가속통계 수집. 양성=버퍼 as-of PS+SBAS, 음성=SBAS 전체."""
    thr = CONFIG["thr_base"]; acc = []; ta = []; d2 = []
    kinds = ("ps", "sbas") if positive else ("sbas",)
    ev = EVENTS[region]; asof = _year(ev["event_date"]) if positive else None
    if positive:
        ex, ey = _TR_M.transform(ev["lon"], ev["lat"])
    for kind in kinds:
        d = _load(region, kind)
        if positive:
            m = np.hypot(d["x"] - ex, d["y"] - ey) <= ev["buffer_m"]
        else:
            m = np.ones(len(d["vel"]), bool)
        if m.sum() == 0:
            continue
        sub = {k: (v[m] if isinstance(v, np.ndarray) and v.shape[:1] == m.shape else v) for k, v in d.items()}
        alpha = _alpha_for(np.column_stack([sub["x"], sub["y"]]))
        gi, _ = _grade_int(sub, alpha, thr, "2seg", asof=asof)
        al = gi >= 1
        if al.sum() == 0:
            continue
        st = _accel_stats(sub["disp"][al], sub["years"], asof)
        if st is None:
            continue
        acc.append(st[0]); ta.append(st[1]); d2.append(st[2])
    if not acc:
        return None
    return np.concatenate(acc), np.concatenate(ta), np.concatenate(d2)


def discriminator_analysis(save=True):
    amin = CONFIG["trend"].get("quad_accel_min_mmyr2", 1.0)
    rows = []
    groups = [("양성(발생)", POS, True), ("음성-송도", ["Incheon_Songdo"], False),
              ("음성-만덕", ["Busan_Mandeok_Centum"], False)]
    for name, regs, pos in groups:
        A = []; TA = []; D2 = []
        for r in regs:
            st = _alarm_accel(r, pos)
            if st is None:
                continue
            A.append(st[0]); TA.append(st[1]); D2.append(st[2])
        if not A:
            rows.append(dict(group=name, n_경보=0)); continue
        A = np.concatenate(A); TA = np.concatenate(TA); D2 = np.concatenate(D2)
        acc_sig = (TA >= 2.0) & (A >= amin)       # 유의 가속(발산형=붕괴 가설)
        dec_sig = (TA <= -2.0) & (A <= -amin)     # 유의 감속(수렴형=압밀 가설)
        rows.append(dict(group=name, n_경보=len(A),
                         가속도중앙=round(float(np.median(A)), 2),
                         가속도IQR=f"[{np.percentile(A,25):.1f},{np.percentile(A,75):.1f}]",
                         Δv중앙=round(float(np.median(D2)), 2),
                         유의가속_pct=round(float(acc_sig.mean()) * 100, 1),
                         유의감속_pct=round(float(dec_sig.mean()) * 100, 1)))
    df = pd.DataFrame(rows)
    print("\n" + "=" * 96)
    print("[C] 발생 vs 미발생 판별자 — 경보점(주의/위험) 시계열 가속통계 분포비교")
    print("  가설: 발생=발산/가속(가속도>0), 압밀=수렴/감속(가속도<0). 가속도=2a(mm/yr²), Δv=후반−전반 속도.")
    print("=" * 96)
    print(df.to_string(index=False))
    if save:
        df.to_csv(os.path.join(OUT, "opt_C_discriminator.csv"), index=False, encoding="utf-8-sig")
    # 정직한 판정
    print("\n[판정] 위 분포가 겹치면(양성 유의가속%와 음성 유의가속%가 비슷) → '단일 가속임계로 분리 불가'.")
    return df


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("a2", "all"):
        sweep_trend_methods()
    if what in ("a1", "all"):
        sweep_combine_rules()
    if what in ("b1", "all"):
        sweep_buffer()
    if what in ("b4", "all"):
        sweep_cum_window()
    if what in ("c", "all"):
        discriminator_analysis()
