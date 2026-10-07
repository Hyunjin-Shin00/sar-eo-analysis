#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""지점 등급 판정 — 정상 / 주의 / 위험 — 부산 사상~하단

입력  : input/Busan_Sasang_Hadan_sbas_ps_v.csv   SBAS 시계열
        input/rule_grade.json                    판정 규칙(임계·연속횟수)
        input/rule_grade_bg.npz                  배경 30곳 분포(백분위 기준)
출력  : 표준출력 판정표 + (--out 지정 시) JSON

판정 두 단계
  ① 주의 구역 선별 - 최근 1년 침하량과 침하 가속을 이 지역 배경 분포 대비 백분위로 바꿔
     평균이 임계 이상이면 진입. **한 번 진입하면 유지**된다.
  ② 위험 경보 - 선별 진입 이후 구간에서 세 조건을 동시에 넘는 상태가 K회 관측 연속이면 발령.
     기준일 시점에 성립하면 '위험'.

  정상 = 선별 미진입 · 주의 = 선별 진입 · 위험 = 기준일에 경보 성립

전처리(언래핑 보정·공통모드 보정)와 지표 정의는 apply_risk_rule.py 와 같은 함수를 쓴다.
외부 의존 없이 이 폴더만으로 재현된다.

usage: python3 grade_point.py --lat 35.149025 --lon 128.981094 [--asof 2024-06-30] [--out J.json]
"""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "2")
import sys, json, time, argparse, datetime
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ── 전처리·지표 함수 (운영 파이프라인 loaders.py · discrim_eval.py 와 동일) ──
def log(m, t0=None):
    print("[%s] %s%s" % (time.strftime("%H:%M:%S"), m,
                         "" if t0 is None else "  (+%.1fs)" % (time.time() - t0)), flush=True)


# ───────────────────────────────────── PROJ 전처리 (loaders.py 동일)


def deunwrap(disp, p):
    """언래핑 오류 억제: 국소 시간중앙값 대비 잔차가 λ/2 정수배이고 MAD 게이트를 넘는 점프만 되돌림."""
    from scipy.ndimage import median_filter
    d = disp.astype(float); N, T = d.shape
    if T < 3 or N == 0:
        return disp
    finite = np.isfinite(d)
    rowmed = np.nanmedian(np.where(finite, d, np.nan), axis=1, keepdims=True)
    rowmed = np.where(np.isfinite(rowmed), rowmed, 0.0)
    base = median_filter(np.where(finite, d, rowmed), size=(1, p["win"]), mode="nearest")
    resid = d - base; absr = np.abs(resid)
    mad = np.nanmedian(np.where(finite, absr, np.nan), axis=1, keepdims=True)
    scale = np.clip(1.4826 * np.where(np.isfinite(mad), mad, p["scale_floor_mm"]),
                    p["scale_floor_mm"], None)
    n = np.round(np.where(finite, resid / p["cycle_mm"], 0.0))
    mask = (finite & (n != 0) & (np.abs(n) <= p["max_n"])
            & (np.abs(resid - n * p["cycle_mm"]) <= p["tol_mm"]) & (absr > p["outlier_k"] * scale))
    if mask.any():
        d = np.where(mask, d - n * p["cycle_mm"], d)
    return d.astype(np.float32), int(mask.sum())


def cmc(disp, vel):
    """공통모드 보정: 에폭별 전점 중앙값 시계열·중앙값 속도 차감(사상 지정 지역)."""
    d = disp.astype(float)
    cm = np.nanmedian(d, axis=0)
    if np.isnan(cm).any():
        ok = np.isfinite(cm); i = np.arange(len(cm))
        cm = np.interp(i, i[ok], cm[ok]) if ok.sum() >= 2 else np.nan_to_num(cm)
    return (d - cm[None, :]).astype(np.float32), vel - float(np.nanmedian(vel))


def cum_window(disp, years, win, k=3, asof=None):
    """최근 win년 강건 누적침하(mm, 침하=양수). discrim_eval.cum_window 동일.
    asof 를 주면 그 시점 이하 관측만 사용(과거 시점 재현)."""
    yend = years[-1] if asof is None else float(asof)
    m = (years <= yend) & (years >= yend - win) if win else (years <= yend)
    if m.sum() < 2 * k:
        m = years <= yend
    d = disp[:, m]; T = d.shape[1]
    kk = min(k, max(1, T // 2))
    return -(np.nanmedian(d[:, -kk:], axis=1) - np.nanmedian(d[:, :kk], axis=1))


# ───────────────────────────────────── 규칙 적용


def pctl(v, bg_sorted, flip):
    """배경분포 대비 백분위(동점은 중앙). featx/searchx 와 동일."""
    B = np.asarray(bg_sorted, float)
    p = (np.searchsorted(B, v, "left") + np.searchsorted(B, v, "right")) / (2.0 * len(B))
    return 1 - p if flip else p


BASE = os.path.dirname(HERE)


def _pick(*cands):
    """demo/03_risk 배치와 sasang_yearly_risk/code 배치 양쪽에서 동작하게 경로를 고른다."""
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


CSVNAME = "Busan_Sasang_Hadan_sbas_ps_v.csv"
DEF_SBAS = _pick(os.path.join(BASE, "02_sbas", "out", CSVNAME),
                 os.path.join(BASE, "02_sbas", "precomputed", CSVNAME))
RULE = os.path.join(HERE, "rule_grade.json")
BG = os.path.join(HERE, "rule_grade_bg.npz")
DAYS = 365.25
CRS_M = 32652                       # UTM 52N

KR = {"cum1": "최근 1년 침하량", "dv": "침하 가속",
      "cumF_d3": "최근 약 36일 사이에 늘어난 관측 시작 이후 총 침하량",
      "cum1_d1": "최근 약 12일 사이에 늘어난 최근 1년 침하량",
      "cumF_z3": "최근 약 36일 사이의 총 침하량 변화폭 (평소 변동폭의 몇 배인지)"}
UNIT = {"cumF_d3": "mm", "cum1_d1": "mm", "cumF_z3": "배"}


def y2d(y):
    yy = int(y)
    return (datetime.date(yy, 1, 1) + datetime.timedelta(days=round((y - yy) * DAYS))).isoformat()


def trend_dv(disp, years, asof, smooth_win=5, min_series=12):
    """전·후반 2구간 강건기울기 차이(mm/년). indicators.trend_grade(2seg) 와 동일."""
    m = years <= asof
    t = years[m]
    s = -disp[:, m].astype(float)                      # 침하 양수
    T = s.shape[1]
    if T < min_series:
        return np.zeros(s.shape[0])
    bad = np.where(np.isnan(s).any(axis=1))[0]
    if len(bad):
        idx = np.arange(T)
        for i in bad:
            row = s[i]; ok = np.isfinite(row)
            s[i] = np.interp(idx, idx[ok], row[ok]) if ok.sum() >= 2 else 0.0
    if smooth_win > 1:
        pad = smooth_win // 2
        sm = np.copy(s)
        for j in range(T):
            sm[:, j] = np.median(s[:, max(0, j - pad):min(T, j + pad + 1)], axis=1)
        s = sm

    def slope(tt, ss):
        tb = tt.mean(); den = np.sum((tt - tb) ** 2)
        return np.zeros(ss.shape[0]) if den <= 0 else ss @ ((tt - tb) / den)

    mid = T // 2
    return slope(t[mid:], s[:, mid:]) - slope(t[:mid], s[:, :mid])


def derive(F, name, j):
    """<지표>_d창 / <지표>_z창 값. 창이 모자라면 NaN."""
    b, suf = name.split("_")
    m = int(suf[1:]); v = F[b]
    if j - m < 0:
        return np.nan
    if suf[0] == "d":
        return v[j] - v[j - m]
    w = v[j - m:j]
    mu, sd = np.nanmean(w), np.nanstd(w)
    return np.nan if not np.isfinite(sd) or sd <= 1e-6 else (v[j] - mu) / sd


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--asof", default=None, help="판정 기준일 YYYY-MM-DD (기본: 최종 관측)")
    p.add_argument("--sbas", default=DEF_SBAS)
    p.add_argument("--out", default=None, help="판정 결과 JSON 경로")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args()

    R = json.load(open(RULE))
    G, AL = R["gate"], R["alarm"]
    Rbuf = float(R["config"]["buffer_m"])
    bg = np.load(BG)

    zr = {"preprocess": R["preprocess"]}
    df = pd.read_csv(a.sbas)
    dcols = [c for c in df.columns if c.startswith("D") and len(c) == 9 and c[1:].isdigit()]
    years = np.array([int(c[1:5]) + (pd.Timestamp(int(c[1:5]), int(c[5:7]), int(c[7:9]))
                                     - pd.Timestamp(int(c[1:5]), 1, 1)).days / DAYS for c in dcols])
    lon = df.Longitude.to_numpy(float); lat = df.Latitude.to_numpy(float)
    vel = df.velocity.to_numpy(float); disp = df[dcols].to_numpy(np.float32)
    disp, nfix = deunwrap(disp, zr["preprocess"]["deunwrap"])
    disp, vel = cmc(disp, vel)

    if a.asof:
        d0 = datetime.date.fromisoformat(a.asof)
        av = d0.year + (d0 - datetime.date(d0.year, 1, 1)).days / DAYS
    else:
        av = float(years[-1])
    m_as = years <= av + 1e-9
    years, disp = years[m_as], disp[:, m_as]
    if not a.quiet:
        log("SBAS %d점 · %d에폭 (~%s) · 언래핑보정 %d · CMC 적용"
            % (len(df), len(years), y2d(float(years[-1])), nfix))

    # ── 반경 400 m 버퍼 ──
    from pyproj import Transformer
    tr = Transformer.from_crs(4326, CRS_M, always_xy=True)
    X, Y = tr.transform(lon, lat)
    px, py = tr.transform(a.lon, a.lat)
    d2 = (X - px) ** 2 + (Y - py) ** 2
    idx = np.where(d2 <= Rbuf * Rbuf)[0]
    if len(idx) == 0:
        sys.exit("반경 %.0fm 내 관측점이 없습니다." % Rbuf)
    D = disp[idx]
    if not a.quiet:
        log("반경 %.0fm 관측점 %d점" % (Rbuf, len(idx)))

    # ── 에폭별 지표(버퍼 최댓값) ──
    j0 = int(R["min_epochs"]) - 1
    T = len(years)
    if T <= j0:
        sys.exit("관측이 %d회뿐이라 판정할 수 없습니다(최소 %d회)." % (T, R["min_epochs"]))
    F = {"cum1": np.full(T, np.nan), "cumF": np.full(T, np.nan), "dv": np.full(T, np.nan)}
    for j in range(j0, T):
        tj = float(years[j])
        F["cum1"][j] = np.nanmax(cum_window(D, years, R["cum_window"]["cum1_years"], asof=tj))
        F["cumF"][j] = np.nanmax(cum_window(D, years, None, asof=tj))
        F["dv"][j] = np.nanmax(trend_dv(D, years, tj, R["trend"]["smooth_win"], R["trend"]["min_series"]))

    # ── ① 주의 구역 선별 ──
    P = np.column_stack([pctl(F[f], bg[f], G["flips"][f]) for f in G["features"]])
    P[:j0] = np.nan
    import warnings
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")            # 앞쪽 창부족 구간은 전부 NaN
        score = np.nanmean(P, axis=1) if G["comb"] == "mean" else np.nanmin(P, axis=1)
    TH = float(G["threshold"])
    gok = np.nan_to_num(score, nan=-1e18) >= TH
    gj = int(np.argmax(gok)) if gok.any() else -1
    entered = gj >= 0

    # ── ② 위험 경보 ── (선별 진입 시점 이후 구간에서 파생값 산출)
    gcol = gj if gj >= 0 else j0
    Fs = {k: v[gcol:] for k, v in F.items()}
    ts = years[gcol:]
    K = int(AL["K"])
    okv, run, fires, first = [], 0, [], -1
    for i in range(len(ts)):
        hit = True
        for nm, th in AL["rule"]:
            v = derive(Fs, nm, i)
            hit &= np.isfinite(v) and v >= float(th)
        okv.append(hit)
        run = run + 1 if hit else 0
        if run >= K:
            fires.append(float(ts[i]))
            if first < 0:
                first = i
    inst = bool(len(okv) >= K and all(okv[-K:]))
    grade = "위험" if inst else ("주의" if entered else "정상")

    conds = []
    for nm, th in AL["rule"]:
        v = derive(Fs, nm, len(ts) - 1)
        conds.append({"항목": KR.get(nm, nm), "feature": nm, "기준값": float(th),
                      "실측값": None if not np.isfinite(v) else round(float(v), 3),
                      "충족": bool(np.isfinite(v) and v >= float(th)), "단위": UNIT.get(nm, "")})

    res = {
        "lat": a.lat, "lon": a.lon, "asof": y2d(av), "obs_end": y2d(float(years[-1])),
        "n_epoch": T, "n_buffer_point": int(len(idx)), "buffer_m": Rbuf,
        "grade": grade,
        "gate": {"entered": entered, "first": None if gj < 0 else y2d(float(years[gj])),
                 "score_now": None if not np.isfinite(score[-1]) else round(float(score[-1]), 3),
                 "threshold": TH,
                 "pct_now": {f: (None if not np.isfinite(P[-1, i]) else round(float(P[-1, i]), 3))
                             for i, f in enumerate(G["features"])}},
        "alarm": {"instant": inst, "fired": first >= 0, "K": K,
                  "first": None if first < 0 else y2d(float(ts[first])),
                  "last_fire": y2d(fires[-1]) if fires else None,
                  "n_fire_epoch": len(fires), "conditions": conds},
    }
    if a.out:
        json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=2)

    if not a.quiet:
        print()
        print("  기준일 %s (최종 반영 관측 %s · %d회)" % (res["asof"], res["obs_end"], T))
        print("  ── 판정 %s ──" % grade)
        print()
        print("  ① 주의 구역 선별  %s" % ("진입 (%s)" % res["gate"]["first"] if entered else "미진입"))
        for i, f in enumerate(G["features"]):
            print("       %-14s 상위 순위 %s" % (KR.get(f, f), res["gate"]["pct_now"][f]))
        print("       결합 점수 %s (기준 %.5f) → %s"
              % (res["gate"]["score_now"], TH, "성립" if (score[-1] >= TH) else "미성립"))
        print()
        print("  ② 위험 경보  %s · %d회 관측 연속 필요" % ("성립" if inst else "미성립", K))
        for c in conds:
            print("       %-52s 기준 %6.3f · 실측 %9s · %s"
                  % (c["항목"][:52], c["기준값"],
                     "-" if c["실측값"] is None else c["실측값"], "충족" if c["충족"] else "미충족"))
        print()
    else:
        print(grade)
    return 0


if __name__ == "__main__":
    sys.exit(main())
