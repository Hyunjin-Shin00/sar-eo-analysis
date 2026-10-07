#!/usr/bin/env python3
"""Seoul subsidence maps for the four products.

Two figures:
  fig1  2x2 panel — cumulative vertical displacement over the common window,
        each product on its own points/grid, same colour scale.
  fig2  the deliverable — S1 secular vertical rate (the only estimate long
        enough to be quoted as mm/yr), with the 25 자치구 outlines and the
        CSK/S1 agreement contour behind it.
A third figure holds the 1 km scatter matrix so the numbers in summary.json can
be read off visually.
"""
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Polygon as MplPoly

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import (CSK, OVERLAP, REF_LL, S1, fit_secular, grid_mean,
                         load_ps, load_sbas, reref, window_rate)

FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
font_manager.fontManager.addfont(FONT)
plt.rcParams['font.family'] = font_manager.FontProperties(fname=FONT).get_name()
plt.rcParams['axes.unicode_minus'] = False

OUT = f'{CSK}/results/maps'
GU = json.load(open(f'{CSK}/aux/seoul_municipalities_geo_simple.json'))
EXT = (126.76, 127.19, 37.42, 37.71)


def rings(feat):
    g = feat['geometry']
    polys = g['coordinates'] if g['type'] == 'Polygon' else [p[0] for p in g['coordinates']]
    if g['type'] == 'Polygon':
        polys = [g['coordinates'][0]]
    return polys


def draw_gu(ax, lw=0.5, color='0.25', label=False):
    for f in GU['features']:
        for r in rings(f):
            ax.add_patch(MplPoly(np.array(r), closed=True, fill=False, lw=lw, ec=color, zorder=5))
        if label:
            r = np.array(rings(f)[0])
            ax.text(r[:, 0].mean(), r[:, 1].mean(), f['properties']['name'],
                    fontsize=5.5, ha='center', va='center', color='0.15', zorder=6,
                    path_effects=None)


def frame(ax, title):
    ax.set_xlim(EXT[0], EXT[1]); ax.set_ylim(EXT[2], EXT[3])
    ax.set_aspect(1 / np.cos(np.radians(37.55)))
    ax.set_title(title, fontsize=10)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.6)


def scale_bar(ax, km=5):
    dlon = km * 1000 / (111320 * np.cos(np.radians(37.55)))
    x0, y0 = EXT[0] + 0.02, EXT[2] + 0.015
    ax.plot([x0, x0 + dlon], [y0, y0], 'k-', lw=2.5, zorder=8)
    ax.text(x0 + dlon / 2, y0 + 0.005, f'{km} km', ha='center', fontsize=7, zorder=8)


