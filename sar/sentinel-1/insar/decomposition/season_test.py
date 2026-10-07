#!/usr/bin/env python3
"""Does S1 reproduce the CSK number when given the same months?

CSK only ever saw 2025-12 .. 2026-08, so its rate could be either a real
winter-to-summer swing or a 6x gain error.  S1 covers 2.6 years, which contains
the same Dec->Aug window a year and two years earlier.  Running S1 through the
identical window is the one test that separates the two explanations.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import CSK, S1, full_rate, grid_mean, load_ps, load_sbas, reref

OUT = f'{CSK}/results/compare'


def rate_between(D, t0, t1):
    day = D['day'].astype('datetime64[D]')
    m = (day >= np.datetime64(t0)) & (day <= np.datetime64(t1))
    if m.sum() < 5:
        return None, 0, None, None
    t = (day[m] - day[m][0]).astype(int) / 365.25
    A = np.column_stack([t, np.ones_like(t)])
    sol, *_ = np.linalg.lstsq(A, D['disp'][:, m].T, rcond=None)
    return sol[0] * D['kv'], int(m.sum()), str(day[m][0]), str(day[m][-1])


def gmap(D, v, nmin=20):
    k, val = grid_mean(D['lon'], D['lat'], v, cell=0.01, nmin=nmin)
    return dict(zip(k.tolist(), val.tolist()))


def join(*ms):
    ks = sorted(set(ms[0]).intersection(*[set(m) for m in ms[1:]]))
    return ks, [np.array([m[k] for k in ks]) for m in ms]


def main():
    import h5py
    P = {'CSK_PS': load_ps(f'{CSK}/results/seoul_csk_ps.npz'),
         'S1_PS': load_ps(f'{S1}/results/seoul_s1_ps.npz'),
         'S1_SBAS': load_sbas(f'{S1}/sbas/mintpy/geo',
                              'geo_timeseries_tropHgt_ramp_demErr.h5',
                              'geo_temporalCoherence.h5', tc_min=0.5)}
    g = f'{S1}/sbas/mintpy/geo'
    with h5py.File(f'{g}/geo_geometryRadar.h5', 'r') as f:
        inc = f['incidenceAngle'][:]
    with h5py.File(f'{g}/geo_temporalCoherence.h5', 'r') as f:
        tc = f[list(f.keys())[0]][:]
    with h5py.File(f'{g}/geo_timeseries_tropHgt_ramp_demErr.h5', 'r') as f:
        sel = np.isfinite(f['timeseries'][0]) & (tc >= 0.5)
    P['S1_SBAS']['kv'] = 1.0 / np.cos(np.radians(inc[sel]))
    for D in P.values():
        reref(D, rad=300.0)

    csk_rate, nc, c0, c1 = rate_between(P['CSK_PS'], '2025-12-01', '2026-09-01')
    Gc = gmap(P['CSK_PS'], csk_rate)
    print(f'CSK  {c0}..{c1}  {nc} epochs  median {np.nanmedian(csk_rate):+6.2f} '
          f'std {np.nanstd(csk_rate):5.2f} mm/yr   (1km std {np.std(list(Gc.values())):.2f})')

    print('\n같은 달(12월→8월)을 S1 의 각 연도에 적용:')
    rep = {'csk': dict(t0=c0, t1=c1, n=nc, median=float(np.nanmedian(csk_rate)),
                       grid_std=float(np.std(list(Gc.values()))))}
    rep['s1_windows'] = {}
    for y in (2023, 2024):
        r, n, a, b = rate_between(P['S1_PS'], f'{y}-12-01', f'{y+1}-09-01')
        if r is None:
            print(f'  {y}-12 .. {y+1}-08  에폭 부족'); continue
        Gs = gmap(P['S1_PS'], r)
        ks, (gc, gs) = join(Gc, Gs)
        rr = np.corrcoef(gc, gs)[0, 1]
        gain = rr * np.std(gc) / np.std(gs)
        print(f'  S1 {a}..{b}  {n:2d} epochs  median {np.nanmedian(r):+6.2f} '
              f'std {np.nanstd(r):5.2f} mm/yr  (1km std {np.std(gs):.2f})')
        print(f'      vs CSK 격자: n={len(ks)}  r={rr:+.3f}  CSK/S1 gain={gain:+.2f}  '
              f'bias={np.median(gc - gs):+.2f} mm/yr')
        rep['s1_windows'][f'{y}-12..{y+1}-08'] = dict(
            t0=a, t1=b, n=n, median=float(np.nanmedian(r)),
            grid_std=float(np.std(gs)), r_vs_csk=float(rr), gain=float(gain),
            bias=float(np.median(gc - gs)))

    # 참고: S1 의 12월→8월 창 두 해끼리는 서로 얼마나 재현되나 (계절의 반복성)
    r23, *_ = rate_between(P['S1_PS'], '2023-12-01', '2024-09-01')
    r24, *_ = rate_between(P['S1_PS'], '2024-12-01', '2025-09-01')
    if r23 is not None and r24 is not None:
        G23, G24 = gmap(P['S1_PS'], r23), gmap(P['S1_PS'], r24)
        ks, (a23, a24) = join(G23, G24)
        rr = np.corrcoef(a23, a24)[0, 1]
        print(f'\nS1 의 두 겨울→여름 창끼리: n={len(ks)}  r={rr:+.3f}  '
              f'median {np.median(a23):+.2f} / {np.median(a24):+.2f} mm/yr')
        rep['s1_season_repeatability'] = dict(n=len(ks), r=float(rr),
                                              med1=float(np.median(a23)),
                                              med2=float(np.median(a24)))

    # 대조군: S1 의 여름→여름(온전한 1년) 창
    print('\n대조군 — 온전한 1년 창(8월→8월):')
    rep['s1_full_year'] = {}
    for y in (2023, 2024):
        r, n, a, b = rate_between(P['S1_PS'], f'{y}-08-01', f'{y+1}-08-01')
        if r is None:
            print(f'  {y}-08 .. {y+1}-08  에폭 부족'); continue
        Gs = gmap(P['S1_PS'], r)
        print(f'  S1 {a}..{b}  {n:2d} epochs  median {np.nanmedian(r):+6.2f} '
              f'std {np.nanstd(r):5.2f} mm/yr  (1km std {np.std(list(Gs.values())):.2f})')
        rep['s1_full_year'][f'{a}..{b}'] = dict(
            n=n, median=float(np.nanmedian(r)), grid_std=float(np.std(list(Gs.values()))))

    # SBAS 도 같은 계절 창에서 CSK PS 를 재현하는가
    print('\n같은 계절 창 — S1 SBAS:')
    rep['s1_sbas_windows'] = {}
    for y in (2023, 2024, 2025):
        r, n, a, b = rate_between(P['S1_SBAS'], f'{y}-12-01', f'{y+1}-09-01')
        if r is None:
            print(f'  {y}-12 .. {y+1}-08  에폭 부족'); continue
        Gs = gmap(P['S1_SBAS'], r, nmin=3)
        ks, (gc, gs) = join(Gc, Gs)
        rr = np.corrcoef(gc, gs)[0, 1] if len(ks) >= 10 else float('nan')
        print(f'  S1 SBAS {a}..{b}  {n:2d} epochs  median {np.nanmedian(r):+6.2f} '
              f'std {np.nanstd(r):5.2f} mm/yr   vs CSK PS: n={len(ks)} r={rr:+.3f}')
        rep['s1_sbas_windows'][f'{y}-12..{y+1}-08'] = dict(
            t0=a, t1=b, n=n, median=float(np.nanmedian(r)),
            n_cells=len(ks), r_vs_csk=float(rr))

    with open(f'{OUT}/season_test.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/season_test.json')


if __name__ == '__main__':
    main()
