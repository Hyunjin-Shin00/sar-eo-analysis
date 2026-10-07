#!/usr/bin/env python3
"""Per-자치구 summary of the four products.

The citywide tilt is the least trustworthy part of the map (see
ramp_validation2.json), so each borough is reported both as-is and after the
citywide median is removed -- the second column is what survives if the tilt
turns out to be an artefact.
"""
import json
import os
import sys

import numpy as np
from matplotlib.path import Path as MplPath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import CSK, OVERLAP, S1, fit_secular, load_ps, load_sbas, reref, window_rate

GU = json.load(open(f'{CSK}/aux/seoul_municipalities_geo_simple.json'))
OUT = f'{CSK}/results/compare'


def gu_paths():
    out = []
    for f in GU['features']:
        g = f['geometry']
        polys = [g['coordinates'][0]] if g['type'] == 'Polygon' else [p[0] for p in g['coordinates']]
        out.append((f['properties']['name'], [MplPath(np.array(p)) for p in polys]))
    return out


def assign(lon, lat, paths):
    pts = np.column_stack([lon, lat])
    idx = np.full(lon.size, -1, np.int16)
    for i, (_, ps) in enumerate(paths):
        m = np.zeros(lon.size, bool)
        for p in ps:
            m |= p.contains_points(pts)
        idx[m & (idx < 0)] = i
    return idx


def main():
    paths = gu_paths()
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

    val = {'S1_PS_sec': fit_secular(P['S1_PS'])[0] * P['S1_PS']['kv'],
           'S1_SBAS_sec': fit_secular(P['S1_SBAS'])[0] * P['S1_SBAS']['kv'],
           'CSK_cum': window_rate(P['CSK_PS'], *OVERLAP)[1] * P['CSK_PS']['kv'],
           'S1_cum': window_rate(P['S1_PS'], *OVERLAP)[1] * P['S1_PS']['kv']}
    src = {'S1_PS_sec': 'S1_PS', 'S1_SBAS_sec': 'S1_SBAS',
           'CSK_cum': 'CSK_PS', 'S1_cum': 'S1_PS'}
    gidx = {k: assign(P[k]['lon'], P[k]['lat'], paths) for k in P}
    med = {k: float(np.nanmedian(v)) for k, v in val.items()}

    rows = []
    for i, (name, _) in enumerate(paths):
        r = {'gu': name}
        for q, v in val.items():
            m = gidx[src[q]] == i
            r[q] = float(np.nanmedian(v[m])) if m.sum() >= 50 else None
            r[f'{q}_n'] = int(m.sum())
        rows.append(r)
    rows.sort(key=lambda r: (r['S1_PS_sec'] if r['S1_PS_sec'] is not None else 1e9))

    hdr = (f'{"자치구":<8}{"S1 PS 장기":>11}{"중앙값차":>10}{"S1 SBAS":>10}'
           f'{"CSK 누적":>10}{"S1 누적":>10}{"PS 점수":>10}')
    print(hdr); print('-' * len(hdr.encode('utf-8')) // 2 * '-' if False else '-' * 70)
    print(f'  (장기 = 2023-09~2026-04 secular mm/yr,  누적 = {OVERLAP[0]}~{OVERLAP[1]} mm)')
    print(f'  서울 전역 중앙값: S1 장기 {med["S1_PS_sec"]:+.2f} mm/yr, '
          f'CSK 누적 {med["CSK_cum"]:+.2f} mm, S1 누적 {med["S1_cum"]:+.2f} mm\n')
    for r in rows:
        f2 = lambda x: f'{x:+10.2f}' if x is not None else f'{"-":>10}'
        d = (r['S1_PS_sec'] - med['S1_PS_sec']) if r['S1_PS_sec'] is not None else None
        print(f'{r["gu"]:<8}{f2(r["S1_PS_sec"])}{f2(d)}{f2(r["S1_SBAS_sec"])}'
              f'{f2(r["CSK_cum"])}{f2(r["S1_cum"])}{r["S1_PS_sec_n"]:>10,}')

    with open(f'{OUT}/gu_stats.json', 'w') as f:
        json.dump({'citywide_median': med, 'window': OVERLAP, 'rows': rows}, f,
                  indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/gu_stats.json')


if __name__ == '__main__':
    main()