def main():
    os.makedirs(OUT, exist_ok=True)
    print('loading...')
    P = {'CSK_PS': load_ps(f'{CSK}/results/seoul_csk_ps.npz'),
         'S1_PS': load_ps(f'{S1}/results/seoul_s1_ps.npz'),
         'CSK_SBAS': load_sbas(f'{CSK}/seoul/sbas/mintpy/geo',
                               'geo_timeseries_tropHgt_ramp_demErr.h5',
                               'geo_temporalCoherence.h5', tc_min=0.5),
         'S1_SBAS': load_sbas(f'{S1}/sbas/mintpy/geo',
                              'geo_timeseries_tropHgt_ramp_demErr.h5',
                              'geo_temporalCoherence.h5', tc_min=0.5)}
    import h5py
    for k, g in (('CSK_SBAS', f'{CSK}/seoul/sbas/mintpy/geo'),
                 ('S1_SBAS', f'{S1}/sbas/mintpy/geo')):
        with h5py.File(f'{g}/geo_geometryRadar.h5', 'r') as f:
            inc = f['incidenceAngle'][:]
        with h5py.File(f'{g}/geo_temporalCoherence.h5', 'r') as f:
            tc = f[list(f.keys())[0]][:]
        with h5py.File(f'{g}/geo_timeseries_tropHgt_ramp_demErr.h5', 'r') as f:
            sel = np.isfinite(f['timeseries'][0]) & (tc >= 0.5)
        P[k]['kv'] = 1.0 / np.cos(np.radians(inc[sel]))
    for D in P.values():
        reref(D, rad=300.0)

    # 양 끝 두 에폭 차분은 그 두 날짜의 대기지연을 통째로 싣는다 — 창 안의 모든
    # 에폭에 직선을 적합해 누적을 낸다.
    cum = {k: window_rate(D, *OVERLAP)[1] * D['kv'] for k, D in P.items()}

    # ---- fig1: 2x2 cumulative ------------------------------------------------
    vmax = 15.0
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    fig, axs = plt.subplots(2, 2, figsize=(13.5, 10.2), constrained_layout=True)
    order = ['CSK_PS', 'CSK_SBAS', 'S1_PS', 'S1_SBAS']
    nice = {'CSK_PS': 'COSMO-SkyMed  PS-InSAR', 'CSK_SBAS': 'COSMO-SkyMed  SBAS',
            'S1_PS': 'Sentinel-1  PS-InSAR', 'S1_SBAS': 'Sentinel-1  SBAS'}
    for ax, k in zip(axs.ravel(), order):
        D, v = P[k], cum[k]
        o = np.argsort(np.abs(v))           # 큰 값이 위로
        sc = ax.scatter(D['lon'][o], D['lat'][o], c=v[o], s=0.09 if 'PS' in k and 'SBAS' not in k else 1.2,
                        cmap='RdYlBu_r', norm=norm, linewidths=0, rasterized=True)
        draw_gu(ax)
        ax.plot(*REF_LL, marker='*', ms=13, mfc='k', mec='w', mew=0.8, zorder=9)
        frame(ax, f'{nice[k]}   n={D["lon"].size:,}')
        scale_bar(ax)
    cb = fig.colorbar(sc, ax=axs, shrink=0.55, pad=0.012, extend='both')
    cb.set_label('누적 수직변위 (mm)   침하 ← → 융기', fontsize=10)
    fig.suptitle(f'서울시 지반변위 — 4종 해 비교   {OVERLAP[0]} ~ {OVERLAP[1]}   '
                 f'(기준점 ★ 성북 {REF_LL[1]:.4f}N {REF_LL[0]:.4f}E)', fontsize=13)
    fig.savefig(f'{OUT}/fig1_four_products.png', dpi=200)
    plt.close(fig)
    print(f'  {OUT}/fig1_four_products.png')

    # ---- fig2: deliverable — S1 secular --------------------------------------
    # 왼쪽은 성북 기준점 그대로. 서울 전역이 기준점 대비 약 +1 mm/yr 라, 그 상수
    # 하나가 색을 다 먹어버린다. 오른쪽은 도시 전체 중앙값을 뺀 것 — 절대 기준면은
    # GNSS 로 확정되지 않았으므로, 어디가 주변보다 가라앉는지는 이쪽이 정직하다.
    sec, amp, lin = fit_secular(P['S1_PS'])
    secv = sec * P['S1_PS']['kv']
    med = float(np.median(secv))
    fig, axs = plt.subplots(1, 2, figsize=(19, 7.6), constrained_layout=True)
    for ax, v, ttl, lim in (
            (axs[0], secv, f'성북 기준점 대비   중앙값 {med:+.2f} mm/yr', 3.0),
            (axs[1], secv - med, '서울 전역 중앙값 제거 — 주변 대비 상대 침하', 2.0)):
        n2 = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
        o = np.argsort(np.abs(v))
        sc = ax.scatter(P['S1_PS']['lon'][o], P['S1_PS']['lat'][o], c=v[o], s=0.13,
                        cmap='RdYlBu_r', norm=n2, linewidths=0, rasterized=True)
        draw_gu(ax, lw=0.7, label=True)
        ax.plot(*REF_LL, marker='*', ms=14, mfc='k', mec='w', mew=1.0, zorder=9)
        frame(ax, ttl)
        scale_bar(ax)
        cb = fig.colorbar(sc, ax=ax, shrink=0.82, pad=0.012, extend='both')
        cb.set_label('수직 변위속도 (mm/yr)   침하 ← → 융기', fontsize=10)
    fig.suptitle('서울시 지반침하 지도 — Sentinel-1 PS-InSAR 장기 추세   '
                 f'{P["S1_PS"]["day"][0]} ~ {P["S1_PS"]["day"][-1]} (2.6년, 73 에폭)\n'
                 '연주기·반년주기 제거 후 secular 성분, PS 1,535,010 점', fontsize=13)
    fig.savefig(f'{OUT}/fig2_seoul_subsidence_rate.png', dpi=210)
    plt.close(fig)
    print(f'  {OUT}/fig2_seoul_subsidence_rate.png')

    # ---- fig3: 1 km scatter matrix -------------------------------------------
    G = {}
    for k in order:
        nmin = 3 if 'SBAS' in k else 20
        kk, vv = grid_mean(P[k]['lon'], P[k]['lat'], cum[k], cell=0.01, nmin=nmin)
        G[k] = dict(zip(kk.tolist(), vv.tolist()))
    pairs = [('CSK_PS', 'S1_PS'), ('CSK_SBAS', 'S1_SBAS'),
             ('CSK_PS', 'CSK_SBAS'), ('S1_PS', 'S1_SBAS')]
    fig, axs = plt.subplots(1, 4, figsize=(17, 4.4), constrained_layout=True)
    for ax, (a, b) in zip(axs, pairs):
        ks = sorted(set(G[a]) & set(G[b]))
        if len(ks) < 5:
            ax.text(.5, .5, f'공통 셀 {len(ks)}개\n비교 불가', ha='center', va='center',
                    transform=ax.transAxes, fontsize=11)
            ax.set_title(f'{nice[a]}\nvs {nice[b]}', fontsize=9)
            continue
        va = np.array([G[a][k] for k in ks]); vb = np.array([G[b][k] for k in ks])
        r = np.corrcoef(va, vb)[0, 1]
        ax.scatter(va, vb, s=7, alpha=.45, lw=0)
        lim = np.nanpercentile(np.abs(np.r_[va, vb]), 99) * 1.1
        ax.plot([-lim, lim], [-lim, lim], 'k--', lw=.8)
        ax.axhline(0, c='.7', lw=.5); ax.axvline(0, c='.7', lw=.5)
        ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect('equal')
        ax.set_xlabel(f'{nice[a]} (mm)', fontsize=8)
        ax.set_ylabel(f'{nice[b]} (mm)', fontsize=8)
        ax.set_title(f'n={len(ks)}  r={r:+.3f}', fontsize=9)
    fig.suptitle('1 km 격자 평균 누적 수직변위 교차비교', fontsize=12)
    fig.savefig(f'{OUT}/fig3_grid_scatter.png', dpi=190)
    plt.close(fig)
    print(f'  {OUT}/fig3_grid_scatter.png')




