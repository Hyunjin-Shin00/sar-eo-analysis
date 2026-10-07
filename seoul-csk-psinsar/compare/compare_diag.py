#!/usr/bin/env python3
"""Two diagnostics that turn the correlation table into a conclusion.

(1) Total-least-squares slope.  A low r between two noisy estimates of the same
    field is expected; what distinguishes "same signal, noisier" from "no common
    signal" is the slope, not r.  OLS is biased toward zero by noise in x, so the
    slope is taken from the principal axis of the 2x2 covariance instead.
(2) Is the CSK-minus-S1 rate difference explained by the seasonal cycle?  S1's
    2.6-year record measures the annual amplitude independently.  If the CSK
    window (Dec->Aug, winter to summer) is reading swelling rather than motion,
    the difference must track that amplitude.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import (CSK, OVERLAP, REF_LL, S1, fit_secular, full_rate,
                         grid_mean, load_ps, load_sbas, reref)

OUT = f'{CSK}/results/compare'


def ols(x, y):
    """Slope of y on x, with x the cleaner of the two.

    A principal-axis (total least squares) fit is wrong here: it assumes equal
    noise on both axes, so when one series is several times noisier the axis
    swings onto it and the slope degenerates to sigma_y/sigma_x.  Regressing the
    noisy series on the clean one answers the question actually being asked --
    how much of the clean pattern does the other reproduce, and at what gain.
    """
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    r = float(np.corrcoef(x, y)[0, 1])
    return float(r * np.std(y) / np.std(x)), r, int(m.sum()), float(np.std(x)), float(np.std(y))


def gmap(D, v, nmin):
    k, val = grid_mean(D['lon'], D['lat'], v, cell=0.01, nmin=nmin)
    return dict(zip(k.tolist(), val.tolist()))


def join(*ms):
    ks = sorted(set(ms[0]).intersection(*[set(m) for m in ms[1:]]))
    return ks, [np.array([m[k] for k in ks]) for m in ms]


def main():
    import h5py
    P = {'CSK_PS': load_ps(f'{CSK}/results/seoul_csk_ps.npz'),
         'S1_PS': load_ps(f'{S1}/results/seoul_s1_ps.npz'),
         'CSK_SBAS': load_sbas(f'{CSK}/seoul/sbas/mintpy/geo',
                               'geo_timeseries_tropHgt_ramp_demErr.h5',
                               'geo_temporalCoherence.h5', tc_min=0.5),
         'S1_SBAS': load_sbas(f'{S1}/sbas/mintpy/geo',
                              'geo_timeseries_tropHgt_ramp_demErr.h5',
                              'geo_temporalCoherence.h5', tc_min=0.5)}
    for k, g in (('CSK_SBAS', f'{CSK}/seoul/sbas/mintpy/geo'),
                 ('S1_SBAS', f'{S1}/sbas/mintpy/geo')):
        with h5py.File(f'{g}/geo_geometryRadar.h5', 'r') as f:
            inc = f['incidenceAngle'][:]; hgt = f['height'][:]
        with h5py.File(f'{g}/geo_temporalCoherence.h5', 'r') as f:
            tc = f[list(f.keys())[0]][:]
        with h5py.File(f'{g}/geo_timeseries_tropHgt_ramp_demErr.h5', 'r') as f:
            sel = np.isfinite(f['timeseries'][0]) & (tc >= 0.5)
        P[k]['kv'] = 1.0 / np.cos(np.radians(inc[sel]))
        P[k]['hgt'] = hgt[sel]
    for D in P.values():
        reref(D, rad=300.0)

    rate = {k: full_rate(D)[0] * D['kv'] for k, D in P.items()}
    nmin = {k: (3 if 'SBAS' in k else 20) for k in P}
    G = {k: gmap(P[k], rate[k], nmin[k]) for k in P}

    rep = {}
    print('== OLS gain on the 1 km grid, clean series as predictor (full-record rate) ==')
    print('   (기울기 1 = 같은 패턴 같은 크기, >1 = 같은 패턴을 과대, ~0 = 공통 패턴 없음)')
    rep['gain'] = {}
    for a, b in [('S1_PS', 'S1_SBAS'), ('S1_PS', 'CSK_PS'), ('S1_PS', 'CSK_SBAS'),
                 ('CSK_PS', 'CSK_SBAS'), ('S1_SBAS', 'CSK_SBAS')]:
        ks, (va, vb) = join(G[a], G[b])
        if len(ks) < 10:
            print(f'  {a:8s} -> {b:8s}  n={len(ks)} 부족'); continue
        sl, r, n, sa, sb = ols(va, vb)
        rep['gain'][f'{a}->{b}'] = dict(slope=sl, r=r, n=n, std_x=sa, std_y=sb)
        print(f'  {a:8s} -> {b:8s}  n={n:5d}  gain={sl:+6.2f}  r={r:+.3f}  '
              f'std {sa:.2f} -> {sb:.2f} mm/yr')

    print('\n== is the CSK-minus-S1 rate difference the annual cycle? ==')
    sec, amp, lin = fit_secular(P['S1_PS'])
    kv = P['S1_PS']['kv']
    Gsec = gmap(P['S1_PS'], sec * kv, 20)
    Gamp = gmap(P['S1_PS'], amp * kv, 20)
    Ghgt = gmap(P['S1_PS'], P['S1_PS']['hgt'], 20)
    ks, (gcsk, gsec, gamp, ghgt) = join(G['CSK_PS'], Gsec, Gamp, Ghgt)
    d = gcsk - gsec
    for nm, x in (('S1 연주기 진폭 (mm)', gamp), ('표고 (m)', ghgt), ('S1 secular (mm/yr)', gsec)):
        r = np.corrcoef(x, d)[0, 1]
        sl = np.polyfit(x, d, 1)[0]
        print(f'  차이 vs {nm:22s}  r={r:+.3f}  기울기={sl:+.3f}')
        rep.setdefault('diff_explained_by', {})[nm] = dict(r=float(r), slope=float(sl))
    print(f'  차이 median {np.median(d):+.2f} mm/yr, std {np.std(d):.2f}, n={len(ks)}')
    rep['diff_stats'] = dict(median=float(np.median(d)), std=float(np.std(d)), n=len(ks))

    # 계절 성분을 CSK 창에 대해 예측해 빼면 잔차가 줄어드는가?
    print('\n== predict the seasonal part of the CSK window from S1 and remove it ==')
    day_c = P['CSK_PS']['day'].astype('datetime64[D]')
    t0 = (day_c[0] - np.datetime64('2023-09-09')).astype(int) / 365.25
    t1 = (day_c[-1] - np.datetime64('2023-09-09')).astype(int) / 365.25
    day_s = P['S1_PS']['day'].astype('datetime64[D]')
    ts = (day_s - day_s[0]).astype(int) / 365.25
    A = np.column_stack([ts, np.ones_like(ts), np.cos(2 * np.pi * ts), np.sin(2 * np.pi * ts),
                         np.cos(4 * np.pi * ts), np.sin(4 * np.pi * ts)])
    sol, *_ = np.linalg.lstsq(A, P['S1_PS']['disp'].T, rcond=None)
    off = (day_s[0] - np.datetime64('2023-09-09')).astype(int) / 365.25

    def seas(t):
        tt = t - off
        return (sol[2] * np.cos(2 * np.pi * tt) + sol[3] * np.sin(2 * np.pi * tt)
                + sol[4] * np.cos(4 * np.pi * tt) + sol[5] * np.sin(4 * np.pi * tt))

    seas_rate = (seas(t1) - seas(t0)) / (t1 - t0) * kv       # mm/yr 로 환산된 계절 기여
    Gseas = gmap(P['S1_PS'], seas_rate, 20)
    ks2, (gcsk2, gsec2, gseas2) = join(G['CSK_PS'], Gsec, Gseas)
    before = gcsk2 - gsec2
    after = gcsk2 - gseas2 - gsec2
    print(f'  계절 예측 기여 median {np.median(gseas2):+.2f} mm/yr')
    print(f'  보정 전 차이  median {np.median(before):+6.2f}  std {np.std(before):5.2f}  '
          f'RMS {np.sqrt(np.mean(before**2)):5.2f} mm/yr')
    print(f'  보정 후 차이  median {np.median(after):+6.2f}  std {np.std(after):5.2f}  '
          f'RMS {np.sqrt(np.mean(after**2)):5.2f} mm/yr')
    rep['deseason'] = dict(
        seas_median=float(np.median(gseas2)),
        before=dict(median=float(np.median(before)), std=float(np.std(before)),
                    rms=float(np.sqrt(np.mean(before ** 2)))),
        after=dict(median=float(np.median(after)), std=float(np.std(after)),
                   rms=float(np.sqrt(np.mean(after ** 2)))),
        n=len(ks2))

    with open(f'{OUT}/diagnostics.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/diagnostics.json')


if __name__ == '__main__':
    main()
