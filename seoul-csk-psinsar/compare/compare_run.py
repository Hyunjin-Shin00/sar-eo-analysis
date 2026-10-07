#!/usr/bin/env python3
"""Run the four-way comparison and write results/compare/summary.json.

Everything is put on the same footing first: same reference pixel (성북), same
observation window (the CSK/S1 overlap), and LOS -> vertical.  Then three
questions are asked, in increasing order of what the data can actually support:

  1. same sensor, PS vs SBAS  -> does the two methods' disagreement come from
     the method or from the scatterer population?
  2. same method, CSK vs S1   -> is the X-band result reproducible in C-band?
  3. everything vs S1 secular -> how much of each short-window number is the
     annual cycle rather than ground motion?
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import (CSK, KX, OVERLAP, REF_LL, S1, fit_secular, full_rate,
                         grid_mean, load_ps, load_sbas, match, reref,
                         window_delta, window_rate)

OUT = f'{CSK}/results/compare'
os.makedirs(OUT, exist_ok=True)
GRID = 0.01                      # ~1 km
SEOUL = (126.76, 127.19, 37.42, 37.71)


def stats(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10:
        return dict(n=int(m.sum()))
    d = b[m] - a[m]
    return dict(n=int(m.sum()), r=float(np.corrcoef(a[m], b[m])[0, 1]),
                bias=float(np.median(d)), rms=float(np.sqrt(np.mean(d ** 2))),
                mad=float(np.median(np.abs(d - np.median(d)))),
                sa=float(np.std(a[m])), sb=float(np.std(b[m])))


def gridded(D, val):
    k, v = grid_mean(D['lon'], D['lat'], val, cell=GRID, nmin=D.get('nmin', 20))
    return dict(zip(k.tolist(), v.tolist()))


def gjoin(*maps):
    keys = sorted(set(maps[0]).intersection(*[set(m) for m in maps[1:]]))
    return keys, [np.array([m[k] for k in keys]) for m in maps]


def main():
    P = {}
    print('== load ==')
    P['CSK_PS'] = load_ps(f'{CSK}/results/seoul_csk_ps.npz')
    P['S1_PS'] = load_ps(f'{S1}/results/seoul_s1_ps.npz')
    P['CSK_SBAS'] = load_sbas(f'{CSK}/seoul/sbas/mintpy/geo',
                              'geo_timeseries_tropHgt_ramp_demErr.h5',
                              'geo_temporalCoherence.h5', tc_min=0.5)
    P['S1_SBAS'] = load_sbas(f'{S1}/sbas/mintpy/geo',
                             'geo_timeseries_tropHgt_ramp_demErr.h5',
                             'geo_temporalCoherence.h5', tc_min=0.5)
    # SBAS는 격자라 1 km 셀당 점 수가 PS보다 훨씬 적다 — 최소 개수를 낮춘다.
    P['CSK_SBAS']['nmin'] = 3
    P['S1_SBAS']['nmin'] = 3
    for k in ('CSK_SBAS', 'S1_SBAS'):
        P[k]['kv'] = None       # geo_geometryRadar 에서 따로 채운다

    import h5py
    for k, g in (('CSK_SBAS', f'{CSK}/seoul/sbas/mintpy/geo'),
                 ('S1_SBAS', f'{S1}/sbas/mintpy/geo')):
        with h5py.File(f'{g}/geo_geometryRadar.h5', 'r') as f:
            inc = f['incidenceAngle'][:]        # MintPy: 도
        with h5py.File(f'{g}/geo_temporalCoherence.h5', 'r') as f:
            tc = f[list(f.keys())[0]][:]
        with h5py.File(f'{g}/geo_timeseries_tropHgt_ramp_demErr.h5', 'r') as f:
            sel = np.isfinite(f['timeseries'][0]) & (tc >= 0.5)
        P[k]['kv'] = 1.0 / np.cos(np.radians(inc[sel]))

    rep = {'reference': {'lon': REF_LL[0], 'lat': REF_LL[1], 'name': '성북'},
           'window': OVERLAP, 'grid_deg': GRID, 'products': {}}
    for k, D in P.items():
        ok, n = reref(D, rad=300.0)
        rep['products'][k] = dict(n=int(D['lon'].size), nepoch=int(D['day'].size),
                                  t0=str(D['day'][0]), t1=str(D['day'][-1]),
                                  reref_ok=bool(ok), reref_npts=n)
        print(f'  {k:9s} n={D["lon"].size:>9,} epochs={D["day"].size:3d} '
              f'{D["day"][0]}..{D["day"][-1]}  reref={ok} ({n} pts)')

    # ---- 1. 공통 창 — 창 안의 모든 에폭에 직선적합 ---------------------------
    # 양 끝 두 에폭의 차분은 두 날짜의 대기지연을 통째로 싣는다. 서울의 5개월
    # 실제 변위(<1 mm)보다 그 잡음이 몇 배 크므로 창 내 전 에폭을 적합한다.
    print('\n== common window %s .. %s (linear fit over all epochs inside) ==' % OVERLAP)
    cum, wrate, d2ep = {}, {}, {}
    for k, D in P.items():
        r, c, ne, a, b = window_rate(D, *OVERLAP)
        wrate[k] = r * D['kv']
        cum[k] = c * D['kv']
        d2, _, _ = window_delta(D, *OVERLAP)
        d2ep[k] = d2 * D['kv']
        rep['products'][k]['win_used'] = [a, b, ne]
        rep['products'][k]['cum_vert_mm'] = dict(
            median=float(np.nanmedian(cum[k])), std=float(np.nanstd(cum[k])),
            p5=float(np.nanpercentile(cum[k], 5)), p95=float(np.nanpercentile(cum[k], 95)),
            std_two_epoch=float(np.nanstd(d2ep[k])))
        print(f'  {k:9s} [{a} .. {b}] {ne:2d} epochs  median {np.nanmedian(cum[k]):+7.2f} '
              f'std {np.nanstd(cum[k]):6.2f} mm   (2-epoch diff std {np.nanstd(d2ep[k]):6.2f})')

    # 각 산출물의 자기 전체기간 속도 — 관측을 전부 쓰는, 신호대잡음이 가장 좋은 양
    print('\n== each product over its own full record (mm/yr) ==')
    frate = {}
    for k, D in P.items():
        r, span = full_rate(D)
        frate[k] = r * D['kv']
        rep['products'][k]['full_rate_mmyr'] = dict(
            span_yr=span, median=float(np.nanmedian(frate[k])), std=float(np.nanstd(frate[k])))
        print(f'  {k:9s} span {span:.2f} yr  median {np.nanmedian(frate[k]):+6.2f} '
              f'std {np.nanstd(frate[k]):5.2f} mm/yr')

    # ---- 2. S1 장기 secular (진실값 역할) ------------------------------------
    print('\n== S1 secular (2.6 yr, linear + annual + semiannual) ==')
    sec, amp, lin = fit_secular(P['S1_PS'])
    P['S1_PS']['secular'] = sec * P['S1_PS']['kv']
    P['S1_PS']['annamp'] = amp * P['S1_PS']['kv']
    rep['s1_ps_secular_mmyr'] = dict(median=float(np.median(sec * P['S1_PS']['kv'])),
                                     std=float(np.std(sec * P['S1_PS']['kv'])),
                                     ann_amp_median=float(np.median(amp * P['S1_PS']['kv'])),
                                     naive_linear_median=float(np.median(lin * P['S1_PS']['kv'])))
    print('  secular {median:+.3f} ± {std:.3f} mm/yr, annual amp {ann_amp_median:.2f} mm, '
          'naive linear {naive_linear_median:+.3f}'.format(**rep['s1_ps_secular_mmyr']))
    sec2, amp2, lin2 = fit_secular(P['S1_SBAS'])
    P['S1_SBAS']['secular'] = sec2 * P['S1_SBAS']['kv']
    rep['s1_sbas_secular_mmyr'] = dict(median=float(np.median(sec2 * P['S1_SBAS']['kv'])),
                                       std=float(np.std(sec2 * P['S1_SBAS']['kv'])),
                                       ann_amp_median=float(np.median(amp2 * P['S1_SBAS']['kv'])))
    print('  SBAS secular {median:+.3f} ± {std:.3f} mm/yr, annual amp {ann_amp_median:.2f} mm'
          .format(**rep['s1_sbas_secular_mmyr']))

    # ---- 3. 1 km 격자 교차비교 ------------------------------------------------
    pairs = [('CSK_PS', 'CSK_SBAS'), ('S1_PS', 'S1_SBAS'),
             ('CSK_PS', 'S1_PS'), ('CSK_SBAS', 'S1_SBAS'),
             ('CSK_PS', 'S1_SBAS'), ('CSK_SBAS', 'S1_PS')]
    rep['grid_pairs'] = {}
    quantities = [('win_cum_mm', cum, '공통창 누적 (창내 전에폭 적합)'),
                  ('two_epoch_mm', d2ep, '공통창 양끝 2에폭 차분'),
                  ('full_rate_mmyr', frate, '각자 전체기간 속도')]
    GQ = {}
    for qname, qval, qdesc in quantities:
        print(f'\n== 1 km grid — {qdesc} ==')
        G = {k: gridded(P[k], qval[k]) for k in P}
        GQ[qname] = G
        rep['grid_pairs'][qname] = {}
        for a, b in pairs:
            keys, (va, vb) = gjoin(G[a], G[b])
            st = stats(va, vb)
            rep['grid_pairs'][qname][f'{a}|{b}'] = st
            if st.get('n', 0) >= 10:
                print(f'  {a:9s} vs {b:9s}  n={st["n"]:5d}  r={st["r"]:+.3f}  '
                      f'bias={st["bias"]:+6.2f}  rms={st["rms"]:6.2f}  '
                      f'std {st["sa"]:.2f}/{st["sb"]:.2f}')
            else:
                print(f'  {a:9s} vs {b:9s}  n={st.get("n",0)} — too few common cells')
    G = GQ['full_rate_mmyr']

    # ---- 4. 점 단위 근접 대응 (60 m) -----------------------------------------
    print('\n== point-level match within 60 m (full-record rate, mm/yr) ==')
    rep['point_pairs'] = {}
    for a, b in pairs:
        vb = match(P[a], P[b]['lon'], P[b]['lat'], frate[b], rad=60.0, nmin=3)
        st = stats(frate[a], vb)
        rep['point_pairs'][f'{a}|{b}'] = st
        if st.get('n', 0) >= 10:
            print(f'  {a:9s} vs {b:9s}  n={st["n"]:8,}  r={st["r"]:+.3f}  '
                  f'bias={st["bias"]:+6.2f}  rms={st["rms"]:6.2f}')
        else:
            print(f'  {a:9s} vs {b:9s}  n={st.get("n",0)} — too few pairs')

    # ---- 5. 계절 편향: 짧은 창의 누적을 연율로 읽으면 얼마나 틀리나 ----------
    print('\n== seasonal bias of the short window ==')
    gsec = gridded(P['S1_PS'], P['S1_PS']['secular'])
    rep['seasonal_bias'] = {}
    for qname, qval, qdesc in [('CSK_PS_full_rate', frate['CSK_PS'], 'CSK PS 전체기간(0.72yr) 속도'),
                               ('CSK_PS_win_rate', wrate['CSK_PS'], 'CSK PS 공통창(0.39yr) 속도'),
                               ('S1_PS_naive_linear', None, 'S1 PS 계절항 없는 단순직선')]:
        if qval is None:
            lin = fit_secular(P['S1_PS'])[2] * P['S1_PS']['kv']
            gq = gridded(P['S1_PS'], lin)
        else:
            gq = gridded(P['CSK_PS'], qval)
        keys, (gs, gn) = gjoin(gsec, gq)
        st = stats(gs, gn)
        rep['seasonal_bias'][qname] = st
        print(f'  {qdesc:34s} median {np.median(gn):+6.2f} vs S1 secular {np.median(gs):+6.2f} '
              f'mm/yr  → 편차 {np.median(gn - gs):+6.2f}, r={st.get("r", float("nan")):+.3f}')

    with open(f'{OUT}/summary.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    np.savez_compressed(f'{OUT}/grids.npz',
                        **{f'{q}_k_{k}': np.array(list(GQ[q][k].keys()))
                           for q in GQ for k in GQ[q]},
                        **{f'{q}_v_{k}': np.array(list(GQ[q][k].values()))
                           for q in GQ for k in GQ[q]})
    print(f'\n-> {OUT}/summary.json')


if __name__ == '__main__':
    main()