def fig_season():
    """The test that settles it: give S1 the same months CSK saw.

    CSK only ever observed 2025-12 .. 2026-08.  Compared against S1's 2.6-year
    secular rate it looks six times too large; compared against S1 run over the
    same Dec->Aug months, in either earlier year, it is the same map.
    """
    import matplotlib.pyplot as plt
    P = {'CSK_PS': load_ps(f'{CSK}/results/seoul_csk_ps.npz'),
         'S1_PS': load_ps(f'{S1}/results/seoul_s1_ps.npz')}
    for D in P.values():
        reref(D, rad=300.0)

    def rate(D, t0, t1):
        day = D['day'].astype('datetime64[D]')
        m = (day >= np.datetime64(t0)) & (day <= np.datetime64(t1))
        t = (day[m] - day[m][0]).astype(int) / 365.25
        A = np.column_stack([t, np.ones_like(t)])
        sol, *_ = np.linalg.lstsq(A, D['disp'][:, m].T, rcond=None)
        return sol[0] * D['kv'], str(day[m][0]), str(day[m][-1])

    panels = [('CSK_PS', '2025-12-01', '2026-09-01', 'COSMO-SkyMed  2025-12 → 2026-08'),
              ('S1_PS', '2024-12-01', '2025-09-01', 'Sentinel-1  2024-12 → 2025-08'),
              ('S1_PS', '2023-12-01', '2024-09-01', 'Sentinel-1  2023-12 → 2024-08'),
              ('S1_PS', '2024-08-01', '2025-08-01', 'Sentinel-1  2024-08 → 2025-07  (온전한 1년)')]
    from matplotlib.colors import TwoSlopeNorm
    norm = TwoSlopeNorm(vmin=-16, vcenter=0, vmax=16)
    fig, axs = plt.subplots(2, 2, figsize=(13.5, 10.2), constrained_layout=True)
    for ax, (k, t0, t1, ttl) in zip(axs.ravel(), panels):
        v, a, b = rate(P[k], t0, t1)
        o = np.argsort(np.abs(v))
        sc = ax.scatter(P[k]['lon'][o], P[k]['lat'][o], c=v[o], s=0.09,
                        cmap='RdYlBu_r', norm=norm, linewidths=0, rasterized=True)
        draw_gu(ax)
        ax.plot(*REF_LL, marker='*', ms=13, mfc='k', mec='w', mew=0.8, zorder=9)
        frame(ax, f'{ttl}\nmedian {np.nanmedian(v):+.2f} mm/yr')
        scale_bar(ax)
    cb = fig.colorbar(sc, ax=axs, shrink=0.55, pad=0.012, extend='both')
    cb.set_label('선형 변위속도 (mm/yr)   침하 ← → 융기', fontsize=10)
    fig.suptitle('같은 달을 주면 두 위성은 같은 지도를 만든다 — CSK 의 큰 값은 계절 창의 결과\n'
                 '겨울→여름 창 세 장은 서로 r = 0.79~0.91, 온전한 1년 창(우하)만 크기가 1/3 로 줄어든다',
                 fontsize=12)
    fig.savefig(f'{OUT}/fig4_season_window_test.png', dpi=200)
    plt.close(fig)
    print(f'  {OUT}/fig4_season_window_test.png')




