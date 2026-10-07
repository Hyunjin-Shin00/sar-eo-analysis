#!/usr/bin/env python3
"""Is the NE-SW gradient in the S1 secular map ground motion or a residual ramp?

The median-removed map puts the north-east (노원·도봉·강북·성북) below the city
median and the south-west (강서·양천·구로·금천) above it.  That is the opposite
of what the geology suggests -- the north-east is granite, the south-west is Han
river alluvium -- so it has to be checked rather than assumed.

Three independent checks:
  plane   how much of the field is a single linear tilt across the city
  height  does the rate track topography (a DEM-error or tropospheric signature)
  GNSS    do the permanent stations, which have no ramp, show the same gradient
The GNSS check is the decisive one: it is an outside measurement.
"""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import CSK, S1, fit_secular, grid_mean, load_ps, reref

OUT = f'{CSK}/results/compare'
GDIR = f'{CSK}/aux/gnss'
S1_WIN = ('2023-09-09', '2026-04-26')


def gnss_secular(path, t0, t1):
    """Vertical secular rate (mm/yr) with annual + semi-annual removed."""
    d = np.genfromtxt(path, skip_header=1, usecols=(2, 12, 20, 21), dtype=float)
    yr, up, lat, lon = d[:, 0], d[:, 1] * 1000.0, d[:, 2], d[:, 3]
    y0 = 2000 + int(t0[2:4]) if False else float(t0[:4]) + (int(t0[5:7]) - 1) / 12 + int(t0[8:]) / 365.25
    y1 = float(t1[:4]) + (int(t1[5:7]) - 1) / 12 + int(t1[8:]) / 365.25
    m = (yr >= y0) & (yr <= y1) & np.isfinite(up)
    if m.sum() < 200:
        return None
    t = yr[m] - yr[m].mean()
    A = np.column_stack([t, np.ones_like(t), np.cos(2 * np.pi * t), np.sin(2 * np.pi * t),
                         np.cos(4 * np.pi * t), np.sin(4 * np.pi * t)])
    sol, res, *_ = np.linalg.lstsq(A, up[m], rcond=None)
    resid = up[m] - A @ sol
    # 속도 표준오차: 잔차 분산 / 시간 분산
    se = np.std(resid) / (np.std(t) * np.sqrt(m.sum()))
    la, lo = float(np.nanmedian(lat[m])), float(np.nanmedian(lon[m]))
    return dict(rate=float(sol[0]), se=float(se), ann=float(np.hypot(sol[2], sol[3])),
                n=int(m.sum()), lat=la, lon=lo % 360 - 360 + 360 if lo < 0 else lo)


