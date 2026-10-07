# -*- coding: utf-8 -*-
"""
변위 3지표 산정 (STEP2)  [6·22 자료 p.7]
부호규약: LOS 침하 = 음(-). 위험도는 '침하 크기'(양수)로 환산.
  · risk_vel = -velocity            (mm/yr, 양수=침하)
  · risk_cum = 관측창 내 최대 침하량 = max_t(-(disp - disp_base))  (mm)
  · trend    = 롤링 국소기울기의 최근 연속 가속 횟수 → 등급
지표별 α 적용: threshold_adj = base × α (연약일수록 낮은 변위에서 상위등급)
"""
import numpy as np
from config import CONFIG


# ---------- 관측창(as-of) 마스크 ----------
def asof_mask(years, asof_year=None):
    """asof_year 이하 관측만 True. None이면 전체."""
    if asof_year is None:
        return np.ones(len(years), bool)
    return years <= asof_year


# ---------- 3지표 원시값 ----------
def risk_velocity(vel):
    """침하속도(mm/yr, 양수=침하)."""
    return -np.asarray(vel, float)


def risk_cumulative(disp, years, asof_year=None):
    """최근 고정창(cum_window_years) 내 강건 net 침하량(mm, 양수=침하).
    = median(창끝 k) - median(창시작 k). 스택기간 정합성 확보(장기스택 팽창 방지)."""
    k = CONFIG.get("cum_robust_k", 3)
    win = CONFIG.get("cum_window_years", 2.0)
    yend = asof_year if asof_year is not None else years[-1]
    m = (years <= yend) & (years >= yend - win)
    if m.sum() < 2 * k:                     # 창 관측 부족 시 창 시작 완화
        m = years <= yend
    d = disp[:, m]
    T = d.shape[1]
    if T == 0:
        return np.full(disp.shape[0], np.nan)
    kk = min(k, max(1, T // 2))
    with np.errstate(invalid="ignore"):
        start = np.nanmedian(d[:, :kk], axis=1)
        end = np.nanmedian(d[:, -kk:], axis=1)
    return -(end - start)                   # 침하(누적 감소) → 양수


def _seg_slope(t, s):
    """시간축 t 공유 구간의 최소제곱 기울기(각 점) [N]. s:[N,L]."""
    tb = t.mean()
    denom = np.sum((t - tb) ** 2)
    if denom <= 0:
        return np.zeros(s.shape[0])
    w = (t - tb) / denom
    return s @ w


def _rolling_slopes(disp, years, asof_year=None):
    """
    각 점의 시계열에서 에폭별 국소기울기(mm/yr) 행렬 반환 [N, T'].
    창=slope_win 관측(같은 시간축→가중치 공유). 침하양수(s=-disp) 기준.
    NaN은 선형보간으로 메움(누적변위는 평활).
    """
    return None  # (구 sliding-window 방식 폐기 — 2구간 방식 trend_grade 사용)


def _trend_prep(disp, years, asof_year, tr):
    """추세 공통 전처리 → (t[T'], s[N,T'] 침하양수·NaN보간·평활, N, T). T<min_series면 None."""
    N = disp.shape[0]
    m = asof_mask(years, asof_year)
    t = years[m]; s = -disp[:, m].astype(float)          # 침하 양수
    T = s.shape[1]
    if T < tr["min_series"]:
        return None
    nanrows = np.where(np.isnan(s).any(axis=1))[0]
    if len(nanrows):
        idx = np.arange(T)
        for i in nanrows:
            row = s[i]; ok = np.isfinite(row)
            s[i] = np.interp(idx, idx[ok], row[ok]) if ok.sum() >= 2 else 0.0
    sw = tr["smooth_win"]
    if sw > 1:
        pad = sw // 2
        sm = np.copy(s)
        for j in range(T):
            lo = max(0, j - pad); hi = min(T, j + pad + 1)
            sm[:, j] = np.median(s[:, lo:hi], axis=1)
        s = sm
    return t, s, N, T


def _core_2seg(t, s, tr):
    """[기본·현행] 전/후반 2구간 강건 기울기 비교. 반환 (grade,v_late,v_early)."""
    N, T = s.shape; mid = T // 2
    grade = np.array(["정상"] * N, dtype=object)
    v_early = _seg_slope(t[:mid], s[:, :mid]); v_late = _seg_slope(t[mid:], s[:, mid:])
    delta = v_late - v_early; lm = tr["late_min_rate_mmyr"]
    grade[(v_late >= lm) & (delta >= tr["accel_delta_watch_mmyr"])] = "주의"
    grade[(v_late >= lm) & (delta >= tr["accel_delta_danger_mmyr"])] = "위험"
    return grade, v_late, v_early


def _core_slidewin(t, s, tr):
    """[후보①] 이동창 회귀로 국소속도 시계열 v(t) 추적 → 최근창 v_late vs 전반 v_early.
    중간점 위치에 둔감(2구간의 임계 민감성 완화). 임계는 2구간과 동일."""
    N, T = s.shape
    W = min(int(tr.get("slide_win", 8)), T)
    nwin = T - W + 1
    grade = np.array(["정상"] * N, dtype=object)
    if nwin < 2:
        return _core_2seg(t, s, tr)
    V = np.empty((N, nwin))
    for w in range(nwin):
        V[:, w] = _seg_slope(t[w:w + W], s[:, w:w + W])
    h = max(1, nwin // 2); tail = max(1, nwin // 3)
    v_early = np.median(V[:, :h], axis=1)
    v_late = np.median(V[:, -tail:], axis=1)
    delta = v_late - v_early; lm = tr["late_min_rate_mmyr"]
    grade[(v_late >= lm) & (delta >= tr["accel_delta_watch_mmyr"])] = "주의"
    grade[(v_late >= lm) & (delta >= tr["accel_delta_danger_mmyr"])] = "위험"
    return grade, v_late, v_early


def _core_quad(t, s, tr):
    """[후보②] 2차항 회귀 s=a·t²+b·t+c. 가속도=2a(mm/yr²), 유의성 t=a/se(a) 검정.
    a>0(볼록=가속침하) AND |가속도|≥floor AND t통계≥임계 AND 최근침하율≥late_min → 상위등급."""
    N, T = s.shape
    grade = np.array(["정상"] * N, dtype=object)
    tc = t - t.mean()
    X = np.column_stack([tc**2, tc, np.ones(T)])          # 공유 설계행렬
    XtX_inv = np.linalg.inv(X.T @ X)
    P = XtX_inv @ X.T                                     # [3,T]
    beta = s @ P.T                                        # [N,3]  (a,b,c)
    a = beta[:, 0]
    resid = s - beta @ X.T
    dof = max(1, T - 3)
    sigma2 = np.sum(resid**2, axis=1) / dof
    se_a = np.sqrt(np.clip(XtX_inv[0, 0] * sigma2, 1e-12, None))
    t_a = a / se_a
    accel = 2.0 * a                                       # d²s/dt² (mm/yr²)
    # 최근 1/3 구간 침하율(노이즈 바닥 late_min)
    third = max(2, T // 3)
    v_late = _seg_slope(t[-third:], s[:, -third:])
    amin = tr.get("quad_accel_min_mmyr2", 1.0); lm = tr["late_min_rate_mmyr"]
    base = (accel >= amin) & (v_late >= lm)
    grade[base & (t_a >= tr.get("quad_t_watch", 2.0))] = "주의"
    grade[base & (t_a >= tr.get("quad_t_danger", 3.0))] = "위험"
    return grade, v_late, accel


def _core_inflection(t, s, tr):
    """[후보③] 3구간 단조가속(v1≤v2≤v3, 곡률 상향=변곡) 탐지. 계단형·일시노이즈 배제에 강함.
    v3≥late_min AND (v3−v1)≥delta → 상위등급."""
    N, T = s.shape; k = max(2, T // 3)
    grade = np.array(["정상"] * N, dtype=object)
    v1 = _seg_slope(t[:k], s[:, :k])
    v2 = _seg_slope(t[k:2 * k], s[:, k:2 * k])
    v3 = _seg_slope(t[2 * k:], s[:, 2 * k:])
    mono = (v3 >= v2) & (v2 >= v1); delta = v3 - v1; lm = tr["late_min_rate_mmyr"]
    dw = tr.get("infl_delta_watch_mmyr", tr["accel_delta_watch_mmyr"])
    dd = tr.get("infl_delta_danger_mmyr", tr["accel_delta_danger_mmyr"])
    grade[mono & (v3 >= lm) & (delta >= dw)] = "주의"
    grade[mono & (v3 >= lm) & (delta >= dd)] = "위험"
    return grade, v3, v1


_TREND_CORES = {"2seg": _core_2seg, "slidewin": _core_slidewin,
                "quad": _core_quad, "inflection": _core_inflection}


def trend_grade(disp, years, asof_year=None, thr=None, method=None):
    """
    추세(가속) 등급. method(기본=CONFIG['trend']['method']='2seg')로 알고리즘 선택:
      · 2seg      : 전/후반 2구간 강건기울기 비교(현행)
      · slidewin  : 이동창 회귀 국소속도 v(t) 추적(중간점 민감성 완화)
      · quad      : 2차항 가속도계수 + t검정(유의성)
      · inflection: 3구간 단조가속(계단형/일시노이즈 배제)
    ⚠️ 최종 방법 확정 전 잠정. 방법별 recall/FP는 analyze_options.py 비교표 참조.
    반환 dict(grade[N], v_late[N], v_early[N]).  (quad는 v_early 자리에 가속도 accel)
    """
    tr = CONFIG["trend"]
    method = method or tr.get("method", "2seg")
    N = disp.shape[0]
    prep = _trend_prep(disp, years, asof_year, tr)
    if prep is None:
        z = np.zeros(N)
        return {"grade": np.array(["정상"] * N, dtype=object), "v_late": z, "v_early": z}
    t, s, N, T = prep
    core = _TREND_CORES.get(method, _core_2seg)
    grade, v_late, v_early = core(t, s, tr)
    return {"grade": grade, "v_late": v_late, "v_early": v_early}


# ---------- 지표별 등급 (α 적용) ----------
_ORDER = {"정상": 0, "주의": 1, "위험": 2}


def grade_velocity(risk_vel, alpha, thr=None):
    t = thr or CONFIG["thr_base"]
    a = np.asarray(alpha, float)
    g = np.array(["정상"] * len(risk_vel), dtype=object)
    rv = np.asarray(risk_vel, float)
    g[rv >= t["vel_watch"] * a] = "주의"
    g[rv >= t["vel_danger"] * a] = "위험"
    g[rv >= t["vel_immediate"] * a] = "위험"   # 30초과 즉시위험
    return g


def grade_cumulative(risk_cum, alpha, thr=None):
    t = thr or CONFIG["thr_base"]
    a = np.asarray(alpha, float)
    g = np.array(["정상"] * len(risk_cum), dtype=object)
    rc = np.asarray(risk_cum, float)
    g[rc >= t["cum_watch"] * a] = "주의"
    g[rc >= t["cum_danger"] * a] = "위험"
    return g


def subsidence_gate(grades, vel):
    """CONFIG['subsidence_only']이면 비침하(vel>=0) 점 등급을 '정상'으로 강제. 침하(vel<0)만 상위등급."""
    if not CONFIG.get("subsidence_only", False):
        return grades
    g = np.array(grades, dtype=object).copy()
    g[np.asarray(vel, float) >= 0] = "정상"
    return g


def combine_max(*grades):
    """여러 등급 배열 중 원소별 최고위험(보수적) 채택."""
    grades = [np.asarray(g, dtype=object) for g in grades]
    N = len(grades[0])
    out = np.array(["정상"] * N, dtype=object)
    best = np.zeros(N, int)
    for g in grades:
        v = np.array([_ORDER.get(x, 0) for x in g])
        out = np.where(v > best, g, out)
        best = np.maximum(best, v)
    return out


def which_indicator(gv, gc, gt):
    """최종등급 근거지표 라벨(가장 높은 등급을 준 지표들)."""
    N = len(gv)
    labels = []
    for i in range(N):
        vs = {"속도": _ORDER[gv[i]], "누적": _ORDER[gc[i]], "추세": _ORDER[gt[i]]}
        mx = max(vs.values())
        if mx == 0:
            labels.append("-")
        else:
            labels.append("+".join([k for k, v in vs.items() if v == mx]))
    return np.array(labels, dtype=object)