def fig_apraug():
    """The cleanest cross-sensor validation available.

    Split the winter-to-summer window in two and the two halves behave very
    differently.  Dec->Apr is unstable: Sentinel-1's own tilt azimuth swings
    between 150, 168 and 285 degrees over three winters, so neither sensor can
    be held to it.  Apr->Aug repeats -- and CSK 2026, which no Sentinel-1 epoch
    overlaps, lands on top of Sentinel-1's 2024 and 2025.  That is two
    satellites, two tracks, three years, one map.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    from compare_all import grid_mean
    P = {'CSK': load_ps(f'{CSK}/results/seoul_csk_ps.npz'),
         'S1': load_ps(f'{S1}/results/seoul_s1_ps.npz')}
    for D in P.values():
        reref(D, rad=300.0)

    def rate(D, t0, t1):
        day = D['day'].astype('datetime64[D]')
        m = (day >= np.datetime64(t0)) & (day <= np.datetime64(t1))
        t = (day[m] - day[m][0]).astype(int) / 365.25
        A = np.column_stack([t, np.ones_like(t)])
        sol, *_ = np.linalg.lstsq(A, D['disp'][:, m].T, rcond=None)
        return sol[0] * D['kv'], int(m.sum()), str(day[m][0]), str(day[m][-1])

    def g1(D, v):
        k, gv = grid_mean(D['lon'], D['lat'], v, cell=0.01, nmin=20)
        return dict(zip(k.tolist(), gv.tolist()))

    cases = [('CSK', '2026-04-01', '2026-09-01', 'COSMO-SkyMed  2026-04 → 08'),
             ('S1', '2025-04-01', '2025-09-01', 'Sentinel-1  2025-04 → 08'),
             ('S1', '2024-04-01', '2024-09-01', 'Sentinel-1  2024-04 → 08')]
    norm = TwoSlopeNorm(vmin=-12, vcenter=0, vmax=12)
    fig, axs = plt.subplots(1, 3, figsize=(19.5, 6.6), constrained_layout=True)
    G = []
    for ax, (k, t0, t1, ttl) in zip(axs, cases):
        v, n, a, b = rate(P[k], t0, t1)
        G.append(g1(P[k], v))
        o = np.argsort(np.abs(v))
        sc = ax.scatter(P[k]['lon'][o], P[k]['lat'][o], c=v[o], s=0.09,
                        cmap='RdYlBu_r', norm=norm, linewidths=0, rasterized=True)
        draw_gu(ax)
        ax.plot(*REF_LL, marker='*', ms=13, mfc='k', mec='w', mew=0.8, zorder=9)
        frame(ax, f'{ttl}   {n} 에폭\nmedian {np.nanmedian(v):+.2f} mm/yr')
        scale_bar(ax)
    cb = fig.colorbar(sc, ax=axs, shrink=0.72, pad=0.012, extend='both')
    cb.set_label('선형 변위속도 (mm/yr)   침하 ← → 융기', fontsize=10)
    rs = []
    for i, j in ((0, 1), (0, 2), (1, 2)):
        ks = sorted(set(G[i]) & set(G[j]))
        va = np.array([G[i][k] for k in ks]); vb = np.array([G[j][k] for k in ks])
        rs.append(np.corrcoef(va, vb)[0, 1])
    fig.suptitle('봄→여름 창에서의 교차검증 — 두 위성, 세 해, 같은 지도\n'
                 f'1 km 격자 상관: CSK↔S1(2025) r={rs[0]:+.3f},  '
                 f'CSK↔S1(2024) r={rs[1]:+.3f},  S1 두 해끼리 r={rs[2]:+.3f}', fontsize=13)
    fig.savefig(f'{OUT}/fig5_apr_aug_validation.png', dpi=200)
    plt.close(fig)
    print(f'  {OUT}/fig5_apr_aug_validation.png   r = '
          + ', '.join(f'{x:+.3f}' for x in rs))
    return rs


if __name__ == '__main__':
    main()
    fig_season()
    fig_apraug()
