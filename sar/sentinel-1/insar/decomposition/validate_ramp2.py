#!/usr/bin/env python3
"""Second pass on the NE-SW tilt, after GNSS coverage turned out to be the limit.

The Seoul stations that sit in the north-east (DBON, SOUL, GANS, SON2, GUMC) all
end in 2023, so none of them overlaps the Sentinel-1 window.  Two substitutes:

  A  their long-term rates (2015-2023).  Not the same epoch, but a tilt that is
     real ground motion should be a persistent feature of the city, so it should
     appear in the earlier decade too.
  B  the tilt seen by CSK.  A different satellite on a different track with a
     different orbit-error realisation; an orbital artefact cannot be common to
     both, real ground motion must be.
"""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import CSK, S1, fit_secular, grid_mean, load_ps, reref
from validate_ramp import GDIR, OUT, gnss_secular


def plane(lon, lat, v):
    x = (lon - lon.mean()) * 111.320 * np.cos(np.radians(37.55))
    y = (lat - lat.mean()) * 110.540
    A = np.column_stack([x, y, np.ones_like(x)])
    sol, *_ = np.linalg.lstsq(A, v, rcond=None)
    fit = A @ sol
    return dict(grad=float(np.hypot(sol[0], sol[1]) * 10),
                az=float(np.degrees(np.arctan2(sol[0], sol[1])) % 360),
                r2=float(1 - np.var(v - fit) / np.var(v)),
                gx=float(sol[0] * 10), gy=float(sol[1] * 10), n=len(v))


def grid(D, v, nmin=20):
    k, gv = grid_mean(D['lon'], D['lat'], v, cell=0.01, nmin=nmin)
    return (k // 100000) * 0.01, (k % 100000) * 0.01, gv


def rate_between(D, t0, t1):
    day = D['day'].astype('datetime64[D]')
    m = (day >= np.datetime64(t0)) & (day <= np.datetime64(t1))
    t = (day[m] - day[m][0]).astype(int) / 365.25
    A = np.column_stack([t, np.ones_like(t)])
    sol, *_ = np.linalg.lstsq(A, D['disp'][:, m].T, rcond=None)
    return sol[0] * D['kv'], int(m.sum())


def main():
    rep = {}
    S = load_ps(f'{S1}/results/seoul_s1_ps.npz'); reref(S, rad=300.0)
    C = load_ps(f'{CSK}/results/seoul_csk_ps.npz'); reref(C, rad=300.0)
    sec = fit_secular(S)[0] * S['kv']

    # ---- A. 장기 GNSS 의 공간 패턴 ------------------------------------------
    print('== A. 장기 GNSS 속도 (각 국 전체 기록) 와 S1 secular 의 공간 패턴 ==')
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([S['lon'] * 111.320 * np.cos(np.radians(37.55)),
                                    S['lat'] * 110.540]))
    rows = []
    for f in sorted(glob.glob(f'{GDIR}/*.tenv3')):
        site = os.path.basename(f).split('.')[0]
        g = gnss_secular(f, '1997-01-01', '2027-01-01')
        if g is None:
            continue
        lo = g['lon'] % 360
        lo = lo - 360 if lo > 180 else lo
        idx = tree.query_ball_point([lo * 111.320 * np.cos(np.radians(37.55)),
                                     g['lat'] * 110.540], 0.5)
        if len(idx) < 20:
            print(f'  {site}: 500 m 내 PS {len(idx)}개 — 제외'); continue
        ins = float(np.median(sec[idx]))
        # 장비 교체·지진에 의한 단차가 있는 국은 직선적합이 터진다. 물리적으로
        # 불가능한 속도(|v| > 10 mm/yr)나 큰 표준오차는 적합 실패의 표시로 본다.
        bad = abs(g['rate']) > 10 or g['se'] > 0.5
        flag = '  ← 단차 의심, 제외' if bad else ''
        print(f'  {site}  ({g["lat"]:.4f}, {lo:.4f})  장기 GNSS {g["rate"]:+8.2f} ±{g["se"]:5.2f} '
              f'({g["n"]:5d}일)   S1 secular {ins:+6.2f} mm/yr{flag}')
        if bad:
            continue
        rows.append(dict(site=site, lat=g['lat'], lon=lo, gnss=g['rate'], se=g['se'],
                         ndays=g['n'], insar=ins, nps=len(idx)))
    rep['gnss_longterm'] = dict(rows=rows)
    if len(rows) >= 5:
        gg = np.array([r['gnss'] for r in rows]); ii = np.array([r['insar'] for r in rows])
        la = np.array([r['lat'] for r in rows]); lo = np.array([r['lon'] for r in rows])
        r = float(np.corrcoef(gg - gg.mean(), ii - ii.mean())[0, 1])
        print(f'\n  유효 {len(rows)}국, 평균 제거 후 r={r:+.3f}  '
              f'RMS={np.sqrt(np.mean(((ii-ii.mean())-(gg-gg.mean()))**2)):.2f} mm/yr')
        print(f'  GNSS 범위 {gg.min():+.2f}~{gg.max():+.2f} (2014~2023), '
              f'S1 범위 {ii.min():+.2f}~{ii.max():+.2f} mm/yr (2023~2026) — 관측 시기가 다르다')
        pg = plane(lo, la, gg); pi = plane(lo, la, ii)
        print(f'  GNSS 평면 경사 {pg["grad"]:.3f} mm/yr/10km 방위 {pg["az"]:.0f}° (R²={pg["r2"]:.2f})')
        print(f'  S1   평면 경사 {pi["grad"]:.3f} mm/yr/10km 방위 {pi["az"]:.0f}° (R²={pi["r2"]:.2f})')
        rep['gnss_longterm'].update(r=r, plane_gnss=pg, plane_insar_at_gnss=pi)

    # ---- B. 두 위성이 같은 경사를 보는가 --------------------------------------
    print('\n== B. 위성별 평면 경사 (1 km 격자) ==')
    rep['planes'] = {}
    cases = [('S1 secular 2.6yr', S, sec, None),
             ('S1 2023-12→2024-08', S, None, ('2023-12-01', '2024-09-01')),
             ('S1 2024-12→2025-08', S, None, ('2024-12-01', '2025-09-01')),
             ('S1 2024-08→2025-07 (1년)', S, None, ('2024-08-01', '2025-08-01')),
             ('CSK 2025-12→2026-08', C, None, ('2025-12-01', '2026-09-01'))]
    for nm, D, val, win in cases:
        v = val if val is not None else rate_between(D, *win)[0]
        gl, ga, gv = grid(D, v)
        p = plane(gl, ga, gv)
        rep['planes'][nm] = dict(**p, std=float(np.std(gv)),
                                 std_dt=float(np.std(gv - (gv - gv))))
        print(f'  {nm:26s} 경사 {p["grad"]:5.3f} mm/yr/10km  방위 {p["az"]:5.0f}°  '
              f'R²={p["r2"]:.3f}  격자std {np.std(gv):.2f}')

    with open(f'{OUT}/ramp_validation2.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/ramp_validation2.json')


if __name__ == '__main__':
    main()
