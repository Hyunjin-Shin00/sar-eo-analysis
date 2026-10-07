#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SBAS 결과 → 위험규칙(T2k) 적용 → 위험구역 산출 — 부산 사상~하단

입력  : 02_sbas/out/Busan_Sasang_Hadan_sbas_ps_v.csv   (라이브 or 폴백, 어느 쪽이든 동일)
규칙  : rule_t2k_sasang.json  (coh0.3 / tcoh0.7 / 버퍼 400m / SBAS 단독, 지표 3종 평균백분위 ≥ 0.963)
출력  : sasang_risk_zones.geojson|.shp   위험구역 폴리곤        ← 지도에 빨강으로 표시
        sasang_risk_peaks.geojson        구역별 대표점 + 판정근거 400m 버퍼
        sasang_risk_score.tif            위험점수 래스터(0~1)
        sasang_sbas_velocity.tif         침하속도 래스터(mm/yr, −=침하)
        sasang_sbas_points.geojson       SBAS 관측점(속도·1년누적침하)
        risk_summary.json                구역 수·면적·점수 요약

PROJ 운영 코드(sinkhole/loaders.py · sbas_sweep/featx_cache.py)의 전처리·지표 정의를
그대로 옮겨 담았고, 외부 의존 없이 이 폴더만으로 재현된다.