def main():
    D = load_ps(f'{S1}/results/seoul_s1_ps.npz')
    reref(D, rad=300.0)
    sec, amp, lin = fit_secular(D)
    v = sec * D['kv']
    rep = {}

    # ---- 1. 평면 --------------------------------------------------------------
    k, gv = grid_mean(D['lon'], D['lat'], v, cell=0.01, nmin=20)
    glon = (k // 100000) * 0.01
    glat = (k % 100000) * 0.01
    x = (glon - glon.mean()) * 111.320 * np.cos(np.radians(37.55))   # km
    y = (glat - glat.mean()) * 110.540
    A = np.column_stack([x, y, np.ones_like(x)])
    sol, *_ = np.linalg.lstsq(A, gv, rcond=None)
    fit = A @ sol
    r2 = 1 - np.var(gv - fit) / np.var(gv)
    grad = np.hypot(sol[0], sol[1]) * 10
    az = (np.degrees(np.arctan2(sol[0], sol[1]))) % 360
    print(f'== 평면 적합 (1 km 격자 {len(k)} 셀) ==')
    print(f'  경사 {grad:.3f} mm/yr / 10 km, 상승 방위 {az:.0f}°, R² = {r2:.3f}')
    print(f'  전체 std {np.std(gv):.3f} → 평면 제거 후 {np.std(gv - fit):.3f} mm/yr')
    rep['plane'] = dict(grad_mm_yr_per_10km=float(grad), azimuth_deg=float(az),
                        r2=float(r2), std_before=float(np.std(gv)),
                        std_after=float(np.std(gv - fit)), n_cells=len(k))

    # ---- 2. 표고 --------------------------------------------------------------
    _, gh = grid_mean(D['lon'], D['lat'], D['hgt'], cell=0.01, nmin=20)
    rh = float(np.corrcoef(gh, gv)[0, 1])
    sh = float(np.polyfit(gh, gv, 1)[0])
    print(f'\n== 표고 ==\n  r = {rh:+.3f}, 기울기 {sh*100:+.3f} mm/yr per 100 m')
    rep['height'] = dict(r=rh, slope_per_100m=sh * 100)

    # ---- 3. GNSS --------------------------------------------------------------
    print(f'\n== GNSS 검증 ({S1_WIN[0]} ~ {S1_WIN[1]}, 연주기 제거) ==')
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([D['lon'] * 111.320 * np.cos(np.radians(37.55)),
                                    D['lat'] * 110.540]))
    rows = []
    for f in sorted(glob.glob(f'{GDIR}/*.tenv3')):
        site = os.path.basename(f).split('.')[0]
        g = gnss_secular(f, *S1_WIN)
        if g is None:
            print(f'  {site}: 관측일 부족'); continue
        lo = g['lon'] if g['lon'] < 180 else g['lon'] - 360
        lo = lo + 360 if lo < 0 else lo
        idx = tree.query_ball_point([lo * 111.320 * np.cos(np.radians(37.55)),
                                     g['lat'] * 110.540], 0.5)
        if len(idx) < 20:
            print(f'  {site} ({g["lat"]:.4f},{lo:.4f}): 500 m 내 PS {len(idx)}개 — 제외')
            continue
        ins = float(np.median(v[idx]))
        rows.append(dict(site=site, lat=g['lat'], lon=lo, gnss=g['rate'], se=g['se'],
                         ann=g['ann'], ndays=g['n'], insar=ins, nps=len(idx)))
        print(f'  {site}  ({g["lat"]:.4f}, {lo:.4f})  GNSS {g["rate"]:+6.2f} ±{g["se"]:.2f}  '
              f'InSAR {ins:+6.2f} mm/yr   PS {len(idx):4d}  관측 {g["n"]:4d}일  연진폭 {g["ann"]:.1f} mm')

    if len(rows) >= 4:
        gg = np.array([r['gnss'] for r in rows]); ii = np.array([r['insar'] for r in rows])
        gg0, ii0 = gg - gg.mean(), ii - ii.mean()      # 기준면 차이는 상수라 제거
        r = float(np.corrcoef(gg0, ii0)[0, 1])
        sl = float(np.polyfit(gg0, ii0, 1)[0])
        rms = float(np.sqrt(np.mean((ii0 - gg0) ** 2)))
        print(f'\n  평균 제거 후: n={len(rows)}  r={r:+.3f}  기울기={sl:+.2f}  RMS={rms:.2f} mm/yr')
        print(f'  GNSS 공간 범위 {gg.min():+.2f} ~ {gg.max():+.2f}, '
              f'InSAR {ii.min():+.2f} ~ {ii.max():+.2f} mm/yr')
        print(f'  GNSS 속도 표준오차 중앙값 {np.median([r_["se"] for r_ in rows]):.2f} mm/yr')
        rep['gnss'] = dict(n=len(rows), r=r, slope=sl, rms=rms, rows=rows,
                           gnss_range=[float(gg.min()), float(gg.max())],
                           insar_range=[float(ii.min()), float(ii.max())],
                           median_se=float(np.median([r_['se'] for r_ in rows])))
    else:
        rep['gnss'] = dict(n=len(rows), rows=rows)

    with open(f'{OUT}/ramp_validation.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/ramp_validation.json')


if __name__ == '__main__':
    main()
