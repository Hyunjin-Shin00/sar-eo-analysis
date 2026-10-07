# -*- coding: utf-8 -*-
"""
PS/SBAS/시추공 통합 지도 생성 (Option D: 지역별 7맵 + 허브 1개).
기존 clickmap(Leaflet 1.9.4, circleMarker+RdBu+시계열 SVG)을 계승·확장.
 · 3레이어 독립 체크박스(PS/SBAS/시추공)  · 등급팝업  · 임계치표(접기)  · 허브 사이드바+리포트
출력: <DATA_ROOT>/CLAB/integrated_maps/CLAB_통합맵.html (허브) + <DATA_ROOT>/CLAB/integrated_maps/통합맵/{region}.html
⚠️ 임계치·α 잠정값. 리포트는 앞 분석(step2/3) 결과값만 사용.
"""
import os as _os
_CR = _os.environ.get("CLAB_ROOT") or _os.path.abspath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", ".."))   # 전달본 상대경로

import os
os.environ.pop("PYTHONPATH", None)
import json, warnings
import numpy as np, pandas as pd
from scipy.ndimage import median_filter
warnings.filterwarnings("ignore", message="Mean of empty slice")
warnings.filterwarnings("ignore", message="invalid value encountered")
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir(); os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]

from config import CONFIG, REGIONS, QUAD3_INSAR_LIMIT
import loaders, indicators as ind
import step2_fusion as s2
import geol_grade as geol
from events import EVENTS

GGO = {"양호": 0, "주의": 1, "연약": 2, "미상": 3}   # 융합 지반등급 코드
GGCOL = {"양호": "#27ae60", "주의": "#e67e22", "연약": "#c0392b"}

OUT_DIR = os.path.join(CONFIG["paths"]["clab_base"], "integrated_maps")  # 2026-07-19: 허브/지역맵 출력 위치
MAP_DIR = os.path.join(OUT_DIR, "통합맵")
OUTC = CONFIG["paths"]["out_dir"]
os.makedirs(MAP_DIR, exist_ok=True)
_O = {"정상": 0, "주의": 1, "위험": 2}
GLABEL = {0: "정상", 1: "주의", 2: "위험"}
BORE_O = {"양호": 0, "주의": 1, "연약": 2}   # 시추공 지반등급(0=양호 녹/1=주의 주황/2=연약 적)
TRLABEL = {0: "등속·감속", 1: "가속전환 의심", 2: "가속확정"}
SOIL_KO = {"cohesive": "점성토", "sandy": "사질토", "rock": "암반", "other": "기타"}

# 4분면 그룹 라벨
GROUP = {"positive": "양성", "positive_shallow": "③분면(천층)", "negative": "음성"}

# AOI.xlsx SNWE (S, N, W, E) — 시추공 표시 범위(#1)
AOI_SNWE = {
    "Seoul_Gangdong":       (37.5097, 37.5840, 127.1033, 127.1994),
    "Seoul_Seodaemun":      (37.5407, 37.5977, 126.8844, 126.9636),
    "Gyeonggi_Gwangmyeong": (37.3812, 37.4442, 126.8410, 126.9181),
    "Incheon_Songdo":       (37.3584, 37.4329, 126.5959, 126.7164),
    "Busan_Mandeok_Centum": (35.1644, 35.2508, 129.0092, 129.1379),
    "Busan_Sasang_Hadan":   (35.1294, 35.1664, 128.9677, 129.0049),
    "Yangyang":             (38.0596, 38.1536, 128.5469, 128.6751),
}

# 같은 지역맵에 다른 궤도(하강/DSC) 결과를 별도 토글 레이어로 겹쳐 표시(기존 상승 레이어 불변).
#  region -> DSC 형제 region(폴더/로더 규칙 {clab_base}/{region}/... 그대로 사용)
DSC_SIBLING = {"Incheon_Songdo": "Incheon_Songdo_DSC"}

# 전국 지반침하 사고 리스트(국토안전관리원 Open API → 주소 지오코딩본). AOI bbox 내 사고만 표출.
SUBSIDENCE_CSV = _CR + "/auxiliary/subsidence_list/subsidence_accidents_geocoded.csv"


def load_subsidence_in_bbox(region):
    """지반침하 사고 리스트에서 해당 AOI(AOI_SNWE) bbox 내 사고만 반환(표시용 레이어; 위험판정 불변)."""
    if region not in AOI_SNWE or not os.path.exists(SUBSIDENCE_CSV):
        return []
    S, N, W, E = AOI_SNWE[region]
    try:
        df = pd.read_csv(SUBSIDENCE_CSV, encoding="utf-8-sig", dtype=str)
    except Exception as e:
        print(f"  [지반침하 리스트 경고] {region}: {e}")
        return []

    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    def _i(x):
        try:
            return int(float(x))
        except (TypeError, ValueError):
            return 0

    def _esc(x):
        x = "" if x is None else str(x).strip()
        if x.lower() == "nan":
            x = ""
        return x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def _date(x):
        x = "" if x is None else str(x).strip()
        return f"{x[0:4]}-{x[4:6]}-{x[6:8]}" if len(x) == 8 and x.isdigit() else x

    out = []
    for _, r in df.iterrows():
        la, lo = _f(r.get("lat")), _f(r.get("lon"))
        if la is None or lo is None:
            continue
        if not (S <= la <= N and W <= lo <= E):
            continue
        loc = " ".join(t for t in [_esc(r.get("siGunGu")), _esc(r.get("dong")), _esc(r.get("addr"))] if t)
        out.append({
            "lat": round(la, 6), "lon": round(lo, 6),
            "no": _esc(r.get("sagoNo")), "date": _date(r.get("sagoDate")), "loc": loc,
            "w": _f(r.get("sinkWidth")), "l": _f(r.get("sinkExtend")), "d": _f(r.get("sinkDepth")),
            "grd": _esc(r.get("grdKind")),
            "death": _i(r.get("deathCnt")), "injury": _i(r.get("injuryCnt")), "veh": _i(r.get("vehicleCnt")),
            "status": _esc(r.get("trStatus")), "detail": _esc(r.get("sagoDetail")),
            "gtype": _esc(r.get("geocodeType")),
        })
    return out


# ---------------- 시각화 평활·미분·변곡점(전조 개시) — 표시/탐지용, 위험판정 원본 불변 ----------------
def _mv():
    return CONFIG.get("map_viz", {})


def smooth_series(y, method=None, win=None):
    """중앙값→이동평균(강건) 평활. y=1D(결측 없음 가정). 반환 동일길이 배열."""
    mv = _mv(); method = method or mv.get("smooth_method", "median_then_ma"); win = int(win or mv.get("smooth_window", 7))
    y = np.asarray(y, float); T = len(y); pad = win // 2
    out = y.copy()
    if method in ("median", "median_then_ma"):
        m = y.copy()
        for j in range(T):
            m[j] = np.median(y[max(0, j - pad):min(T, j + pad + 1)])
        out = m
    if method in ("ma", "median_then_ma"):
        base = out.copy(); o = base.copy()
        for j in range(T):
            o[j] = np.mean(base[max(0, j - pad):min(T, j + pad + 1)])
        out = o
    return out


def _seg_slope_local(t, y, i, seg, side):
    """i 기준 side('before'/'after') seg관측 구간 최소제곱 기울기(mm/yr)."""
    lo, hi = (max(0, i - seg + 1), i + 1) if side == "before" else (i, min(len(t), i + seg))
    if hi - lo < 2:
        return np.nan
    tt = t[lo:hi]; yy = y[lo:hi]; tb = tt.mean(); den = float(np.sum((tt - tb) ** 2))
    return float(np.sum((tt - tb) * yy) / den) if den > 0 else np.nan


def detect_inflection(disp_row, years, viz=None):
    """평활 누적변위 s=-disp의 침하개시(변곡) 후보 탐지 — 기울기 변화폭 Δv 기준(강건).
    후보 = 후반 침하율>=late_min(침하로 전환) AND 전반 미침하(<late_min) AND Δv>=vjump(또는 accel>=).
    근접후보 병합·강도순 top_n. 반환 list[dict(idx,delta_v,accel,v_before,v_after,strength)]."""
    viz = viz or _mv()
    y = np.asarray(disp_row, float); ok = np.isfinite(y)
    seg = int(viz.get("infl_seg", 5))
    if ok.sum() < max(8, 2 * seg):
        return []
    y = np.interp(np.arange(len(y)), np.where(ok)[0], y[ok])
    s = -y                                    # 침하 양수
    sm = smooth_series(s, viz.get("smooth_method"), viz.get("smooth_window"))
    lm = float(viz.get("infl_late_min_mmyr", 3.0)); vj = float(viz.get("infl_vjump_min_mmyr", 8.0))
    am = float(viz.get("infl_accel_min_mmyr2", 200.0)); metric = viz.get("infl_metric", "vjump")
    v2 = np.gradient(np.gradient(sm, years), years)
    cands = []
    for i in range(seg, len(sm) - 2):
        vb = _seg_slope_local(years, sm, i, seg, "before")
        va = _seg_slope_local(years, sm, i, seg, "after")
        if not (np.isfinite(vb) and np.isfinite(va)):
            continue
        if not (va >= lm and vb < lm):        # 침하로 '전환'(전반 미침하→후반 침하)
            continue
        dv = va - vb; acc = float(v2[i])
        ok_v = dv >= vj; ok_a = acc >= am
        if (ok_v if metric == "vjump" else ok_a if metric == "accel" else (ok_v and ok_a)):
            cands.append(dict(idx=int(i), delta_v=round(dv, 2), accel=round(acc, 1),
                              v_before=round(vb, 2), v_after=round(va, 2),
                              strength=round(dv if metric != "accel" else acc, 2)))
    cands.sort(key=lambda c: -c["strength"])
    picked = []
    for c in cands:
        if all(abs(c["idx"] - p["idx"]) > seg for p in picked):
            picked.append(c)
        if len(picked) >= int(viz.get("infl_top_n", 3)):
            break
    return picked


def _svg_chart(dates, series, vlines, title, ylab, W=660, H=170):
    """서버측 라인차트 SVG. series=[(values,color,width,dots)], vlines=[(idx,color,label,dash)]."""
    mL, mR, mT, mB = 54, 14, 22, 40
    allv = np.concatenate([np.asarray([v for v in s[0] if v is not None], float) for s in series if any(x is not None for x in s[0])]) \
        if series else np.array([0.0, 1.0])
    if allv.size == 0:
        allv = np.array([0.0, 1.0])
    ymin, ymax = float(np.min(allv)), float(np.max(allv))
    if ymax <= ymin:
        ymax = ymin + 1.0
    pad = (ymax - ymin) * 0.1; ymin -= pad; ymax += pad
    n = len(dates)
    def X(i): return mL + (W - mL - mR) * (i / (n - 1 if n > 1 else 1))
    def Y(v): return mT + (H - mT - mB) * (1 - (v - ymin) / (ymax - ymin))
    out = ['<svg width="%d" height="%d" style="background:#fff;display:block;margin-top:4px">' % (W, H)]
    out.append('<text x="%d" y="13" font-size="11" font-weight="700" fill="#333">%s</text>' % (mL, title))
    for tk in range(5):
        vv = ymin + (ymax - ymin) * tk / 4; yy = Y(vv)
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#eee"/>' % (mL, yy, W - mR, yy))
        out.append('<text x="%d" y="%.1f" font-size="9" text-anchor="end" fill="#666">%.1f</text>' % (mL - 4, yy + 3, vv))
    if ymin < 0 < ymax:
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#c0392b" stroke-dasharray="4,3"/>' % (mL, Y(0), W - mR, Y(0)))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%.1f" stroke="#999"/>' % (mL, mT, mL, H - mB))
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#999"/>' % (mL, H - mB, W - mR, H - mB))
    # 수직선(변곡점/사고)
    for (idx, col, lab, dash) in vlines:
        if idx is None or idx < 0 or idx >= n:
            continue
        xx = X(idx)
        da = ' stroke-dasharray="5,3"' if dash else ''
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6"%s/>' % (xx, mT, xx, H - mB, col, da))
        out.append('<text x="%.1f" y="%d" font-size="8.5" fill="%s" text-anchor="middle">%s</text>' % (xx, mT - 2, col, lab))
    # x 눈금
    for q in range(6):
        ii = int(round((n - 1) * q / 5)); xx = X(ii)
        out.append('<text x="%.1f" y="%d" font-size="8.5" fill="#666" text-anchor="end" transform="rotate(-40 %.1f %d)">%s</text>' % (xx, H - mB + 9, xx, H - mB + 9, dates[ii]))
    # 시리즈
    for (vals, col, wdt, dots) in series:
        pts = [(X(i), Y(v)) for i, v in enumerate(vals) if v is not None]
        if len(pts) >= 2:
            out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s"/>' % (
                " ".join("%.1f,%.1f" % p for p in pts), col, wdt))
        if dots:
            for (px, py) in pts:
                out.append('<circle cx="%.1f" cy="%.1f" r="1.4" fill="%s"/>' % (px, py, col))
    out.append('<text x="%d" y="13" font-size="9" fill="#888" text-anchor="end">%s</text>' % (W - mR, ylab))
    out.append('</svg>')
    return "".join(out)


