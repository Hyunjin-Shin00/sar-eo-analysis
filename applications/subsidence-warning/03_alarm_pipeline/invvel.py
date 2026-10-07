# -*- coding: utf-8 -*-
"""역속도법(Fukuzono 1985) — 침하 가속 시 1/v 가 시간에 대해 선형 감소하며 0에서 붕괴(t_f).
각 점 시계열 → 최근 속도표본의 1/v 선형적합 → 붕괴예상시점 t_f, 적합도 R², 가속 플래그.
⚠️ 임계치 잠정(pcfg.INVVEL). 부호규약: s=-LOS(침하 양수). vel>0 = 침하."""
import os; os.environ.pop("PYTHONPATH", None)
import warnings
import numpy as np
from scipy.ndimage import median_filter
warnings.filterwarnings("ignore", message="Mean of empty slice")
warnings.filterwarnings("ignore", message="invalid value encountered")
from pcfg import INVVEL                     # SINK를 sys.path에 추가(먼저)
from indicators import _seg_slope          # 기존 검증 슬로프(공유 시간축 최소제곱)


def _prep(disp, years, asof_year):
    """asof 이하 마스크 → s[N,T](침하양수·NaN보간·롤링중앙값 평활), t[T]."""
    m = years <= asof_year if asof_year is not None else np.ones(len(years), bool)
    t = years[m]; s = -disp[:, m].astype(float)
    T = s.shape[1]
    if T < INVVEL["min_series"]:
        return None
    nanrows = np.where(np.isnan(s).any(axis=1))[0]
    idx = np.arange(T)
    for i in nanrows:
        ok = np.isfinite(s[i])
        s[i] = np.interp(idx, idx[ok], s[i][ok]) if ok.sum() >= 2 else 0.0
    sw = INVVEL["smooth_win"]
    if sw > 1:
        s = median_filter(s, size=(1, sw), mode="nearest")   # 롤링중앙값 평활(벡터화)
    return t, s


def _velocity_series(t, s, w):
    """롤링 국소기울기 v(t) [N, nwin], 창중심시각 tc[nwin] (mm/yr, 침하양수)."""
    N, T = s.shape; nwin = T - w + 1
    V = np.empty((N, nwin)); tc = np.empty(nwin)
    for j in range(nwin):
        tt = t[j:j + w]
        V[:, j] = _seg_slope(tt, s[:, j:j + w]); tc[j] = tt.mean()
    return V, tc


def inverse_velocity(disp, years, asof_year=None):
    """반환 dict(len N): v_recent, tf_year, r2, iv_slope, accel, lead_days."""
    N = disp.shape[0]
    z = np.zeros(N)
    empty = {"v_recent": z.copy(), "tf_year": np.full(N, np.nan), "r2": z.copy(),
             "iv_slope": z.copy(), "accel": np.zeros(N, bool), "lead_days": np.full(N, np.nan)}
    prep = _prep(disp, years, asof_year)
    if prep is None:
        return empty
    t, s = prep
    w = INVVEL["vel_win"]
    if s.shape[1] < w + 2:
        return empty
    V, tc = _velocity_series(t, s, w)
    R = min(INVVEL["recent_win"], V.shape[1])
    Vr = V[:, -R:]; tr = tc[-R:]                 # 최근 속도표본
    v_recent = Vr.mean(axis=1)
    floor = INVVEL["iv_floor_mmyr"]
    # 최근 창에서 '지속 침하'(모든 표본 v>=floor)인 점만 역속도 적합(폭주·부호혼재 배제)
    valid = np.all(Vr >= floor, axis=1)
    iv = np.where(Vr >= floor, 1.0 / np.clip(Vr, floor, None), np.nan)   # 1/v (yr/mm 규모)
    tcm = tr - tr.mean(); denom = float(np.sum(tcm ** 2))
    a = np.full(N, np.nan); b = np.full(N, np.nan); r2 = np.zeros(N)
    if denom > 0:
        a = (iv @ tcm) / denom                    # 기울기(밸리드행만 의미)
        b = np.nanmean(iv, axis=1) - a * tr.mean()
        pred = a[:, None] * tr[None, :] + b[:, None]
        ss_res = np.nansum((iv - pred) ** 2, axis=1)
        ss_tot = np.nansum((iv - np.nanmean(iv, axis=1, keepdims=True)) ** 2, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            r2 = np.where(ss_tot > 0, 1.0 - ss_res / ss_tot, 0.0)
    # t_f: iv=0 → t = -b/a, 단 a<0(가속=1/v 하강)
    with np.errstate(invalid="ignore", divide="ignore"):
        tf = np.where(a < 0, -b / a, np.nan)
    lm = INVVEL["late_min_rate_mmyr"]; r2min = INVVEL["r2_min"]
    accel = valid & (a < 0) & (r2 >= r2min) & (v_recent >= lm) & np.isfinite(tf)
    asof = asof_year if asof_year is not None else float(t[-1])
    lead = (tf - asof) * 365.25
    lead = np.where(accel & (lead >= 0) & (lead <= INVVEL["horizon_days_max"]), lead, np.nan)
    accel = accel & np.isfinite(lead)             # 물리적 미래(0~상한)만 가속확정
    return {"v_recent": v_recent, "tf_year": np.where(accel, tf, np.nan), "r2": r2,
            "iv_slope": a, "accel": accel, "lead_days": lead}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "<DATA_ROOT>/analysis/sinkhole")
    import loaders
    reg = sys.argv[1] if len(sys.argv) > 1 else "Yangyang"
    for kind, load in (("PS", loaders.load_ps), ("SBAS", loaders.load_sbas)):
        d = load(reg)
        r = inverse_velocity(d["disp"], d["years"], asof_year=None)
        na = int(r["accel"].sum())
        print(f"{reg} {kind}: n={len(d['vel'])} 가속확정={na} "
              f"({100*na/max(1,len(d['vel'])):.2f}%)")
        if na:
            j = np.nanargmin(r["lead_days"])
            print(f"   최단 t_f 리드={r['lead_days'][j]:.0f}일 R²={r['r2'][j]:.2f} v_recent={r['v_recent'][j]:.1f}mm/yr")