usage: python3 apply_risk_rule.py [--sbas CSV] [--grid 40] [--out .]
"""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "2")
import sys, json, time, argparse
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(HERE)
DEF_SBAS = os.path.join(DEMO, "02_sbas", "out", "Busan_Sasang_Hadan_sbas_ps_v.csv")
RULE = os.path.join(HERE, "rule_t2k_sasang.json")
ALPHA = os.path.join(HERE, "ground_alpha_sasang.csv")
BBOX = (35.1294, 35.1664, 128.9677, 129.0049)     # S,N,W,E — AOI
CRS_M = 32652                                      # UTM 52N (거리 계산)


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--sbas", default=DEF_SBAS)
    p.add_argument("--grid", type=float, default=20.0, help="위험 판정 격자 간격(m)")
    p.add_argument("--smooth", type=float, default=10.0,
                   help="구역 경계 정리 반경(m). 계단형 경계를 닫음. 0=원본 격자")
    p.add_argument("--min_area_ha", type=float, default=0.05,
                   help="이 면적 미만의 파편 구역은 제외(제외 개수는 요약에 기록)")
    p.add_argument("--asof", type=float, default=None,
                   help="판정 기준 시점(소수연도, 예 2021.0 = 2020년 말까지의 관측만 사용). "
                        "미지정=최신. 지정 시 출력 파일명에 _asofYYYY 접미사")
    p.add_argument("--out", default=HERE)
    return p.parse_args()


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


def main():
    a = parse()
    T0 = time.time()
    rule = json.load(open(RULE))
    Rbuf = float(rule["config"]["buffer_m"]); TH = float(rule["threshold"])
    comb = rule["combine"]
    log("규칙 %s · 지표 %s [%s] ≥ %.3f · 버퍼 %.0fm"
        % (rule["config"], [f["key"] for f in rule["features"]], comb, TH, Rbuf))

    # ── SBAS 결과 로드 + PROJ 전처리 ──
    df = pd.read_csv(a.sbas)
    dcols = [c for c in df.columns if c.startswith("D") and len(c) == 9 and c[1:].isdigit()]
    years = np.array([int(c[1:5]) + (pd.Timestamp(int(c[1:5]), int(c[5:7]), int(c[7:9]))
                                     - pd.Timestamp(int(c[1:5]), 1, 1)).days / 365.25 for c in dcols])
    lon = df.Longitude.to_numpy(float); lat = df.Latitude.to_numpy(float)
    vel = df.velocity.to_numpy(float); disp = df[dcols].to_numpy(np.float32)
    pp = rule["preprocess"]
    disp, nfix = deunwrap(disp, pp["deunwrap"])
    disp, vel = cmc(disp, vel)
    log("SBAS %d점 · %d에폭 (%s~%s) · 언래핑보정 %d · CMC 적용"
        % (len(df), len(dcols), dcols[0][1:], dcols[-1][1:], nfix))

    # ── as-of: 그 시점까지의 관측만 사용(과거 재현) ──
    sfx = ""
    if a.asof is not None:
        m_as = years <= a.asof
        if m_as.sum() < 6:
            log("에폭 부족(%d) — as-of %.2f 는 너무 이릅니다" % (m_as.sum(), a.asof)); sys.exit(2)
        yr = years[m_as]; dd = disp[:, m_as]
        tc = yr - yr.mean()
        vel = ((tc[None, :] * dd).sum(1) / (tc ** 2).sum())      # 그 시점까지의 속도로 갱신
        last = dcols[np.where(m_as)[0][-1]][1:]          # 실제 사용한 마지막 관측일 = 충돌 없는 식별자
        sfx = "_asof" + last
        log("as-of %.2f 적용 — %d/%d 에폭 사용 (~%s)" % (a.asof, m_as.sum(), len(years), last))

    # ── 지반등급 α 결합(최근접 5m) ──
    from pyproj import Transformer
    from scipy.spatial import cKDTree
    tr = Transformer.from_crs(4326, CRS_M, always_xy=True)
    x, y = tr.transform(lon, lat); x = np.asarray(x); y = np.asarray(y)
    ga = pd.read_csv(ALPHA, encoding="utf-8-sig")
    gx, gy = tr.transform(ga.lon.values, ga.lat.values)
    dist, gi = cKDTree(np.c_[gx, gy]).query(np.c_[x, y])
    alpha = ga.final_alpha.values[gi].astype(float)
    alpha[dist > 5.0] = 1.0
    alpha = np.where(np.isfinite(alpha) & (alpha > 0), alpha, 1.0)

    # ── 점별 지표 ──
    c1 = cum_window(disp, years, 1.0, pp["cum_robust_k"], a.asof)   # 최근 1년 누적침하(mm, +=침하)
    c1a = c1 / alpha
    xf_th = pp["xf_threshold_mm"]["c1"]
    tree = cKDTree(np.c_[x, y])

    # ── AOI 격자 스캔 ──
    S, N, W, E = BBOX
    x0, y0 = tr.transform(W, S); x1, y1 = tr.transform(E, N)
    gxs = np.arange(x0, x1 + a.grid, a.grid); gys = np.arange(y0, y1 + a.grid, a.grid)
    GX, GY = np.meshgrid(gxs, gys)
    P = np.c_[GX.ravel(), GY.ravel()]
    log("격자 %dx%d = %d셀 @%.0fm · 버퍼집계 시작" % (len(gys), len(gxs), len(P), a.grid))

    t1 = time.time()
    nb = np.zeros(len(P)); f_xf = np.full(len(P), np.nan); f_max = np.full(len(P), np.nan)
    for i, idx in enumerate(tree.query_ball_point(P, Rbuf, workers=-1)):
        if not idx:
            continue
        v1 = c1[idx]; v1 = v1[np.isfinite(v1)]
        v2 = c1a[idx]; v2 = v2[np.isfinite(v2)]
        nb[i] = len(idx)
        if len(v1):
            f_xf[i] = np.mean(v1 >= xf_th)
        if len(v2):
            f_max[i] = np.max(v2)
    log("버퍼집계 완료", t1)

    raw = {"nbuf": nb, "c1_xf": f_xf, "c1a_max": f_max}
    ps = []
    for f in rule["features"]:
        ps.append(pctl(raw[f["key"]], f["background_sorted"], f["flip"]))
    PS = np.vstack(ps)
    with np.errstate(invalid="ignore"):
        score = {"min": np.nanmin, "mean": np.nanmean, "max": np.nanmax}[comb](PS, axis=0)
    score[nb == 0] = np.nan
    risk = np.isfinite(score) & (score >= TH)
    SC = score.reshape(GX.shape); RK = risk.reshape(GX.shape)
    log("위험 셀 %d/%d (%.2f%%) · 점수 최대 %.3f"
        % (risk.sum(), np.isfinite(score).sum(), 100 * risk.sum() / max(1, np.isfinite(score).sum()),
           np.nanmax(score)))

    # ── 래스터 출력 ──
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.features import shapes
    os.makedirs(a.out, exist_ok=True)
    trf = from_origin(gxs[0] - a.grid / 2, gys[-1] + a.grid / 2, a.grid, a.grid)
    SCf = np.flipud(SC).astype(np.float32)
    prof = dict(driver="GTiff", height=SCf.shape[0], width=SCf.shape[1], count=1,
                dtype="float32", crs="EPSG:%d" % CRS_M, transform=trf, nodata=np.nan,
                compress="deflate")
    with rasterio.open(os.path.join(a.out, "sasang_risk_score%s.tif" % sfx), "w", **prof) as d:
        d.write(SCf, 1); d.update_tags(rule="T2k coh0.3/tcoh0.7/R400/SBAS", threshold=TH)

    # 속도 래스터(관측점 최근접, 버퍼 밖은 nodata)
    dv, iv = tree.query(P)
    VG = np.where(dv <= a.grid * 1.5, vel[iv], np.nan).reshape(GX.shape).astype(np.float32)
    with rasterio.open(os.path.join(a.out, "sasang_sbas_velocity%s.tif" % sfx), "w", **prof) as d:
        d.write(np.flipud(VG), 1); d.update_tags(unit="mm/yr", sign="negative=subsidence")

    # ── 위험구역 폴리곤(인접 셀 병합) ──
    import geopandas as gpd
    from shapely.geometry import shape, Point
    RKf = np.flipud(RK).astype(np.uint8)
    polys = [shape(g) for g, v in
             shapes(RKf, mask=RKf.astype(bool), transform=trf, connectivity=8) if v == 1]
    if polys and a.smooth > 0:
        from shapely.ops import unary_union
        u = unary_union(polys).buffer(a.smooth).buffer(-a.smooth)     # 계단경계 닫기
        polys = [p.simplify(a.grid / 2) for p in
                 (u.geoms if hasattr(u, "geoms") else [u]) if not p.is_empty]
    n_all = len(polys)
    dropped = [p for p in polys if p.area < a.min_area_ha * 1e4]
    polys = [p for p in polys if p.area >= a.min_area_ha * 1e4]
    gz = gpd.GeoDataFrame(geometry=polys, crs=CRS_M)
    if len(gz):
        gz = gz.explode(index_parts=False).reset_index(drop=True)
    log("위험구역 %d곳 (파편 %d곳 %.2fha 제외, <%.2fha)"
        % (len(gz), len(dropped), sum(p.area for p in dropped) / 1e4, a.min_area_ha))

    rows, peaks = [], []
    for i, geom in enumerate(gz.geometry):
        inz = geom.contains(gpd.points_from_xy(P[:, 0], P[:, 1]))
        sel = np.where(inz & risk)[0]
        if not len(sel):
            sel = np.where(inz)[0]
        j = sel[np.nanargmax(score[sel])]
        px, py = P[j]
        plon, plat = Transformer.from_crs(CRS_M, 4326, always_xy=True).transform(px, py)
        nearby = tree.query_ball_point([px, py], Rbuf)
        rows.append({"zone_id": i + 1, "area_m2": round(geom.area),
                     "area_ha": round(geom.area / 1e4, 2),
                     "score_max": round(float(score[sel].max()), 3),
                     "score_mean": round(float(np.nanmean(score[sel])), 3),
                     "peak_lon": round(plon, 6), "peak_lat": round(plat, 6),
                     "n_sbas_in_buffer": int(nb[j]),
                     "cum1yr_max_mm": round(float(np.nanmax(c1[nearby])), 1),
                     "cum1yr_over10mm_pct": round(float(f_xf[j] * 100), 1),
                     "vel_min_mm_yr": round(float(np.nanmin(vel[nearby])), 2),
                     "alpha_min": round(float(np.nanmin(alpha[nearby])), 2)})
        peaks.append(Point(px, py))
    gz = gz.assign(**{k: [r[k] for r in rows] for k in rows[0]}) if rows else gz
    gz = gz.sort_values("score_max", ascending=False).reset_index(drop=True) if len(gz) else gz

    gz.to_crs(4326).to_file(os.path.join(a.out, "sasang_risk_zones%s.geojson" % sfx), driver="GeoJSON")
    gz.to_crs(4326).to_file(os.path.join(a.out, "sasang_risk_zones%s.shp" % sfx), encoding="utf-8")

    gp = gpd.GeoDataFrame(pd.DataFrame(rows), geometry=peaks, crs=CRS_M)
    gp["geometry"] = gp.buffer(Rbuf)                       # 판정 근거가 된 400m 버퍼
    gp.to_crs(4326).to_file(os.path.join(a.out, "sasang_risk_peaks%s.geojson" % sfx), driver="GeoJSON")


    # ── SBAS 관측점(표시용) ──
    gpts = gpd.GeoDataFrame(
        pd.DataFrame({"velocity": np.round(vel, 2), "cum1yr_mm": np.round(c1, 1),
                      "alpha": alpha, "tcoh": df.tcoh.values}),
        geometry=gpd.points_from_xy(lon, lat), crs=4326)
    gpts.to_file(os.path.join(a.out, "sasang_sbas_points%s.geojson" % sfx), driver="GeoJSON")

    summary = {"region": "부산 사상~하단", "rule": rule["config"], "threshold": TH,
               "asof": a.asof, "asof_note": ("최신(전체 관측)" if a.asof is None else "%.2f 시점까지의 관측만 사용" % a.asof),
               "grid_m": a.grid, "smooth_m": a.smooth, "n_sbas_points": int(len(df)),
               "n_risk_zones": int(len(gz)),
               "risk_area_ha": round(float(sum(r["area_ha"] for r in rows)), 2),
               "fragments_dropped": {"n": len(dropped),
                                     "area_ha": round(sum(p.area for p in dropped) / 1e4, 3),
                                     "min_area_ha": a.min_area_ha},
               "cells_evaluated": int(np.isfinite(score).sum()), "cells_risk": int(risk.sum()),
               "score_max": round(float(np.nanmax(score)), 3),
               "performance_of_rule": rule["performance"],
               "zones": rows, "elapsed_sec": round(time.time() - T0, 1)}
    json.dump(summary, open(os.path.join(a.out, "risk_summary%s.json" % sfx), "w"),
              ensure_ascii=False, indent=1)
    log("완료 — 위험구역 %d곳 · %.1fha · %s" % (len(gz), summary["risk_area_ha"], a.out), T0)


if __name__ == "__main__":
    main()