def _year_of(datestr):
    if not datestr:
        return None
    t = pd.Timestamp(datestr)
    return t.year + (t - pd.Timestamp(t.year, 1, 1)).days / 365.25


def _yr_to_date(yr):
    """소수연도 → 'YYYY-MM-DD'. NaN/None이면 None."""
    if yr is None or not np.isfinite(yr):
        return None
    y = int(np.floor(yr))
    d = pd.Timestamp(y, 1, 1) + pd.Timedelta(days=(yr - y) * 365.25)
    return d.strftime("%Y-%m-%d")


def inverse_velocity(disp, years, asof_year=None):
    """역속도법(Fukuzono): 최근 속도표본의 1/v 선형적합 → 붕괴예상 t_f·R²·가속플래그·리드.
    sinkhole_pipeline/invvel.py 로직 이식(자체포함). s=-LOS(침하 양수). 반환 dict of arrays[N]."""
    IV = CONFIG.get("invvel", {})
    N = disp.shape[0]; z = np.zeros(N)
    out = {"v_recent": z.copy(), "tf_year": np.full(N, np.nan), "r2": z.copy(),
           "accel": np.zeros(N, bool), "lead_days": np.full(N, np.nan)}
    m = years <= asof_year if asof_year is not None else np.ones(len(years), bool)
    t = years[m]; s = -disp[:, m].astype(float); T = s.shape[1]
    if T < int(IV.get("min_series", 12)):
        return out
    for i in np.where(np.isnan(s).any(axis=1))[0]:
        ok = np.isfinite(s[i]); idx = np.arange(T)
        s[i] = np.interp(idx, idx[ok], s[i][ok]) if ok.sum() >= 2 else 0.0
    sw = int(IV.get("smooth_win", 5))
    if sw > 1:
        s = median_filter(s, size=(1, sw), mode="nearest")
    w = int(IV.get("vel_win", 6))
    if T < w + 2:
        return out
    nwin = T - w + 1; V = np.empty((N, nwin)); tc = np.empty(nwin)
    for j in range(nwin):
        tt = t[j:j + w]; V[:, j] = ind._seg_slope(tt, s[:, j:j + w]); tc[j] = tt.mean()
    R = min(int(IV.get("recent_win", 8)), nwin); Vr = V[:, -R:]; tr = tc[-R:]
    v_recent = Vr.mean(axis=1); floor = float(IV.get("iv_floor_mmyr", 1.0))
    valid = np.all(Vr >= floor, axis=1)
    iv = np.where(Vr >= floor, 1.0 / np.clip(Vr, floor, None), np.nan)
    tcm = tr - tr.mean(); denom = float(np.sum(tcm ** 2))
    a = np.full(N, np.nan); b = np.full(N, np.nan); r2 = np.zeros(N)
    if denom > 0:
        a = (iv @ tcm) / denom; b = np.nanmean(iv, axis=1) - a * tr.mean()
        pred = a[:, None] * tr[None, :] + b[:, None]
        ss_res = np.nansum((iv - pred) ** 2, axis=1)
        ss_tot = np.nansum((iv - np.nanmean(iv, axis=1, keepdims=True)) ** 2, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            r2 = np.where(ss_tot > 0, 1.0 - ss_res / ss_tot, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        tf = np.where(a < 0, -b / a, np.nan)
    lm = float(IV.get("late_min_rate_mmyr", 3.0)); r2min = float(IV.get("r2_min", 0.5))
    accel = valid & (a < 0) & (r2 >= r2min) & (v_recent >= lm) & np.isfinite(tf)
    asof = asof_year if asof_year is not None else float(t[-1])
    lead = (tf - asof) * 365.25
    lead = np.where(accel & (lead >= 0) & (lead <= float(IV.get("horizon_days_max", 3650))), lead, np.nan)
    accel = accel & np.isfinite(lead)
    return {"v_recent": v_recent, "tf_year": np.where(accel, tf, np.nan), "r2": r2,
            "accel": accel, "lead_days": lead}


def _iv_cell(iv, i):
    """포인트 팝업용 역속도 셀 [t_f날짜|None, 가속(0/1), R²|None, 리드일수|None, v_recent]."""
    acc = bool(iv["accel"][i])
    tf = _yr_to_date(float(iv["tf_year"][i])) if acc else None
    lead = int(round(float(iv["lead_days"][i]))) if acc and np.isfinite(iv["lead_days"][i]) else None
    r2 = round(float(iv["r2"][i]), 2) if np.isfinite(iv["r2"][i]) else None
    vr = round(float(iv["v_recent"][i]), 1) if np.isfinite(iv["v_recent"][i]) else None
    return [tf, int(acc), r2, lead, vr]


def inflection_report_html(region, bore_all):
    """기능3: 발생 AOI 대표점(버퍼 내 최대 누적침하)의 침하개시 변곡점 탐지 + 3그래프(누적/1차/2차)."""
    ev = EVENTS.get(region, {})
    if ev.get("lon") is None:
        return ""
    from pyproj import Transformer
    trm = Transformer.from_crs(4326, 32652, always_xy=True)
    ex, ey = trm.transform(ev["lon"], ev["lat"]); buf = ev.get("buffer_m", 200)
    best = None
    for kind, load in (("PS", loaders.load_ps), ("SBAS", loaders.load_sbas)):
        d = load(region)
        dist = np.hypot(np.asarray(d["x"]) - ex, np.asarray(d["y"]) - ey)
        inb = dist <= buf
        if inb.sum() == 0:
            continue
        rc = ind.risk_cumulative(d["disp"], d["years"])
        idxs = np.where(inb)[0]
        j = idxs[int(np.nanargmax(np.nan_to_num(rc[idxs], nan=-1e18)))]
        cand = (kind, d, j, float(np.nan_to_num(rc[j], nan=0.0)), float(dist[j]))
        if best is None or cand[3] > best[3]:
            best = cand
    if best is None:
        return "<h3>침하 개시(전조) 변곡점</h3><p style='color:#888'>발생 버퍼 내 대표 포인트 없음.</p>"
    kind, d, j, netcum, dj = best
    disp_row = np.asarray(d["disp"][j], float); years = np.asarray(d["years"], float)
    dates = [f"{c[1:5]}-{c[5:7]}-{c[7:9]}" for c in d["dates"]]
    viz = _mv()
    cands = detect_inflection(disp_row, years, viz)
    # 표시용(누적변위 disp 원본 + 평활), 1차/2차 미분(평활곡선 기준)
    ok = np.isfinite(disp_row)
    disp_i = np.interp(np.arange(len(disp_row)), np.where(ok)[0], disp_row[ok]) if ok.sum() >= 2 else np.nan_to_num(disp_row)
    disp_sm = smooth_series(disp_i, viz.get("smooth_method"), viz.get("smooth_window"))
    v1 = np.gradient(disp_sm, years); v2 = np.gradient(v1, years)
    raw = [None if not np.isfinite(x) else round(float(x), 2) for x in disp_row]
    smv = [round(float(x), 2) for x in disp_sm]
    v1l = [round(float(x), 2) for x in v1]; v2l = [round(float(x), 1) for x in v2]
    eyr = _year_of(ev.get("event_date"))
    eidx = int(np.argmin(np.abs(years - eyr))) if eyr is not None else None
    # 변곡점 후보 → 발생일 이전만(전조), 강도순
    onset = [c for c in cands if eyr is None or years[c["idx"]] <= eyr]
    vlines = [(c["idx"], "#e67e22", dates[c["idx"]], False) for c in onset]
    if eidx is not None:
        vlines.append((eidx, "#8e44ad", "사고 " + (ev.get("event_date") or ""), True))
    ch1 = _svg_chart(dates, [(raw, "#c9c9c9", "1.0", True), (smv, "#111", "1.8", False)], vlines, "누적 LOS 변위 (원본 회색 · 평활 검정)", "mm")
    ch2 = _svg_chart(dates, [(v1l, "#1a5276", "1.6", False)], vlines, "1차 미분 = 변위속도", "mm/yr")
    ch3 = _svg_chart(dates, [(v2l, "#7d3c98", "1.6", False)], vlines, "2차 미분 = 가속도(곡률)", "mm/yr²")
    # 텍스트 요약
    h = ["<h3>침하 개시(전조) 변곡점 — 자동탐지 <span style='font-weight:400;color:#888'>(후보, 판단 보조)</span></h3>"]
    h.append(f"<p style='font-size:12px;margin:2px 0'>대표점: <b>{kind}</b> (발생점 {dj:.0f}m, 2년 누적침하 {netcum:.1f}mm) · "
             f"평활 {viz.get('smooth_method')}·창{viz.get('smooth_window')} · 급변기준 Δv≥{viz.get('infl_vjump_min_mmyr')}mm/yr(잠정)</p>")
    if onset:
        h.append("<table class='rt'><tr><th>#</th><th>침하개시 후보일</th><th>급변 Δv(mm/yr)</th><th>가속도(mm/yr²)</th><th>발생일까지 리드타임</th></tr>")
        for k, c in enumerate(onset, 1):
            od = dates[c["idx"]]
            lead = ""
            if eyr is not None:
                dd = round((eyr - years[c["idx"]]) * 365.25)
                lead = f"{int(dd):,}일 전" if dd > 0 else f"{int(-dd):,}일 후(무효)"
            h.append(f"<tr><td>{k}</td><td><b>{od}</b></td><td>{c['delta_v']}</td><td>{c['accel']}</td><td>{lead}</td></tr>")
        h.append("</table>")
    else:
        h.append("<p style='color:#a04000;font-size:12px'>급변 임계 이상(Δv 큰) 변곡점 미검출 — 완만한 침하이거나 임계값 조정 필요(CONFIG map_viz).</p>")
    h.append("<div style='overflow-x:auto'>" + ch1 + ch2 + ch3 + "</div>")
    h.append("<p style='font-size:11px;color:#888;margin-top:3px'>주황선=침하개시 후보 · 보라 점선=실제 사고일. "
             "미분은 <b>평활 곡선</b> 기준(원본 직접 미분은 노이즈 폭증). 변곡점은 자동탐지 후보이며 급변 임계는 잠정값.</p>")
    return "".join(h)


# ---------------- 시추공 지층 상세 ----------------
def borehole_layer_detail(codes):
    """near-AOI 시추공(codes)의 지층별 상세 dict{공번:[[uscs,top,bot,repN,is_soft],...]}."""
    import step1_ground_grade as s1
    codes = set(codes)
    uc = ["시추공코드", "학술용지층명USCS", "토목용지층명", "관입깊이", "타격회수",
          "지층시작심도", "지층종료심도", "지층코드"]
    df = pd.read_csv(CONFIG["paths"]["ground_csv"], usecols=uc, encoding="utf-8-sig",
                     dtype={"시추공코드": str, "학술용지층명USCS": str, "토목용지층명": str, "지층코드": str})
    df = df[df["시추공코드"].isin(codes)].copy()
    df["N"] = s1.compute_spt_N(df["타격회수"].values, df["관입깊이"].values)
    df["_lyr"] = df["지층코드"].fillna(df["시추공코드"] + "_" +
                                      df["지층시작심도"].round(2).astype(str) + "_" + df["지층종료심도"].round(2).astype(str))
    lyr = df.groupby("_lyr", sort=False).agg(
        code=("시추공코드", "first"), top=("지층시작심도", "min"), bot=("지층종료심도", "max"),
        uscs=("학술용지층명USCS", "first"), civil=("토목용지층명", "first"), repN=("N", "min")).reset_index()
    s = CONFIG["soft"]
    pref = lyr["uscs"].map(s1._uscs_prefix)
    civ = lyr["civil"].fillna("").str.strip()
    lyr["soil"] = np.select(
        [pref.isin(s["rock_exclude_uscs"]) | civ.isin(s["rock_exclude_civil"]),
         pref.isin(s["cohesive"]), pref.isin(s["sandy"])], ["rock", "cohesive", "sandy"], default="other")
    depth = (lyr["top"] + lyr["bot"]) / 2.0
    finN = np.isfinite(lyr["repN"])
    lyr["soft"] = (((lyr["soil"] == "cohesive") & finN & (lyr["repN"] <= s["cohesive_N"]) & (depth < s["cohesive_depth_max_m"])) |
                   ((lyr["soil"] == "sandy") & finN & (lyr["repN"] <= s["sandy_N"]) & (depth >= s["sandy_depth_min_m"])))
    out = {}
    for _, r in lyr.sort_values(["code", "top"]).iterrows():
        out.setdefault(r["code"], []).append([
            (s1._uscs_prefix(r["uscs"]) or SOIL_KO.get(r["soil"], "?")),
            None if not np.isfinite(r["top"]) else round(float(r["top"]), 1),
            None if not np.isfinite(r["bot"]) else round(float(r["bot"]), 1),
            None if not np.isfinite(r["repN"]) else int(round(r["repN"])),
            bool(r["soft"])])
    return out


# ---------------- 지역 데이터 payload ----------------
def region_payload(region, bore_all, layerdet):
    thr = CONFIG["thr_base"]
    # PS: 지표·등급 계산
    ps = loaders.load_ps(region)
    prv = ind.risk_velocity(ps["vel"]); prc = ind.risk_cumulative(ps["disp"], ps["years"])
    ptr = ind.trend_grade(ps["disp"], ps["years"])
    a_ps = np.ones(len(prv))  # 지도표시는 지표 자체(α는 시추공 레이어에서 별도) — 팝업 최종등급은 α결합
    # α: 최근접 시추공
    from scipy.spatial import cKDTree
    bt = cKDTree(np.column_stack([bore_all["x_m"], bore_all["y_m"]]))
    from pyproj import Transformer
    trm = Transformer.from_crs(4326, 32652, always_xy=True)
    pxx, pyy = trm.transform(ps["lon"], ps["lat"])
    _, pi = bt.query(np.column_stack([pxx, pyy]), k=1); pa = bore_all["alpha"].values[pi]
    pgv = np.array([_O[x] for x in ind.grade_velocity(prv, pa)])
    pgc = np.array([_O[x] for x in ind.grade_cumulative(prc, pa)])
    pgt = np.array([_O[x] for x in ptr["grade"]])
    if CONFIG.get("subsidence_only", False):    # 침하만: 비침하(vel>=0) 제외 → 최종 변위속도 −만 경보
        up = np.asarray(ps["vel"], float) >= 0
        pgv[up] = 0; pgc[up] = 0; pgt[up] = 0
    ps_rows = []
    dispp = ps["disp"]
    ps_iv = inverse_velocity(ps["disp"], ps["years"])   # 역속도법 t_f(예상붕괴시점) — 포인트별
    for i in range(len(prv)):
        row = [round(float(ps["lon"][i]), 6), round(float(ps["lat"][i]), 6), round(float(ps["vel"][i]), 2),
               int(pgv[i]), int(pgc[i]), int(pgt[i]), round(float(prc[i]), 1), _iv_cell(ps_iv, i)]
        row += [None if not np.isfinite(dispp[i, j]) else round(float(dispp[i, j]), 1) for j in range(dispp.shape[1])]
        ps_rows.append(row)

    # SBAS: 융합 판정(process_region 재사용, load_sbas와 동일 순서)
    sbdf, _, _ = s2.process_region(region, (bt, bore_all["alpha"].values, bore_all["등급"].values, bore_all))
    sb = loaders.load_sbas(region)
    dispb = sb["disp"]
    B = {"①PS+SBAS합치": 1, "②SBAS단독(PS공백)": 2, "③불일치(보수상위)": 3, "-": 0}
    sb_rows = []
    fg = sbdf["final_grade"].values; bss = sbdf["basis"].values
    hot = sbdf["hotspot"].values; void = sbdf["ps_void"].values; lowt = sbdf["low_tcoh"].values
    gt = sbdf["sbas_gt"].values; gv = sbdf["sbas_gv"].values; gc = sbdf["sbas_gc"].values
    rc = sbdf["sbas_cum_mm"].values; tco = sbdf["tcoh"].values
    sb_iv = inverse_velocity(sb["disp"], sb["years"])   # 역속도법 t_f(예상붕괴시점) — 포인트별
    for i in range(len(sb["vel"])):
        row = [round(float(sb["lon"][i]), 6), round(float(sb["lat"][i]), 6), round(float(sb["vel"][i]), 2),
               _O[gv[i]], _O[gc[i]], _O[gt[i]], round(float(rc[i]), 1), _O[fg[i]], B.get(bss[i], 0),
               int(bool(hot[i])), int(bool(void[i])), int(bool(lowt[i])),
               None if not np.isfinite(tco[i]) else round(float(tco[i]), 2), _iv_cell(sb_iv, i)]
        row += [None if not np.isfinite(dispb[i, j]) else round(float(dispb[i, j]), 1) for j in range(dispb.shape[1])]
        sb_rows.append(row)

    # 시추공: AOI.xlsx SNWE 범위 내만 표시 (#1)
    lon_all = bore_all["lon"].values; lat_all = bore_all["lat"].values
    latc = float(np.nanmean(ps["lat"])); lonc = float(np.nanmean(ps["lon"]))
    if region in AOI_SNWE:
        S, N, W, E = AOI_SNWE[region]
        m = (lon_all >= W) & (lon_all <= E) & (lat_all >= S) & (lat_all <= N)
    else:
        m = (np.abs(lon_all - lonc) < 0.1) & (np.abs(lat_all - latc) < 0.1)
    bsub = bore_all[m]
    bore_rows = []
    for _, r in bsub.iterrows():
        code = str(r["공번"])
        bore_rows.append([round(float(r["lon"]), 6), round(float(r["lat"]), 6), BORE_O[r["등급"]],
                          round(float(r["alpha"]), 2),
                          None if not np.isfinite(r["최저N"]) else int(round(r["최저N"])),
                          int(r["연약층수"]), round(float(r["연약누적두께_m"]), 1),
                          layerdet.get(code, [])])

    # --- 지질 기반 융합 지반등급 + 지질도 레이어 (전국 25만 → 7개 AOI 전부) ---
    nps = len(ps_rows); nsb = len(sb_rows)
    ps_gg = None; sb_gg = None; geo_litho = None; geo_fault = None
    if region in geol.REGION_SHEET:
        gcsv = os.path.join(OUTC, f"geo_integrated_{region}.csv")
        if os.path.exists(gcsv):
            gd = pd.read_csv(gcsv, encoding="utf-8-sig")
            if len(gd) == nps + nsb:
                ggc = gd["final_ground_grade"].map(GGO).fillna(3).astype(int).values
                src = (gd["source"].values != "borehole").astype(int)
                al = gd["final_alpha"].values
                lit = np.where(gd["source"].values == "geology", gd["LITHONAME"].fillna("").astype(str).values, "")
                fb = (gd["karst"].astype(int) * 1 + gd["fault_adj"].astype(int) * 2).values
                allgg = [[int(ggc[i]), int(src[i]),
                          (None if not np.isfinite(al[i]) else round(float(al[i]), 2)), str(lit[i]), int(fb[i])]
                         for i in range(len(gd))]
                ps_gg = allgg[:nps]; sb_gg = allgg[nps:nps + nsb]
        # 지질도 폴리곤/단층 클립(AOI bbox+pad) → GeoJSON
        try:
            from shapely.geometry import box
            code = geol.REGION_SHEET[region]
            lith, fault = geol.read_geology(code)
            pad = 0.02
            bb = box(float(ps["lon"].min()) - pad, float(ps["lat"].min()) - pad,
                     float(ps["lon"].max()) + pad, float(ps["lat"].max()) + pad)
            import geopandas as gpd
            lc = gpd.clip(lith, bb)
            if len(lc):
                lc = lc.copy()
                lc["grade"] = [geol.classify_litho(n)[0] for n in lc["LITHONAME"]]
                lc["alpha"] = lc["grade"].map({"양호": 1.0, "주의": 0.8, "연약": 0.6})
                lc["geometry"] = lc["geometry"].simplify(0.0002)
                geo_litho = json.loads(lc[["LITHONAME", "AGE", "grade", "alpha", "geometry"]].to_json())
            # 단층 정보 제거(사용자 지시) — geo_fault 미생성
        except Exception as e:
            print(f"  [지질도 클립 경고] {region}: {e}")

    ev = EVENTS.get(region, {})
    _meta = REGIONS.get(region, {})
    poi = None
    if ev.get("lon") is not None:
        poi = {"lat": ev["lat"], "lon": ev["lon"], "label": ev.get("desc", "발생지점"),
               # 기능1 팝업용 케이스 정보(분석·Confluence 값만, 없으면 빈값)
               "region_name": _meta.get("label", region), "quad": _meta.get("quad", ""),
               "group": GROUP.get(_meta.get("type", ""), ""),
               "event_date": ev.get("event_date", ""), "cause": _meta.get("note", ""),
               "desc": ev.get("desc", "")}
    dates = [f"{c[1:5]}-{c[5:7]}-{c[7:9]}" for c in ps["dates"]]
    dates_sb = [f"{c[1:5]}-{c[5:7]}-{c[7:9]}" for c in sb["dates"]]
    vmax = max(1.0, float(np.nanpercentile(np.abs(np.concatenate([ps["vel"], sb["vel"]])), 95)))
    fin = dispp[np.isfinite(dispp)]
    gm = float(np.nanpercentile(np.abs(fin), 98)) if fin.size else 5.0
    gyabs = round(max(gm, 1.0), 1)
    # 통일 스케일 = 각 AOI 데이터 실제 min/max(+5% 여백) — 그래프 안 잘리게 (#통일스케일)
    def _rng(d):
        # 통일 스케일 = 0.5~99.5 퍼센타일(극단 0.5% 제외 → 언랩 이상치 압축 방지) +5% 여백
        f = d[np.isfinite(d)]
        if f.size == 0:
            return [-1.0, 1.0]
        lo, hi = float(np.nanpercentile(f, 0.5)), float(np.nanpercentile(f, 99.5))
        if hi <= lo:
            hi = lo + 1.0
        pad = (hi - lo) * 0.05
        return [round(lo - pad, 1), round(hi + pad, 1)]
    gy_ps = _rng(dispp); gy_sb = _rng(dispb)
    # 리드타임 (#4): 발생점 좌표+날짜 있는 경우 step3_leadtime.csv에서
    lead = None
    ltf = os.path.join(OUTC, "step3_leadtime.csv")
    if ev.get("lon") is not None and ev.get("event_date") and os.path.exists(ltf):
        lt = pd.read_csv(ltf, encoding="utf-8-sig")
        row = lt[lt.region == region]
        if len(row) and pd.notna(row.iloc[0].get("leadtime_days", None)):
            r0 = row.iloc[0]
            lead = {"event_date": ev["event_date"], "leadtime_days": int(r0["leadtime_days"]),
                    "detector": str(r0.get("detector", "-")),
                    "first_alarm_year": round(float(r0["first_alarm_year"]), 2)}
    meta = REGIONS.get(region, {})
    return {
        "region": region, "title": meta.get("label", region),
        "quad": meta.get("quad", ""), "group": GROUP.get(meta.get("type", ""), ""),
        "center": [latc, lonc], "dates": dates, "dates_sb": dates_sb,
        "vmax": round(vmax, 2), "gyabs": gyabs, "gy_ps": gy_ps, "gy_sb": gy_sb, "lead": lead,
        "viz": _mv(),   # 기능2 평활 파라미터(JS 공유)
        "ref": ps.get("reref"), "ps_gg": ps_gg, "sb_gg": sb_gg,
        "geo_litho": geo_litho, "geo_fault": geo_fault,
        "ps": ps_rows, "sbas": sb_rows, "bore": bore_rows, "poi": poi,
        "subs": load_subsidence_in_bbox(region),   # 지반침하 사고 리스트(AOI bbox 내)
        "nps": len(ps_rows), "nsb": len(sb_rows), "nbore": len(bore_rows),
    }


# ---------------- 임계치 표 HTML (공유) ----------------
def thresh_html(has_geo=False, scale="1:5만+1:25만"):
    t = CONFIG["thr_base"]
    geo_block = (
        '<div class="thnote" style="margin-top:7px;border-top:1px solid #eee;padding-top:6px">'
        f'<b>지질 기반 지반등급</b> (시추공 공백 &gt;500m 보완, 수치지질도 {scale})<br>'
        '· 충적층·매립지·석회암 → <b class="g2" style="padding:0 4px">연약</b>(α0.6) '
        '/ 기반암(편마암·화강암·응회암 등) → <b class="g0" style="padding:0 4px">양호</b>(α1.0)<br>'
        '· 출처: 시추공 근접=<b>borehole(high)</b>, 공백=<b>geology(medium)</b> — 포인트 팝업에 표기<br>'
        '· 지질도 면은 지반등급색으로 표시(레이어 토글).</div>'
    ) if has_geo else ''
    return ('<div class="thbox" id="thbox"><div class="thhd"><b>판정 임계치</b>'
            '<button id="thtog" onclick="togTh()">[−]</button></div><div id="thbody">'
            '<table class="tht"><tr><th>위험등급</th><th>변위속도<br>(mm/yr)</th><th>누적변위<br>(mm)</th><th>추세</th></tr>'
            f'<tr><td class="g0">정상</td><td>&lt; {t["vel_watch"]:.0f}</td><td>&lt; {t["cum_watch"]:.0f}</td><td>등속·감속</td></tr>'
            f'<tr><td class="g1">주의</td><td>{t["vel_watch"]:.0f} ~ {t["vel_danger"]:.0f}</td><td>{t["cum_watch"]:.0f} ~ {t["cum_danger"]:.0f}</td><td>가속전환 의심(2회 연속)</td></tr>'
            f'<tr><td class="g2">위험</td><td>&gt; {t["vel_danger"]:.0f} ({t["vel_immediate"]:.0f}↑ 즉시)</td><td>&gt; {t["cum_danger"]:.0f}</td><td>가속확정(4~5회 연속)</td></tr>'
            '</table>'
            '<table class="tht" style="margin-top:6px"><tr><th>지반등급</th><th>조건</th><th>α</th></tr>'
            '<tr><td class="g2">연약</td><td>연약층 1개 이상</td><td>0.6</td></tr>'
            '<tr><td class="g1">주의</td><td>연약층 없음 &amp; 최저N ≤ 10</td><td>0.8</td></tr>'
            '<tr><td class="g0">양호</td><td>최저N &gt; 10</td><td>1.0</td></tr></table>'
            '<div class="thnote">연약할수록 임계치 × α로 하향 → 낮은 변위에서 상위등급 발령.<br>'
            '⚠️ 임계치는 <b>잠정값</b>(백테스팅 확정 전). 채택=기준값(스윕 결과 recall 100%라 하향 불필요).</div>'
            + geo_block +
            '</div></div>')


# ---------------- 지역맵 HTML ----------------
REGION_TEMPLATE = r"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>__TITLE__ — PS/SBAS/시추공 통합맵</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
html,body,#map{height:100%;margin:0}
.info{background:#fff;padding:8px 10px;border-radius:6px;font:12px/1.4 sans-serif;box-shadow:0 1px 6px rgba(0,0,0,.35);max-width:320px}
.lg i{width:16px;height:12px;display:inline-block;margin-right:6px;opacity:.95;vertical-align:middle}
.lg .dot{width:13px;height:13px;border-radius:50%;display:inline-block;margin-right:6px;vertical-align:middle}
.cbar{height:12px;width:230px;background:linear-gradient(to right,#b2182b,#ef8a62,#fddbc7,#f7f7f7,#d1e5f0,#67a9cf,#2166ac);border:1px solid #999}
.ttl{font-weight:700;margin-bottom:4px}
.poi-lbl{background:#c0392b;color:#fff;border:none;font-weight:700;font-size:12px;padding:2px 6px;border-radius:3px}
.ref-lbl{background:#1565c0;color:#fff;border:none;font-weight:700;font-size:12px;padding:2px 6px;border-radius:3px}
.pop{font:12px/1.45 sans-serif}.leaflet-popup-content{margin:10px 12px}
.pt{border-collapse:collapse;font-size:12px}.pt td,.pt th{border:1px solid #ddd;padding:2px 6px;text-align:center}
.pt th{background:#f4f4f4}
.g0{background:#d5f5e3;color:#196f3d;font-weight:700}.g1{background:#fdebd0;color:#a04000;font-weight:700}
.g2{background:#fadbd8;color:#943126;font-weight:700}
.badge{padding:1px 7px;border-radius:9px;font-weight:700}
.thbox{position:absolute;top:10px;left:52px;z-index:1000;background:#fff;border-radius:7px;box-shadow:0 1px 8px rgba(0,0,0,.35);font:12px sans-serif;max-width:340px}
.thhd{padding:6px 10px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}
.thhd button{border:none;background:#eee;border-radius:4px;cursor:pointer;font-weight:700;padding:1px 8px}
#thbody{padding:8px 10px}
.tht{border-collapse:collapse;font-size:11px;width:100%}.tht td,.tht th{border:1px solid #ddd;padding:2px 5px;text-align:center}
.tht th{background:#f4f4f4}.thnote{font-size:10.5px;color:#666;margin-top:5px;line-height:1.4}
.hub{position:absolute;top:10px;right:10px;z-index:1000;background:#2c3e50;color:#fff;padding:6px 12px;border-radius:6px;text-decoration:none;font:13px sans-serif;font-weight:700;box-shadow:0 1px 6px rgba(0,0,0,.35)}
</style></head><body><div id="map"></div>
__THRESH__
<a class="hub" href="../CLAB_통합맵.html">◀ 허브(AOI 목록)</a>
<script>
var D=__PAYLOAD__;
var map=L.map('map',{preferCanvas:true}).setView(D.center,13);
var osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'});
var esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles &copy; Esri'});
osm.addTo(map);
map.createPane('geopane'); map.getPane('geopane').style.zIndex=350;   // 지질도(포인트 아래)
var GGCOL_JS={'양호':'#27ae60','주의':'#e67e22','연약':'#c0392b'};
// 선택 날짜(그래프 세로 점선). PS+SBAS 날짜 합집합.
var selDates=[]; var alldates=D.dates.slice();
D.dates_sb.forEach(function(d){if(alldates.indexOf(d)<0)alldates.push(d);}); alldates.sort();
function nearestIdx(dates,sd){var best=-1,bd=1e18,ts=Date.parse(sd);for(var i=0;i<dates.length;i++){var dd=Math.abs(Date.parse(dates[i])-ts);if(dd<bd){bd=dd;best=i;}}return best;}
function clamp(x,a,b){return x<a?a:(x>b?b:x);}function lerp(a,b,t){return a+(b-a)*t;}
var STOPS=[[178,24,43],[239,138,98],[253,219,199],[247,247,247],[209,229,240],[103,169,207],[33,102,172]];
// 컬러바 velocity 범위(mm/yr) — 기본 대칭 ±D.vmax. 사용자 조절 가능(colorFor·recolorAll).
var cbMin=-D.vmax, cbMax=D.vmax;
// 그래프 '전체' 스케일 수동 override(mm). null이면 각 AOI 통일스케일(D.gy_*) 사용.
var gMin=null, gMax=null;
function colorFor(v){var t=clamp((v-cbMin)/((cbMax-cbMin)||1),0,1);var s=t*(STOPS.length-1);var i=Math.floor(s);var f=s-i;
 if(i>=STOPS.length-1){i=STOPS.length-2;f=1;}var c0=STOPS[i],c1=STOPS[i+1];
 return 'rgb('+Math.round(lerp(c0[0],c1[0],f))+','+Math.round(lerp(c0[1],c1[1],f))+','+Math.round(lerp(c0[2],c1[2],f))+')';}
var BORECOL=['#27ae60','#e67e22','#c0392b'];      // 양호/주의/연약
var GCLS=['g0','g1','g2'],GLAB=['정상','주의','위험'],TRLAB=['등속·감속','가속전환 의심','가속확정'];
var BLAB=['양호','주의','연약'];
function gbadge(g){return '<span class="badge '+GCLS[g]+'">'+GLAB[g]+'</span>';}
function basisLab(b){return ['','①PS+SBAS 합치','②SBAS 단독(PS공백)','③PS-SBAS 불일치(보수상위)'][b]||'';}
function reason(gv,gc,gt){var mx=Math.max(gv,gc,gt);if(mx===0)return '-';var r=[];if(gv===mx)r.push('속도');if(gc===mx)r.push('누적');if(gt===mx)r.push('추세');return r.join('+');}
// 역속도법(Fukuzono) 예상 붕괴시점 행. iv=[t_f날짜|null, 가속(0/1), R²|null, 리드일수|null, 최근침하mm/yr|null].
function ivRow(iv){if(!iv)return '';
 if(iv[1]){var lead=(iv[3]!=null?Number(iv[3]).toLocaleString()+'일 후':'-');
  return '<div style="margin-top:4px;padding:3px 7px;background:#fdecea;border-left:3px solid #c0392b">'
   +'<b>⚠ 역속도법 예상 붕괴시점: '+(iv[0]||'-')+'</b> (약 '+lead+' · R² '+(iv[2]!=null?iv[2]:'-')+' · 최근침하 '+(iv[4]!=null?iv[4]:'-')+' mm/yr)'
   +'<div style="font-size:10.5px;color:#888">1/v 선형외삽(Fukuzono) 자동추정 — 잠정·후보</div></div>';}
 return '<div style="margin-top:4px;color:#888;font-size:11px">역속도법: 가속 신호 없음 → 붕괴시점 예측 불가'+(iv[4]!=null?' (최근침하 '+iv[4]+' mm/yr)':'')+'</div>';}
// 기능2: 강건 평활(중앙값→이동평균). vals=관측값 배열(결측 제거됨), win=관측수.
function smoothSeries(vals,method,win){var T=vals.length,pad=win>>1,out=vals.slice();
 function med(a){a=a.slice().sort(function(x,y){return x-y;});var n=a.length;return n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2;}
 if(method==='median'||method==='median_then_ma'){var m=vals.slice();for(var j=0;j<T;j++){var lo=Math.max(0,j-pad),hi=Math.min(T,j+pad+1);m[j]=med(vals.slice(lo,hi));}out=m;}
 if(method==='ma'||method==='median_then_ma'){var b=out.slice();for(var j=0;j<T;j++){var lo=Math.max(0,j-pad),hi=Math.min(T,j+pad+1),s=0,c=0;for(var k=lo;k<hi;k++){s+=b[k];c++;}out[j]=s/c;}}
 return out;}
// 시계열 SVG (dates 인자). 기능2: 원본=연한 회색(옅게) + 평활=검은 실선(주 추세). 평활은 표시용(판정 원본 불변).
function tsSVG(dv,dates,stroke,fixed,W,cap){stroke=stroke||'#1a5276';W=W||370;var H=210,mL=46,mR=14,mT=26,mB=54;var ys=[],idx=[];
 for(var i=0;i<dv.length;i++){if(dv[i]!=null){idx.push(i);ys.push(dv[i]);}} if(ys.length<2)return '<div class="pop" style="width:'+W+'px;padding-top:18px;color:#888">시계열 없음</div>';
 var vz=D.viz||{};var sm=smoothSeries(ys,vz.smooth_method||'median_then_ma',vz.smooth_window||7);
 var ymin,ymax;if(fixed){ymin=fixed[0];ymax=fixed[1];}else{ymin=Math.min.apply(null,ys);ymax=Math.max.apply(null,ys);if(ymin===ymax){ymin-=1;ymax+=1;}var pad=(ymax-ymin)*0.12;ymin-=pad;ymax+=pad;}
 var n=dates.length;function X(i){return mL+(W-mL-mR)*(i/(n-1));}function Y(v){return clamp(mT+(H-mT-mB)*(1-(v-ymin)/(ymax-ymin)),mT,H-mB);}
 var rawpl='',smpl='';for(var k=0;k<idx.length;k++){rawpl+=(k?' ':'')+X(idx[k]).toFixed(1)+','+Y(ys[k]).toFixed(1);smpl+=(k?' ':'')+X(idx[k]).toFixed(1)+','+Y(sm[k]).toFixed(1);}
 var dots='';for(var k=0;k<idx.length;k++){dots+='<circle cx="'+X(idx[k]).toFixed(1)+'" cy="'+Y(ys[k]).toFixed(1)+'" r="1.5" fill="#c4c4c4" opacity="0.7"/>';}
 var yt='';for(var t=0;t<=4;t++){var vv=ymin+(ymax-ymin)*t/4;var yy=Y(vv);yt+='<line x1="'+mL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-mR)+'" y2="'+yy.toFixed(1)+'" stroke="#eee"/><text x="'+(mL-5)+'" y="'+(yy+3).toFixed(1)+'" font-size="9.5" text-anchor="end" fill="#555">'+vv.toFixed(1)+'</text>';}
 var zl='';if(ymin<0&&ymax>0){var z=Y(0);zl='<line x1="'+mL+'" y1="'+z.toFixed(1)+'" x2="'+(W-mR)+'" y2="'+z.toFixed(1)+'" stroke="#c0392b" stroke-dasharray="4,3"/>';}
 var ax='<line x1="'+mL+'" y1="'+mT+'" x2="'+mL+'" y2="'+(H-mB)+'" stroke="#999"/><line x1="'+mL+'" y1="'+(H-mB)+'" x2="'+(W-mR)+'" y2="'+(H-mB)+'" stroke="#999"/>';
 var xt='';var NT=6;for(var q=0;q<NT;q++){var ii=Math.round((n-1)*q/(NT-1));var xx=X(ii);xt+='<text x="'+xx.toFixed(1)+'" y="'+(H-mB+8)+'" font-size="9" fill="#555" text-anchor="end" transform="rotate(-40 '+xx.toFixed(1)+' '+(H-mB+8)+')">'+dates[ii]+'</text>';}
 var cp=cap?'<text x="'+mL+'" y="14" font-size="10.5" font-weight="700" fill="#333">'+cap+'</text>':'';
 // 선택 날짜 세로 점선(옅은 회색)
 var sl='';for(var q=0;q<selDates.length;q++){var si=nearestIdx(dates,selDates[q]);if(si>=0){var sx=X(si).toFixed(1);
  sl+='<line x1="'+sx+'" y1="'+mT+'" x2="'+sx+'" y2="'+(H-mB)+'" stroke="#888" stroke-width="1" stroke-dasharray="3,3" opacity="0.6"/>'
   +'<text x="'+sx+'" y="'+(mT-2)+'" font-size="8" fill="#888" text-anchor="middle">'+selDates[q].slice(2)+'</text>';}}
 var leg='<text x="'+(mL+2)+'" y="'+(H-6)+'" font-size="8.5" fill="#999">— 원본</text><text x="'+(mL+52)+'" y="'+(H-6)+'" font-size="8.5" font-weight="700" fill="#111">— 평활(이동평균)</text>';
 return '<svg width="'+W+'" height="'+H+'" style="background:#fff;display:block">'+cp+yt+ax+zl+sl
  +'<polyline points="'+rawpl+'" fill="none" stroke="#c4c4c4" stroke-width="0.8" opacity="0.7"/>'+dots
  +'<polyline points="'+smpl+'" fill="none" stroke="#111" stroke-width="1.9"/>'
  +leg+'<text x="'+(W-mR)+'" y="14" font-size="9" fill="#888" text-anchor="end">누적 LOS(mm)</text>'+xt+'</svg>';}
function effFR(fr){return (gMin!=null&&gMax!=null&&gMax>gMin)?[gMin,gMax]:fr;}
function sparks(dv,dates,fr){var e=effFR(fr);var man=(gMin!=null&&gMax!=null&&gMax>gMin);
 var lab=(man?'전체 스케일(수동) ':'전체(통일) 스케일 ')+e[0]+'~'+e[1]+'mm';
 return '<div style="display:flex;gap:6px;margin-top:5px;flex-wrap:wrap">'+tsSVG(dv,dates,null,null,360,'개별 스케일(자동)')+tsSVG(dv,dates,null,e,360,lab)+'</div>';}
// 레이어
var psL=L.layerGroup(),sbL=L.layerGroup(),boL=L.layerGroup();
var psNorm=[],sbNorm=[];   // 최종등급 정상인 마커(필터용 #5)
var psMk=[],sbMk=[];       // [marker,vel] — 컬러바 범위 변경 시 재채색용
// 융합 지반등급 행(시추공/지질 출처)
var GGLAB=['양호','주의','연약','미상'],GGCLS=['g0','g1','g2','g1'];
function ggRow(gg){if(!gg)return '';var lab=GGLAB[gg[0]];var src=gg[1]?'지질':'시추공';var a=(gg[2]!=null?gg[2]:'-');
 var ex=[];if(gg[1]&&gg[3])ex.push('암상 '+gg[3]);if(gg[4]&1)ex.push('카르스트');
 return '<div style="margin-top:4px">지반등급(융합): <b class="'+GGCLS[gg[0]]+'" style="padding:1px 7px;border-radius:8px">'+lab+'</b> '
  +'(α'+a+' · <b>'+src+'</b>'+(gg[1]?'/medium':'/high')+(ex.length?' · '+ex.join(' · '):'')+')</div>';}
// PS
for(var i=0;i<D.ps.length;i++){(function(p,gg){var v=p[2],gv=p[3],gc=p[4],gt=p[5],cum=p[6],iv=p[7],dv=p.slice(8);var g=Math.max(gv,gc,gt);
 var m=L.circleMarker([p[1],p[0]],{radius:3,stroke:false,fillColor:colorFor(v),fillOpacity:0.85});
 m.on('click',function(e){var h='<div class="pop"><b>PS</b> · 위 '+p[1].toFixed(5)+', 경 '+p[0].toFixed(5)+'<table class="pt" style="margin-top:4px">'
  +'<tr><th>변위속도</th><th>누적침하(2yr)</th><th>추세</th><th>최종등급</th><th>근거</th></tr>'
  +'<tr><td>'+v.toFixed(2)+' mm/yr '+(v<0?'(침하)':'(융기)')+'</td><td>'+cum.toFixed(1)+' mm</td><td>'+TRLAB[gt]+'</td><td>'+gbadge(g)+'</td><td>'+reason(gv,gc,gt)+'</td></tr></table>'
  +ivRow(iv)+ggRow(gg)+sparks(dv,D.dates,D.gy_ps)+'</div>';
  L.popup({maxWidth:760,minWidth:740}).setLatLng([p[1],p[0]]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});
 psMk.push([m,v]); if(g===0)psNorm.push(m); m.addTo(psL);})(D.ps[i], D.ps_gg?D.ps_gg[i]:null);}
// SBAS
for(var i=0;i<D.sbas.length;i++){(function(p,gg){var v=p[2],gv=p[3],gc=p[4],gt=p[5],cum=p[6],fg=p[7],bs=p[8],hot=p[9],vo=p[10],lt=p[11],tc=p[12],iv=p[13],dv=p.slice(14);
 var m=L.circleMarker([p[1],p[0]],{radius:4,stroke:false,fillColor:colorFor(v),fillOpacity:0.85});
 m.on('click',function(e){var fl=[];if(bs)fl.push(basisLab(bs));if(hot)fl.push('hotspot');if(vo)fl.push('PS공백');if(lt)fl.push('저tcoh');
  var own=Math.max(gv,gc,gt);var why='';
  if(fg===0&&own>=1){var w=[];if(!hot)w.push('hotspot 미형성');w.push(vo?'반경30m PS 없음(PS공백)':'인근 PS 정상');
   why='<div style="margin-top:3px;color:#943126">ℹ 최종 정상 사유: SBAS 단독 미확인 ('+w.join(' · ')+') · 자체지표는 <b>'+GLAB[own]+'</b>('+reason(gv,gc,gt)+')</div>';}
  var h='<div class="pop"><b>SBAS</b> · 위 '+p[1].toFixed(5)+', 경 '+p[0].toFixed(5)+' · tcoh '+(tc!=null?tc.toFixed(2):'-')+'<table class="pt" style="margin-top:4px">'
  +'<tr><th>변위속도</th><th>누적침하(2yr)</th><th>추세</th><th>최종등급</th><th>근거</th></tr>'
  +'<tr><td>'+v.toFixed(2)+' mm/yr '+(v<0?'(침하)':'(융기)')+'</td><td>'+cum.toFixed(1)+' mm</td><td>'+TRLAB[gt]+'</td><td>'+gbadge(fg)+'</td><td>'+reason(gv,gc,gt)+'</td></tr></table>'
  +(fl.length?'<div style="margin-top:3px;color:#555">플래그: '+fl.join(' · ')+'</div>':'')+why+ivRow(iv)+ggRow(gg)+sparks(dv,D.dates_sb,D.gy_sb)+'</div>';
  L.popup({maxWidth:760,minWidth:740}).setLatLng([p[1],p[0]]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});
 sbMk.push([m,v]); if(fg===0)sbNorm.push(m); m.addTo(sbL);})(D.sbas[i], D.sb_gg?D.sb_gg[i]:null);}
// ===== DSC(하강궤도) 추가 레이어 — 기존 상승 레이어와 별개, 기본 OFF(토글) =====
var psDscL=L.layerGroup(),sbDscL=L.layerGroup();
if(D.ps_dsc){for(var i=0;i<D.ps_dsc.length;i++){(function(p,gg){var v=p[2],gv=p[3],gc=p[4],gt=p[5],cum=p[6],iv=p[7],dv=p.slice(8);var g=Math.max(gv,gc,gt);
 var m=L.circleMarker([p[1],p[0]],{radius:3,stroke:false,fillColor:colorFor(v),fillOpacity:0.85});
 m.on('click',function(e){var h='<div class="pop"><b>PS · 하강/DSC</b> · 위 '+p[1].toFixed(5)+', 경 '+p[0].toFixed(5)+'<table class="pt" style="margin-top:4px">'
  +'<tr><th>변위속도</th><th>누적침하(2yr)</th><th>추세</th><th>최종등급</th><th>근거</th></tr>'
  +'<tr><td>'+v.toFixed(2)+' mm/yr '+(v<0?'(침하)':'(융기)')+'</td><td>'+cum.toFixed(1)+' mm</td><td>'+TRLAB[gt]+'</td><td>'+gbadge(g)+'</td><td>'+reason(gv,gc,gt)+'</td></tr></table>'
  +ivRow(iv)+ggRow(gg)+sparks(dv,D.dates_dsc,D.gy_ps_dsc)+'</div>';
  L.popup({maxWidth:760,minWidth:740}).setLatLng([p[1],p[0]]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});
 psMk.push([m,v]); m.addTo(psDscL);})(D.ps_dsc[i], D.ps_gg_dsc?D.ps_gg_dsc[i]:null);}}
if(D.sbas_dsc){for(var i=0;i<D.sbas_dsc.length;i++){(function(p,gg){var v=p[2],gv=p[3],gc=p[4],gt=p[5],cum=p[6],fg=p[7],bs=p[8],hot=p[9],vo=p[10],lt=p[11],tc=p[12],iv=p[13],dv=p.slice(14);
 var m=L.circleMarker([p[1],p[0]],{radius:4,stroke:false,fillColor:colorFor(v),fillOpacity:0.85});
 m.on('click',function(e){var fl=[];if(bs)fl.push(basisLab(bs));if(hot)fl.push('hotspot');if(vo)fl.push('PS공백');if(lt)fl.push('저tcoh');
  var h='<div class="pop"><b>SBAS · 하강/DSC</b> · 위 '+p[1].toFixed(5)+', 경 '+p[0].toFixed(5)+' · tcoh '+(tc!=null?tc.toFixed(2):'-')+'<table class="pt" style="margin-top:4px">'
  +'<tr><th>변위속도</th><th>누적침하(2yr)</th><th>추세</th><th>최종등급</th><th>근거</th></tr>'
  +'<tr><td>'+v.toFixed(2)+' mm/yr '+(v<0?'(침하)':'(융기)')+'</td><td>'+cum.toFixed(1)+' mm</td><td>'+TRLAB[gt]+'</td><td>'+gbadge(fg)+'</td><td>'+reason(gv,gc,gt)+'</td></tr></table>'
  +(fl.length?'<div style="margin-top:3px;color:#555">플래그: '+fl.join(' · ')+'</div>':'')+ivRow(iv)+ggRow(gg)+sparks(dv,D.dates_sb_dsc,D.gy_sb_dsc)+'</div>';
  L.popup({maxWidth:760,minWidth:740}).setLatLng([p[1],p[0]]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});
 sbMk.push([m,v]); m.addTo(sbDscL);})(D.sbas_dsc[i], D.sb_gg_dsc?D.sb_gg_dsc[i]:null);}}
// 지질도(지질 기반 지반등급) 폴리곤 레이어
var geoL=L.layerGroup();
if(D.geo_litho){L.geoJSON(D.geo_litho,{pane:'geopane',style:function(f){return {color:'#666',weight:0.6,
   fillColor:(GGCOL_JS[f.properties.grade]||'#bbb'),fillOpacity:0.35};},
  onEachFeature:function(f,l){var pr=f.properties;l.bindPopup('<div class="pop"><b>지질(지반등급)</b>'
   +'<table class="pt" style="margin-top:4px"><tr><th>암상</th><th>지질시대</th><th>등급</th><th>α</th></tr>'
   +'<tr><td>'+pr.LITHONAME+'</td><td>'+(pr.AGE||'-')+'</td><td class="'+(pr.grade=="연약"?"g2":(pr.grade=="주의"?"g1":"g0"))+'">'+pr.grade+'</td><td>'+(pr.alpha!=null?pr.alpha:'-')+'</td></tr></table></div>');}
  }).addTo(geoL);}
if(D.geo_litho)geoL.addTo(map);
// 시추공 (마커 크기 동일 #3)
for(var i=0;i<D.bore.length;i++){(function(b){var g=b[2];var rr=5;
 var m=L.circleMarker([b[1],b[0]],{radius:rr,color:'#333',weight:1,fillColor:BORECOL[g],fillOpacity:0.9});
 m.on('click',function(e){var lyr=b[7]||[];var lt='';
  if(lyr.length){lt='<table class="pt" style="margin-top:4px"><tr><th>심도(m)</th><th>토질</th><th>N</th><th>연약</th></tr>';
   for(var k=0;k<lyr.length;k++){var L2=lyr[k];lt+='<tr'+(L2[4]?' style="background:#fadbd8"':'')+'><td>'+(L2[1]!=null?L2[1]:'?')+'~'+(L2[2]!=null?L2[2]:'?')+'</td><td>'+L2[0]+'</td><td>'+(L2[3]!=null?L2[3]:'-')+'</td><td>'+(L2[4]?'●':'')+'</td></tr>';}
   lt+='</table>';}else lt='<div style="color:#888;margin-top:4px">지층 상세 없음</div>';
  var h='<div class="pop"><b>시추공</b> · 위 '+b[1].toFixed(5)+', 경 '+b[0].toFixed(5)+'<table class="pt" style="margin-top:4px">'
   +'<tr><th>지반등급</th><th>α</th><th>최저N</th><th>연약층</th><th>연약누적두께</th></tr>'
   +'<tr><td class="'+GCLS[g]+'">'+BLAB[g]+'</td><td>'+b[3].toFixed(1)+'</td><td>'+(b[4]!=null?b[4]:'-')+'</td><td>'+b[5]+'개</td><td>'+b[6].toFixed(1)+' m</td></tr></table>'
   +'<div style="margin-top:4px;font-weight:700">지층 구성</div>'+lt+'</div>';
  L.popup({maxWidth:420,minWidth:300}).setLatLng([b[1],b[0]]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});
 m.addTo(boL);})(D.bore[i]);}
psL.addTo(map);sbL.addTo(map);boL.addTo(map);
var _ov={};_ov['PS 포인트 ('+D.nps+')']=psL;_ov['SBAS 포인트 ('+D.nsb+')']=sbL;_ov['시추공 지반등급 ('+D.nbore+')']=boL;
if(D.ps_dsc)_ov['PS · 하강/DSC ('+D.nps_dsc+')']=psDscL;
if(D.sbas_dsc)_ov['SBAS · 하강/DSC ('+D.nsb_dsc+')']=sbDscL;
if(D.geo_litho)_ov['지질도(지반등급)']=geoL;
var layersCtl=L.control.layers({'OpenStreetMap':osm,'Esri 위성':esri},_ov,{collapsed:false,position:'topright'}).addTo(map);
// 최종등급 주의·위험만 보기 필터 (#5)
var flt=L.control({position:'bottomleft'});
flt.onAdd=function(){var d=L.DomUtil.create('div','info');
 d.innerHTML='<label style="cursor:pointer;font-weight:700"><input type="checkbox" id="fchk" onchange="applyFilter(this.checked)"> ⚠ 주의·위험만 보기 (PS/SBAS)</label>';
 L.DomEvent.disableClickPropagation(d);return d;};flt.addTo(map);
function applyFilter(on){
 if(on){psNorm.forEach(function(m){psL.removeLayer(m);});sbNorm.forEach(function(m){sbL.removeLayer(m);});}
 else{psNorm.forEach(function(m){psL.addLayer(m);});sbNorm.forEach(function(m){sbL.addLayer(m);});}}
// 날짜 표시선 선택(단일/복수) — 그래프에 옅은 회색 세로 점선
var dctl=L.control({position:'bottomleft'});
dctl.onAdd=function(){var d=L.DomUtil.create('div','info');
 d.innerHTML='<b>날짜 표시선</b> <span style="font-weight:400;color:#888">(직접 입력→최근접 에폭에 표시, 후 포인트 클릭)</span><br>'
  +'<input id="dsel" type="text" placeholder="예: 2022-08-03" style="width:120px" '
  +'onkeydown="if(event.key===\'Enter\'){addDate();event.preventDefault();}"> '
  +'<button onclick="addDate()">추가</button> <button onclick="clrDate()">지우기</button>'
  +'<div id="dsells" style="font-size:11px;color:#555;margin-top:3px">(없음)</div>';
 L.DomEvent.disableClickPropagation(d);L.DomEvent.disableScrollPropagation(d);return d;};dctl.addTo(map);
function refreshSel(){var e=document.getElementById('dsells');if(e)e.textContent=selDates.length?('표시: '+selDates.join(', ')):'(없음)';}
function addDate(){var e=document.getElementById('dsel');var v=(e&&e.value||'').trim();var ls=document.getElementById('dsells');
 if(!v||isNaN(Date.parse(v))){if(ls)ls.textContent='형식 오류 (예: 2022-08-03)';return;}
 if(selDates.indexOf(v)<0){selDates.push(v);selDates.sort();}
 if(e)e.value=''; refreshSel(); if(map.closePopup)map.closePopup();}
function clrDate(){selDates=[];refreshSel();if(map.closePopup)map.closePopup();}
// 그래프 전체스케일 / 컬러바 범위 수동 조절 (날짜 표시선 '위'에 표시 — bottom은 나중 추가가 위)
var sctl=L.control({position:'bottomleft'});
sctl.onAdd=function(){var d=L.DomUtil.create('div','info');
 d.innerHTML='<b>그래프 전체스케일 (mm)</b> <span style="font-weight:400;color:#888">(비우면 자동)</span><br>'
  +'min <input id="gmin" type="number" step="1" style="width:56px" onkeydown="if(event.key===\'Enter\')applyGraph()"> '
  +'max <input id="gmax" type="number" step="1" style="width:56px" onkeydown="if(event.key===\'Enter\')applyGraph()"> '
  +'<button onclick="applyGraph()">적용</button> <button onclick="autoGraph()">자동</button>'
  +'<div style="border-top:1px solid #eee;margin:5px 0 4px"></div>'
  +'<b>컬러바 velocity (mm/yr)</b><br>'
  +'min <input id="cmin" type="number" step="0.5" style="width:56px" onkeydown="if(event.key===\'Enter\')applyCbar()"> '
  +'max <input id="cmax" type="number" step="0.5" style="width:56px" onkeydown="if(event.key===\'Enter\')applyCbar()"> '
  +'<button onclick="applyCbar()">적용</button> <button onclick="autoCbar()">자동</button>'
  +'<div id="gsmsg" style="font-size:11px;color:#555;margin-top:3px"></div>';
 L.DomEvent.disableClickPropagation(d);L.DomEvent.disableScrollPropagation(d);return d;};sctl.addTo(map);
function applyGraph(){var a=parseFloat(document.getElementById('gmin').value),b=parseFloat(document.getElementById('gmax').value);
 if(isFinite(a)&&isFinite(b)&&b>a){gMin=a;gMax=b;}else{gMin=null;gMax=null;}
 gsMsg(); if(map.closePopup)map.closePopup();}
function autoGraph(){gMin=null;gMax=null;var a=document.getElementById('gmin'),b=document.getElementById('gmax');if(a)a.value='';if(b)b.value='';
 gsMsg(); if(map.closePopup)map.closePopup();}
function applyCbar(){var a=parseFloat(document.getElementById('cmin').value),b=parseFloat(document.getElementById('cmax').value);
 if(isFinite(a)&&isFinite(b)&&b>a){cbMin=a;cbMax=b;recolorAll();updateCbarLeg();gsMsg();}else gsMsg();}
function autoCbar(){cbMin=-D.vmax;cbMax=D.vmax;var a=document.getElementById('cmin'),b=document.getElementById('cmax');if(a)a.value='';if(b)b.value='';
 recolorAll();updateCbarLeg();gsMsg();}
function recolorAll(){var i;for(i=0;i<psMk.length;i++)psMk[i][0].setStyle({fillColor:colorFor(psMk[i][1])});
 for(i=0;i<sbMk.length;i++)sbMk[i][0].setStyle({fillColor:colorFor(sbMk[i][1])});}
function updateCbarLeg(){var l=document.getElementById('cbL'),c=document.getElementById('cbC'),r=document.getElementById('cbR');
 if(l)l.textContent=cbMin.toFixed(1);if(c)c.textContent=((cbMin+cbMax)/2).toFixed(1);if(r)r.textContent=(cbMax>=0?'+':'')+cbMax.toFixed(1);}
function gsMsg(){var e=document.getElementById('gsmsg');if(!e)return;
 e.textContent='그래프 '+((gMin!=null&&gMax!=null)?(gMin+'~'+gMax+'mm'):'자동')+' · 컬러바 '+cbMin.toFixed(1)+'~'+cbMax.toFixed(1);}
// 싱크홀 발생지 — 화살표(↓) 마커. 발생점(데이터) + 사용자 추가(복수) 지원.
// 기능1: 독립 레이어(레이어컨트롤 체크박스) + 클릭 팝업(지역·발생일·개요·양성/음성).
var skL=L.layerGroup().addTo(map);
var skList=[];   // 사용자 추가분 [{lat,lon,m}]
function skIcon(){return L.divIcon({className:'',iconSize:[26,34],iconAnchor:[13,33],html:
 '<svg width="26" height="34" viewBox="0 0 26 34">'
 +'<line x1="13" y1="3" x2="13" y2="23" stroke="#fff" stroke-width="6"/>'
 +'<polygon points="13,33 3,18 23,18" fill="#fff"/>'
 +'<line x1="13" y1="4" x2="13" y2="22" stroke="#c0392b" stroke-width="3"/>'
 +'<polygon points="13,31 5,19 21,19" fill="#c0392b"/></svg>'});}
function skInfoPopup(info){var gc=(info.group==='양성')?'#c0392b':(info.group==='음성'?'#2166ac':'#7f8c8d');
 return '<div class="pop"><b>🕳 싱크홀 발생지</b><table class="pt" style="margin-top:4px">'
  +'<tr><th>지역</th><td>'+(info.quad||'')+' '+(info.region_name||'')+'</td></tr>'
  +'<tr><th>구분</th><td><span class="badge" style="background:'+gc+';color:#fff">'+(info.group||'-')+'</span></td></tr>'
  +'<tr><th>발생일</th><td>'+(info.event_date||'-')+'</td></tr>'
  +'<tr><th>개요</th><td>'+(info.desc||'-')+'</td></tr>'
  +'<tr><th>원인/비고</th><td>'+(info.cause||'-')+'</td></tr></table></div>';}
function addSinkArrow(lat,lon,info){var m=L.marker([lat,lon],{icon:skIcon(),zIndexOffset:1000});
 m.bindTooltip('싱크홀',{permanent:true,direction:'top',className:'poi-lbl',offset:[0,-30]});
 m.on('click',function(e){var h=info?skInfoPopup(info):('<div class="pop"><b>🕳 싱크홀(추가 위치)</b><br>위 '+lat.toFixed(5)+', 경 '+lon.toFixed(5)+'</div>');
  L.popup({maxWidth:360,minWidth:230}).setLatLng([lat,lon]).setContent(h).openOn(map);L.DomEvent.stopPropagation(e);});
 m.addTo(skL);return m;}
if(D.poi)addSinkArrow(D.poi.lat,D.poi.lon,D.poi);   // 데이터 발생점(케이스 정보 팝업)
// 싱크홀 발생지 레이어를 레이어 컨트롤에 체크박스로 추가(PS/SBAS/시추공과 나란히)
layersCtl.addOverlay(skL,'🕳 싱크홀 발생지'+(D.poi?' (1)':''));
// 지반침하 사고 리스트(전국 Open API 지오코딩본, AOI bbox 내) — 독립 토글 레이어. 케이스 발생지(⬇)와 별개.
var subL=L.layerGroup().addTo(map);
function subPopup(a){
 function n(x){return (x!=null&&isFinite(x)&&x>0)?x.toFixed(1):'-';}
 var dmg=[];if(a.death)dmg.push('사망 '+a.death);if(a.injury)dmg.push('부상 '+a.injury);if(a.veh)dmg.push('차량 '+a.veh);
 return '<div class="pop"><b>⚠ 지반침하 사고</b> <span style="color:#888">#'+(a.no||'')+'</span>'
  +'<table class="pt" style="margin-top:4px">'
  +'<tr><th>발생일</th><td>'+(a.date||'-')+'</td></tr>'
  +'<tr><th>위치</th><td>'+(a.loc||'-')+'</td></tr>'
  +'<tr><th>규모(가로×세로×깊이)</th><td>'+n(a.w)+' × '+n(a.l)+' × '+n(a.d)+' m</td></tr>'
  +(a.grd?'<tr><th>지반종류</th><td>'+a.grd+'</td></tr>':'')
  +'<tr><th>피해</th><td>'+(dmg.length?dmg.join(' · '):'없음')+'</td></tr>'
  +'<tr><th>복구</th><td>'+(a.status||'-')+'</td></tr>'
  +(a.detail?'<tr><th>경위</th><td>'+a.detail+'</td></tr>':'')
  +'</table><div style="font-size:10px;color:#999;margin-top:3px">위치=주소 지오코딩('+(a.gtype||'')+') · 실제 발생지점과 오차 가능</div></div>';}
(D.subs||[]).forEach(function(a){
 var m=L.circleMarker([a.lat,a.lon],{radius:7,color:'#7a3b00',weight:2,fillColor:'#ff8c1a',fillOpacity:0.9});
 m.bindTooltip('지반침하',{direction:'top',className:'poi-lbl',offset:[0,-8]});
 m.on('click',function(e){L.popup({maxWidth:420,minWidth:280}).setLatLng([a.lat,a.lon]).setContent(subPopup(a)).openOn(map);L.DomEvent.stopPropagation(e);});
 m.addTo(subL);});
layersCtl.addOverlay(subL,'⚠ 지반침하 사고 리스트 ('+((D.subs||[]).length)+')');
// 싱크홀 위치 추가 컨트롤(좌하단) — 한 AOI 복수 발생 대응
var skctl=L.control({position:'bottomleft'});
skctl.onAdd=function(){var d=L.DomUtil.create('div','info');
 d.innerHTML='<b>싱크홀 위치 추가</b> <span style="font-weight:400;color:#888">(화살표, 복수 가능)</span><br>'
  +'위도 <input id="sklat" type="number" step="0.00001" style="width:90px" placeholder="35.15085" onkeydown="if(event.key===\'Enter\')addSink()"> '
  +'경도 <input id="sklon" type="number" step="0.00001" style="width:90px" placeholder="128.98182" onkeydown="if(event.key===\'Enter\')addSink()"> '
  +'<button onclick="addSink()">추가</button> <button onclick="clrSink()">추가분 지우기</button>'
  +'<div id="sklist" style="font-size:11px;color:#555;margin-top:3px">(추가 없음)</div>';
 L.DomEvent.disableClickPropagation(d);L.DomEvent.disableScrollPropagation(d);return d;};skctl.addTo(map);
function addSink(){var la=parseFloat(document.getElementById('sklat').value),lo=parseFloat(document.getElementById('sklon').value);
 var ls=document.getElementById('sklist');
 if(!isFinite(la)||!isFinite(lo)||la<-90||la>90||lo<-180||lo>180){if(ls)ls.textContent='위경도 형식 오류';return;}
 var m=addSinkArrow(la,lo,null);skList.push({lat:la,lon:lo,m:m});
 var a=document.getElementById('sklat'),b=document.getElementById('sklon');if(a)a.value='';if(b)b.value='';
 skRefresh();if(map.setView)map.setView([la,lo],map.getZoom());}
function clrSink(){for(var i=0;i<skList.length;i++)skL.removeLayer(skList[i].m);skList=[];skRefresh();}
function skRefresh(){var ls=document.getElementById('sklist');if(!ls)return;
 if(!skList.length){ls.textContent='(추가 없음)';return;}
 var s='추가: ';for(var i=0;i<skList.length;i++)s+=(i?' · ':'')+skList[i].lat.toFixed(5)+','+skList[i].lon.toFixed(5);ls.textContent=s;}
var lg=L.control({position:'bottomright'});
lg.onAdd=function(){var d=L.DomUtil.create('div','info lg');var vm=D.vmax.toFixed(1);
 d.innerHTML='<div class="ttl">'+D.quad+' '+D.title+' <span style="font-weight:400">('+D.group+')</span></div>'
 +'PS <b>'+D.nps+'</b> · SBAS <b>'+D.nsb+'</b> · 시추공 <b>'+D.nbore+'</b> · 클릭→상세<br>'
 +(D.ps_dsc?'<div style="margin:2px 0;color:#555">+ 하강/DSC: PS <b>'+D.nps_dsc+'</b> · SBAS <b>'+D.nsb_dsc+'</b> <span style="color:#888">(우상단 레이어에서 토글)</span></div>':'')
 +'<div style="margin:5px 0 2px">PS/SBAS LOS velocity (mm/yr)</div><div class="cbar"></div>'
 +'<div style="display:flex;justify-content:space-between;width:230px"><span id="cbL">-'+vm+'</span><span id="cbC">0</span><span id="cbR">+'+vm+'</span></div>'
 +'<div style="margin-top:2px"><b style="color:#b2182b">빨강=침하(-)</b> · <b style="color:#2166ac">파랑=융기(+)</b></div>'
 +'<div style="margin-top:6px">지반등급: <span class="dot" style="background:#c0392b"></span>연약 <span class="dot" style="background:#e67e22"></span>주의 <span class="dot" style="background:#27ae60"></span>양호</div>'
 +(D.geo_litho?'<div style="margin-top:3px"><span class="dot" style="background:#27ae60;opacity:.4"></span> 지질도 면 (설명=좌상단 임계치 탭)</div>':'')
 +'<div style="margin-top:3px"><span style="color:#c0392b;font-weight:900;font-size:15px">⬇</span> 싱크홀(발생·추가)</div>'
 +'<div style="margin-top:3px"><span class="dot" style="background:#ff8c1a;border:2px solid #7a3b00"></span> 지반침하 사고 리스트 <span style="color:#888">('+((D.subs||[]).length)+'건, AOI 내)</span></div>'
 +(D.lead?'<div style="margin-top:6px;padding-top:5px;border-top:1px solid #eee"><b>🕒 경보 리드타임</b><br>사고 '+D.lead.event_date+' 기준<br>첫 주의/위험 <b style="color:#c0392b">'+D.lead.leadtime_days.toLocaleString()+'일 전</b> 경보 ('+D.lead.detector+' 탐지)</div>':'');
 return d;};lg.addTo(map);
function togTh(){var b=document.getElementById('thbody'),t=document.getElementById('thtog');
 if(b.style.display==='none'){b.style.display='block';t.textContent='[−]';}else{b.style.display='none';t.textContent='[+]';}}
var allpts=D.ps.concat(D.sbas).concat(D.bore);
if(allpts.length){var bb=L.latLngBounds(allpts.map(function(p){return [p[1],p[0]];}));if(D.poi)bb.extend([D.poi.lat,D.poi.lon]);map.fitBounds(bb.pad(0.03));}
updateCbarLeg();gsMsg();
</script></body></html>"""


def build_region(region, bore_all, layerdet):
    D = region_payload(region, bore_all, layerdet)
    # 같은 파일에 DSC(하강) 결과를 별도 레이어로 추가 (기존 상승 레이어는 그대로)
    if region in DSC_SIBLING:
        sib = DSC_SIBLING[region]
        try:
            Dd = region_payload(sib, bore_all, layerdet)
            D["ps_dsc"] = Dd["ps"]; D["sbas_dsc"] = Dd["sbas"]
            D["dates_dsc"] = Dd["dates"]; D["dates_sb_dsc"] = Dd["dates_sb"]
            D["gy_ps_dsc"] = Dd["gy_ps"]; D["gy_sb_dsc"] = Dd["gy_sb"]
            D["nps_dsc"] = Dd["nps"]; D["nsb_dsc"] = Dd["nsb"]
            D["ps_gg_dsc"] = Dd["ps_gg"]; D["sb_gg_dsc"] = Dd["sb_gg"]
            print(f"  + DSC 레이어 병합: {sib} (PS {Dd['nps']}, SBAS {Dd['nsb']})")
        except Exception as e:
            print(f"  [DSC 병합 경고] {sib}: {e}")
    payload = json.dumps(D, ensure_ascii=False, separators=(",", ":"))
    html = (REGION_TEMPLATE.replace("__TITLE__", D["title"])
            .replace("__THRESH__", thresh_html(region in geol.REGION_SHEET,
                     geol.SCALE_LABEL.get(geol.REGION_SHEET.get(region, ""), "1:5만+1:25만")))
            .replace("__PAYLOAD__", payload))
    fp = os.path.join(MAP_DIR, f"{region}.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(html)
    mb = os.path.getsize(fp) / 1e6
    print(f"  region map: {fp}  (PS {D['nps']}, SBAS {D['nsb']}, 시추공 {D['nbore']}, {mb:.0f}MB)")
    return D


# ---------------- 허브(AOI 사이드바 + 리포트) ----------------
# AOI 목록(9개). center=[lat,lon] (AOI.xlsx SNWE 중심 또는 발생점). analyzed=지도/데이터 유무.
AOI_HUB = [
    {"key": "Seoul_Gangdong",       "quad": "①", "name": "서울 강동구 명일동",      "group": "positive",         "center": [37.5459, 127.1558], "analyzed": True},
    {"key": "Gyeonggi_Gwangmyeong", "quad": "②", "name": "경기 광명 신안산선 5-2",   "group": "positive",         "center": [37.4123, 126.8808], "analyzed": True},
    {"key": "Yangyang",             "quad": "⑦", "name": "강원 양양 낙산해변",        "group": "positive",         "center": [38.1175, 128.6320], "analyzed": True},
    {"key": "Seoul_Seodaemun",      "quad": "⑧", "name": "서울 서대문구 연희동",      "group": "positive",         "center": [37.5665, 126.9240], "analyzed": True},
    {"key": "Busan_Sasang_Hadan",   "quad": "⑨", "name": "부산 사상~하단선",         "group": "positive",         "center": [35.1494, 128.9815], "analyzed": True},
    # 음성(FP 기준선) — 2026-07-09 재분류: 만덕④(대심도 심부)·송도③
    {"key": "Incheon_Songdo",       "quad": "③", "name": "인천 송도국제도시",        "group": "negative",         "center": [37.3956, 126.6562], "analyzed": True},
    {"key": "Busan_Mandeok_Centum", "quad": "④", "name": "부산 만덕~센텀 대심도",     "group": "negative",         "center": [35.2076, 129.0736], "analyzed": True},
    {"key": None,                   "quad": "⑤", "name": "서울 GPR 공동복구 구간",    "group": "negative",         "center": [37.55, 126.98],     "analyzed": False},
    {"key": None,                   "quad": "⑥", "name": "안정지반 베이스라인",       "group": "negative",         "center": [37.3956, 126.6562], "analyzed": False},
]
GCOLOR = {"positive": "#c0392b", "positive_shallow": "#e67e22", "negative": "#2166ac"}


def _bore_grade_dist(bore_all, center, half=0.06):
    m = (np.abs(bore_all["lon"] - center[1]) < half) & (np.abs(bore_all["lat"] - center[0]) < half)
    sub = bore_all[m]
    if not len(sub):
        return "AOI 인근 시추공 없음", None
    vc = sub["등급"].value_counts().to_dict()
    txt = " · ".join(f"{k} {int(v)}" for k, v in vc.items())
    return f"{len(sub)}공 ({txt})", round(float(sub["alpha"].median()), 2)


def make_report(a, bore_all, cases, bufs, stats):
    """지역 리포트 HTML (분석 결과값만)."""
    region = a["key"]; meta = REGIONS.get(region, {}); ev = EVENTS.get(region, {})
    grp = {"positive": "양성(붕괴 발생)", "negative": "음성(비붕괴)"}.get(a["group"], a["group"])
    if not a["analyzed"] or region not in stats.index:
        return (f"<h2>{a['quad']} {a['name']}</h2><p class='gtag'>{grp}</p>"
                f"<p>이 AOI는 본 분석의 InSAR/시추공 데이터가 없어 <b>미분석</b>입니다. "
                f"(신규 수집·처리 필요 case)</p>")
    st = stats.loc[region]
    h = [f"<h2>{a['quad']} {a['name']}</h2><p class='gtag' style='color:{GCOLOR[a['group']]}'>{grp}</p>"]
    # 개요
    h.append("<h3>지역 개요</h3><ul>")
    if ev.get("event_date"): h.append(f"<li>사고일: <b>{ev['event_date']}</b></li>")
    if meta.get("note"): h.append(f"<li>{meta['note']}</li>")
    h.append(f"<li>InSAR 스택: PS {int(st['n_ps']):,}점 · SBAS {int(st['n_sbas']):,}점</li></ul>")
    # 판정 결과(지역 전체)
    fw, fd = int(st["final_주의"]), int(st["final_위험"])
    h.append("<h3>판정 결과 (지역 전체 SBAS 판정점)</h3><ul>"
             f"<li>주의 {fw:,} · 위험 {fd:,} / 정상 {int(st['n_sbas'])-fw-fd:,}</li>"
             f"<li>hotspot {int(st['sbas_hotspot']):,} · PS공백 {st['ps_void_frac']*100:.0f}%</li>"
             f"<li>근거분류(경보): ①합치 {int(st['①합치'])} · ②SBAS단독 {int(st['②SBAS단독'])} · ③불일치 {int(st['③불일치'])}</li></ul>")
    # 발생점 버퍼(있으면)
    bf = bufs[bufs.region == region] if bufs is not None else None
    if bf is not None and len(bf):
        h.append("<h3>발생점 버퍼(200m) 판정</h3><table class='rt'><tr><th>기법</th><th>최고등급</th><th>주의/위험</th><th>대표속도</th><th>대표누적</th><th>대표α</th></tr>")
        for _, r in bf.iterrows():
            h.append(f"<tr><td>{r['kind']}</td><td>{r['max_grade']}</td><td>{int(r['n_주의'])}/{int(r['n_위험'])}</td>"
                     f"<td>{r.get('med_rv','-')} (p90 {r.get('p90_rv','-')})</td><td>{r.get('med_rc','-')} (p90 {r.get('p90_rc','-')})</td><td>{r.get('med_alpha','-')}</td></tr>")
        h.append("</table>")
    elif ev.get("lon") is None and a["group"] != "negative":
        h.append("<p style='color:#a04000'>⚠ 발생점 좌표 미기재(AOI.xlsx) → 버퍼 판정 보류. 좌표 확보 시 추가.</p>")
    # 지반
    dist, ma = _bore_grade_dist(bore_all, a["center"])
    h.append(f"<h3>지반 조건(시추공)</h3><ul><li>AOI 인근 {dist}</li>")
    if ma is not None: h.append(f"<li>대표 α(중앙): {ma}</li>")
    h.append("</ul>")
    # 지질 기반 보완 (수치지질도 보유 지역)
    gcsv = os.path.join(OUTC, f"geo_integrated_{region}.csv")
    if region in geol.REGION_SHEET and os.path.exists(gcsv):
        gd = pd.read_csv(gcsv, encoding="utf-8-sig")
        ngap = int(gd["gap"].sum()); nfill = int((gd["gap"] & (gd["source"] == "geology") & (gd["final_ground_grade"] != "미상")).sum())
        vc = gd[gd["gap"]]["final_ground_grade"].value_counts()
        dist_txt = " · ".join(f"{k} {int(vc[k]):,}" for k in ["연약", "주의", "양호", "미상"] if k in vc)
        h.append(f"<h3>지질 기반 보완 (수치지질도 {geol.REGION_SHEET[region]})</h3><ul>"
                 f"<li>시추공 공백(>{int(geol.G['gap_dist_m'])}m): {ngap:,}점 → 지질로 {nfill:,}점 메움({nfill/max(1,ngap)*100:.0f}%)</li>"
                 f"<li>공백점 지질등급: {dist_txt} (confidence=medium)</li>"
                 f"<li>카르스트 {int(gd['karst'].sum()):,} · 단층인접 {int(gd['fault_adj'].sum()):,}</li></ul>")
    # 리드타임/판정
    if cases is not None and region in cases.index:
        c = cases.loc[region]
        h.append("<h3>리드타임 · 판정</h3><ul>")
        if pd.notna(c.get("leadtime_days", None)):
            h.append(f"<li>첫 상위등급 진입 → 사고: <b>{int(c['leadtime_days']):,}일</b> 선행 (탐지: {c.get('detector','-')})</li>")
        h.append(f"<li>사례판정: <b>{c['verdict']}</b></li>")
        if region in QUAD3_INSAR_LIMIT:
            h.append("<li style='color:#a04000'>③분면: 천층/노후관 메커니즘 → PS-InSAR 물리적 미탐 가능. (A)제약 예외로 정성 해석.</li>")
        h.append("</ul>")
    elif a["group"] == "negative":
        h.append("<h3>판정</h3><ul><li>음성(비붕괴) 기준선. 송도는 실제 광역 압밀침하(속도 중앙 ~19mm/yr)로 "
                 "InSAR 경보율이 높으나 붕괴는 아님 → <b>\"침하 ≠ 붕괴\" InSAR 한계 baseline</b>.</li></ul>")
    # 기능3: 발생(양성) AOI — 침하 개시(전조) 변곡점 + 미분 상세 그래프
    if EVENTS.get(region, {}).get("type") == "positive" and EVENTS.get(region, {}).get("lon") is not None:
        try:
            h.append(inflection_report_html(region, bore_all))
        except Exception as e:
            h.append(f"<p style='color:#a04000'>[변곡점 그래프 생략: {e}]</p>")
    return "".join(h)


HUB_TEMPLATE = r"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>CLAB 지반침하 워닝 — AOI 통합 허브</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
html,body{height:100%;margin:0;font-family:sans-serif}
#wrap{display:flex;height:100%}
#side{width:300px;background:#1f2d3d;color:#ecf0f1;overflow-y:auto;flex:none}
#side h1{font-size:15px;padding:14px 14px 6px;margin:0}
#side .sub{font-size:11px;color:#9fb3c8;padding:0 14px 10px}
.grp{font-size:11px;color:#7f8c9a;padding:8px 14px 2px;text-transform:uppercase;letter-spacing:.5px}
.aoi{display:flex;align-items:center;gap:8px;padding:9px 14px;cursor:pointer;border-left:4px solid transparent}
.aoi:hover{background:#2c3e50}.aoi.dis{opacity:.45;cursor:default}
.aoi .q{font-weight:700;width:18px}.aoi .nm{flex:1;font-size:13px}
.aoi .ic{font-size:15px}
#main{flex:1;position:relative}#map{height:100%}
.legend{position:absolute;bottom:12px;right:12px;z-index:900;background:#fff;color:#222;padding:8px 10px;border-radius:6px;font-size:12px;box-shadow:0 1px 6px rgba(0,0,0,.3)}
.legend .dot{width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:6px;vertical-align:middle}
.thbox{position:absolute;top:10px;right:10px;z-index:900;background:#fff;color:#222;border-radius:7px;box-shadow:0 1px 8px rgba(0,0,0,.3);font-size:12px;max-width:340px}
.thhd{padding:6px 10px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}
.thhd button{border:none;background:#eee;border-radius:4px;cursor:pointer;font-weight:700;padding:1px 8px}
#thbody{padding:8px 10px}.tht{border-collapse:collapse;font-size:11px;width:100%}.tht td,.tht th{border:1px solid #ddd;padding:2px 5px;text-align:center}
.tht th{background:#f4f4f4}.g0{background:#d5f5e3;color:#196f3d;font-weight:700}.g1{background:#fdebd0;color:#a04000;font-weight:700}.g2{background:#fadbd8;color:#943126;font-weight:700}
.thnote{font-size:10.5px;color:#666;margin-top:5px;line-height:1.4}
#modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2000}
#mbox{background:#fff;max-width:720px;margin:4vh auto;max-height:88vh;overflow-y:auto;border-radius:10px;padding:22px 26px;position:relative}
#mbox h2{margin:0 0 2px}#mbox h3{margin:14px 0 4px;border-bottom:2px solid #eee;padding-bottom:3px;font-size:14px}
#mbox .gtag{font-weight:700;margin:0 0 8px}#mbox ul{margin:4px 0;padding-left:20px}#mbox li{margin:2px 0;font-size:13px}
.rt{border-collapse:collapse;font-size:12px;margin-top:4px}.rt td,.rt th{border:1px solid #ddd;padding:3px 7px;text-align:center}.rt th{background:#f4f4f4}
#mclose{position:absolute;top:12px;right:16px;cursor:pointer;font-size:22px;color:#888;border:none;background:none}
.mbtn{display:inline-block;margin-top:14px;background:#2c3e50;color:#fff;padding:7px 14px;border-radius:6px;text-decoration:none;font-weight:700;font-size:13px}
.mbtn.dis{background:#bbb;pointer-events:none}
</style></head><body>
<div id="wrap">
<div id="side"><h1>CLAB 지반침하·함몰 워닝</h1><div class="sub">AOI 통합 허브 · PS/SBAS/시추공 · ⚠ 잠정 임계치</div><div id="aoilist"></div></div>
<div id="main"><div id="map"></div>
__THRESH__
<div class="legend"><b>AOI 케이스</b><br><span class="dot" style="background:#c0392b"></span>양성(발생)<br><span class="dot" style="background:#2166ac"></span>음성/미분석</div>
</div></div>
<div id="modal"><div id="mbox"><button id="mclose" onclick="closeM()">×</button><div id="mcontent"></div></div></div>
<script>
var AOI=__AOI__;var REPORTS=__REPORTS__;var GCOL={positive:'#c0392b',positive_shallow:'#e67e22',negative:'#2166ac'};
var map=L.map('map').setView([36.5,127.8],7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
function mapHref(k){return '통합맵/'+k+'.html';}
function openReport(i){var a=AOI[i];document.getElementById('mcontent').innerHTML=REPORTS[i]
 +(a.analyzed&&a.key?'<a class="mbtn" href="'+mapHref(a.key)+'">🗺 상세 통합맵 열기 (PS/SBAS/시추공)</a>':'<span class="mbtn dis">상세 지도 없음</span>');
 document.getElementById('modal').style.display='block';}
function closeM(){document.getElementById('modal').style.display='none';}
document.getElementById('modal').addEventListener('click',function(e){if(e.target.id==='modal')closeM();});
// 사이드바
var groups=[['positive','양성 (붕괴 발생)'],['negative','음성 / 미분석']];
var sb=document.getElementById('aoilist');
groups.forEach(function(g){var hd=document.createElement('div');hd.className='grp';hd.textContent=g[1];sb.appendChild(hd);
 AOI.forEach(function(a,i){if(a.group!==g[0])return;var d=document.createElement('div');d.className='aoi'+(a.analyzed?'':' dis');
  d.style.borderLeftColor=GCOL[a.group];
  d.innerHTML='<span class="q">'+a.quad+'</span><span class="nm">'+a.name+'</span><span class="ic">'+(a.analyzed?'📄':'—')+'</span>';
  d.onclick=function(){openReport(i);};sb.appendChild(d);});});
// 개요맵 마커
AOI.forEach(function(a,i){var m=L.circleMarker(a.center,{radius:a.analyzed?9:6,color:'#fff',weight:2,fillColor:GCOL[a.group],fillOpacity:a.analyzed?0.9:0.5});
 m.addTo(map).bindTooltip(a.quad+' '+a.name,{direction:'top'});
 m.on('click',function(){openReport(i);});});
function togTh(){var b=document.getElementById('thbody'),t=document.getElementById('thtog');
 if(b.style.display==='none'){b.style.display='block';t.textContent='[−]';}else{b.style.display='none';t.textContent='[+]';}}
</script></body></html>"""


def build_hub(bore_all):
    cases = pd.read_csv(os.path.join(OUTC, "step3_case_verification.csv"), encoding="utf-8-sig").set_index("region") \
        if os.path.exists(os.path.join(OUTC, "step3_case_verification.csv")) else None
    bufs = pd.read_csv(os.path.join(OUTC, "step3_buffer_grades.csv"), encoding="utf-8-sig") \
        if os.path.exists(os.path.join(OUTC, "step3_buffer_grades.csv")) else None
    stats = pd.read_csv(os.path.join(OUTC, "step2_region_stats.csv"), encoding="utf-8-sig").set_index("region")
    reports = [make_report(a, bore_all, cases, bufs, stats) for a in AOI_HUB]
    aoi_js = [{"quad": a["quad"], "name": a["name"], "group": a["group"],
               "center": a["center"], "analyzed": a["analyzed"], "key": a["key"]} for a in AOI_HUB]
    html = (HUB_TEMPLATE.replace("__THRESH__", thresh_html(True))
            .replace("__AOI__", json.dumps(aoi_js, ensure_ascii=False))
            .replace("__REPORTS__", json.dumps(reports, ensure_ascii=False)))
    fp = os.path.join(OUT_DIR, "CLAB_통합맵.html")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  hub: {fp}")
    return fp


def main(regions=None):
    regions = regions or list(REGIONS.keys())
    bore = pd.read_csv(os.path.join(OUTC, "step1_borehole_grade.csv"), encoding="utf-8-sig")
    bore["공번"] = bore["공번"].astype(str)
    # near-AOI 시추공 지층상세 (전 지역 bbox union)
    codes = []
    import loaders as _l
    for R in regions:
        ps = _l.load_ps(R)
        m = bore.lon.between(ps["lon"].min()-0.05, ps["lon"].max()+0.05) & \
            bore.lat.between(ps["lat"].min()-0.05, ps["lat"].max()+0.05)
        codes += bore.loc[m, "공번"].tolist()
    print(f"지층상세 대상 시추공: {len(set(codes))}공")
    layerdet = borehole_layer_detail(set(codes))
    for R in regions:
        build_region(R, bore, layerdet)
    build_hub(bore)
    print("완료: <DATA_ROOT>/CLAB/integrated_maps/CLAB_통합맵.html")


if __name__ == "__main__":
    main()
