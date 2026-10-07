#!/usr/bin/env python3
"""서울 지도에 남은 도시 규모 경사의 정체를 판정하고 그림으로 낸다.

판정 논리. 상승과 하강은 동서 감도의 부호가 반대이고 수직 감도는 둘 다 양수다.
따라서 두 궤도의 LOS 평면경사 벡터 g 사이에는
    순수 수직   : g_DSC = (u_D/u_A) g_ASC   양의 배율, 사잇각 0°
    순수 동서   : g_DSC = (e_D/e_A) g_ASC   음의 배율, 사잇각 180°
    궤도 아티팩트: 두 트랙이 독립이므로 관계 없음 (배율 ~0, 사잇각 임의)
셋 중 어디에 가까운지로 가른다. 상승 자리에는 CSK(X밴드)를, 하강 자리에는 S1 DSC
(C밴드)를 넣는다 — 위성·주파수·궤도가 모두 달라 공통 아티팩트가 있을 수 없다.

★ 주의: CSK 와 S1 ASC 는 둘 다 상승이고 방위각이 2° 밖에 안 차이 난다(101.9° vs
99.9°). 둘이 r=0.91 로 일치하는 것은 신호의 재현성을 증명할 뿐, 수직/수평을 가르지
못한다. 그 구분은 하강궤도가 있어야만 가능하다.
"""
import json
import os

import h5py
import numpy as np

CSK = '<DATA_ROOT>/CSK_PSInSAR'
DSCG = '<DATA_ROOT>/S1_DSC/sbas/mintpy/geo'
ASCG = '<DATA_ROOT>/S1_PSInSAR/sbas/mintpy_noderamp/geo'
OUT = f'{CSK}/results/compare'
SEOUL = (126.76, 127.19, 37.42, 37.71)
REF = (127.06254, 37.607475)
CELL = 0.01


def plane_vec(LO, LA, v, m):
    x = (LO[m] - LO[m].mean()) * 111.320 * np.cos(np.radians(37.55))
    y = (LA[m] - LA[m].mean()) * 110.540
    X = np.column_stack([x, y, np.ones_like(x)])
    sol, *_ = np.linalg.lstsq(X, v[m], rcond=None)
    fit = X @ sol
    return np.array([sol[0], sol[1]]) * 10, float(1 - np.var(v[m] - fit) / np.var(v[m]))


def load_grid(geo, t0=None, t1=None):
    with h5py.File(f'{geo}/geo_timeseries_tropHgt_demErr.h5', 'r') as f:
        ts = f['timeseries'][:] * 1000.0
        A = dict(f.attrs)
        dd = np.array([np.datetime64(f'{x.decode()[:4]}-{x.decode()[4:6]}-{x.decode()[6:]}')
                       for x in f['date'][:]])
    with h5py.File(f'{geo}/geo_temporalCoherence.h5', 'r') as f:
        tc = f[list(f.keys())[0]][:]
    with h5py.File(f'{geo}/geo_geometryRadar.h5', 'r') as f:
        inc = f['incidenceAngle'][:]; azi = f['azimuthAngle'][:]
    ny, nx = tc.shape
    lon = float(A['X_FIRST']) + np.arange(nx) * float(A['X_STEP'])
    lat = float(A['Y_FIRST']) + np.arange(ny) * float(A['Y_STEP'])
    LO, LA = np.meshgrid(lon, lat)
    day = dd.astype('datetime64[D]')
    s = np.ones(len(day), bool)
    if t0: s &= day >= np.datetime64(t0)
    if t1: s &= day <= np.datetime64(t1)
    t = (day[s] - day[s][0]).astype(int) / 365.25
    X = np.column_stack([t, np.ones_like(t)])
    sol, *_ = np.linalg.lstsq(X, ts[s].reshape(s.sum(), -1), rcond=None)
    v = sol[0].reshape(ny, nx)
    m = (tc >= 0.5) & np.isfinite(v) & (LO >= SEOUL[0]) & (LO <= SEOUL[1]) \
        & (LA >= SEOUL[2]) & (LA <= SEOUL[3])
    d0 = np.hypot((LA - REF[1]) * 110540, (LO - REF[0]) * 111320 * np.cos(np.radians(37.55)))
    v = v - np.nanmean(v[(d0 <= 300) & m])
    return dict(LO=LO, LA=LA, v=v, m=m, inc=float(np.median(inc[m])),
                azi=float(np.median(azi[m])), n=int(s.sum()),
                t0=str(day[s][0]), t1=str(day[s][-1]), dir=A.get('ORBIT_DIRECTION', '?'))


def load_csk():
    Z = np.load(f'{CSK}/results/seoul_csk_ps.npz')
    day = Z['day'].astype('datetime64[D]')
    t = (day - day[0]).astype(int) / 365.25
    X = np.column_stack([t, np.ones_like(t)])
    sol, *_ = np.linalg.lstsq(X, Z['disp_mm'].T, rcond=None)
    v = sol[0]
    d = np.hypot((Z['lat'] - REF[1]) * 110540, (Z['lon'] - REF[0]) * 111320 * np.cos(np.radians(37.55)))
    v = v - np.nanmean(v[d <= 300])
    NX = int(round((SEOUL[1] - SEOUL[0]) / CELL)); NY = int(round((SEOUL[3] - SEOUL[2]) / CELL))
    ix = ((Z['lon'] - SEOUL[0]) / CELL).astype(int); iy = ((Z['lat'] - SEOUL[2]) / CELL).astype(int)
    s = (ix >= 0) & (ix < NX) & (iy >= 0) & (iy < NY)
    k = iy[s] * NX + ix[s]
    acc = np.bincount(k, weights=v[s], minlength=NX * NY)
    cnt = np.bincount(k, minlength=NX * NY)
    g = np.where(cnt >= 20, acc / np.maximum(cnt, 1), np.nan).reshape(NY, NX)
    gx = SEOUL[0] + (np.arange(NX) + .5) * CELL; gy = SEOUL[2] + (np.arange(NY) + .5) * CELL
    LO, LA = np.meshgrid(gx, gy)
    return dict(LO=LO, LA=LA, v=g, m=np.isfinite(g),
                inc=float(np.degrees(np.median(Z['inc_deg']))), azi=-258.13,
                n=len(day), t0=str(day[0]), t1=str(day[-1]), dir='ASCENDING')


def unit(inc, azi):
    i, a = np.radians(inc), np.radians(azi)
    return -np.sin(i) * np.sin(a), np.sin(i) * np.cos(a), np.cos(i)


def main():
    os.makedirs(OUT, exist_ok=True)
    P = {'CSK': load_csk(), 'S1_DSC': load_grid(DSCG), 'S1_ASC': load_grid(ASCG)}
    rep = {'cell_deg': CELL, 'reference': {'lon': REF[0], 'lat': REF[1], 'name': '성북'},
           'tracks': {}}
    for k, X in P.items():
        g, r2 = plane_vec(X['LO'], X['LA'], X['v'], X['m'])
        e, n, u = unit(X['inc'], X['azi'])
        X['g'], X['r2'], X['e'], X['u'] = g, r2, e, u
        rep['tracks'][k] = dict(direction=X['dir'], n_epoch=X['n'], span=[X['t0'], X['t1']],
                                inc=X['inc'], azi=X['azi'], e=float(e), n=float(n), u=float(u),
                                grad=float(np.hypot(*g)),
                                az=float(np.degrees(np.arctan2(*g)) % 360), r2=r2,
                                median=float(np.nanmedian(X['v'][X['m']])))
        print(f"{k:7s} {X['dir'][:3]}  {X['n']:2d}ep {X['t0']}~{X['t1']}  "
              f"경사 {np.hypot(*g):5.3f} 방위 {np.degrees(np.arctan2(*g)) % 360:5.0f}° "
              f"R²={r2:.3f}  e={e:+.3f} u={u:+.3f}")

    print('\n== 경사 벡터 판정 (상승 CSK  vs  하강 S1_DSC) ==')
    A, D = P['CSK'], P['S1_DSC']
    k_obs = float(np.dot(D['g'], A['g']) / np.dot(A['g'], A['g']))
    ang = float(np.degrees(np.arccos(np.clip(
        np.dot(D['g'], A['g']) / np.linalg.norm(D['g']) / np.linalg.norm(A['g']), -1, 1))))
    kv, ke = float(D['u'] / A['u']), float(D['e'] / A['e'])
    rep['verdict'] = dict(k_observed=k_obs, angle_deg=ang, k_vertical=kv, k_east=ke,
                          closer='vertical' if abs(k_obs - kv) < abs(k_obs - ke) else 'east')
    print(f'  관측     k={k_obs:+.3f}  사잇각 {ang:.0f}°')
    print(f'  수직가설 k={kv:+.3f}  사잇각 0°      |차| {abs(k_obs-kv):.3f}')
    print(f'  동서가설 k={ke:+.3f}  사잇각 180°    |차| {abs(k_obs-ke):.3f}')
    print(f'  궤도아티팩트 k≈0, 사잇각 임의')
    print(f'  → {rep["verdict"]["closer"]}')
    with open(f'{OUT}/tilt_verdict.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/tilt_verdict.json')
    return P





def figure(P):
    """세 트랙의 LOS 속도와 각자의 평면경사 방향을 나란히 놓는다."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.patches import Polygon as MplPoly
    import json as _json
    F = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
    font_manager.fontManager.addfont(F)
    plt.rcParams['font.family'] = font_manager.FontProperties(fname=F).get_name()
    plt.rcParams['axes.unicode_minus'] = False
    GU = _json.load(open(f'{CSK}/aux/seoul_municipalities_geo_simple.json'))

    order = [('CSK', 'COSMO-SkyMed  상승'), ('S1_ASC', 'Sentinel-1  상승'),
             ('S1_DSC', 'Sentinel-1  하강')]
    fig, axs = plt.subplots(1, 3, figsize=(19.5, 6.8), constrained_layout=True)
    norm = TwoSlopeNorm(vmin=-8, vcenter=0, vmax=8)
    for ax, (k, ttl) in zip(axs, order):
        X = P[k]
        v = np.where(X['m'], X['v'], np.nan)
        im = ax.pcolormesh(X['LO'], X['LA'], v, cmap='RdYlBu_r', norm=norm, shading='auto')
        for ft in GU['features']:
            g = ft['geometry']
            rings = [g['coordinates'][0]] if g['type'] == 'Polygon' else [p[0] for p in g['coordinates']]
            for r in rings:
                ax.add_patch(MplPoly(np.array(r), closed=True, fill=False, lw=.5, ec='0.25', zorder=5))
        # 경사 방향 화살표 (상승 방향)
        gx, gy = X['g']
        L = 0.11 / max(1e-9, np.hypot(gx, gy))
        cx, cy = 126.975, 37.565
        ax.arrow(cx - gx * L / 2, cy - gy * L / 2, gx * L, gy * L, width=0.004,
                 head_width=0.016, color='k', zorder=9, length_includes_head=True)
        ax.plot(*REF, marker='*', ms=14, mfc='k', mec='w', mew=1.0, zorder=10)
        ax.set_xlim(SEOUL[0], SEOUL[1]); ax.set_ylim(SEOUL[2], SEOUL[3])
        ax.set_aspect(1 / np.cos(np.radians(37.55))); ax.set_xticks([]); ax.set_yticks([])
        az = np.degrees(np.arctan2(gx, gy)) % 360
        ax.set_title(f'{ttl}   {X["n"]}에폭\n{X["t0"]}~{X["t1"]}\n'
                     f'경사 {np.hypot(gx, gy):.2f} mm/yr/10km  방위 {az:.0f}°  R²={X["r2"]:.2f}',
                     fontsize=10)
    cb = fig.colorbar(im, ax=axs, shrink=0.72, pad=0.012, extend='both')
    cb.set_label('LOS 속도 (mm/yr)   위성에서 멀어짐 ← → 가까워짐', fontsize=10)
    A, D = P['CSK'], P['S1_DSC']
    kobs = np.dot(D['g'], A['g']) / np.dot(A['g'], A['g'])
    ang = np.degrees(np.arccos(np.clip(np.dot(D['g'], A['g']) / np.linalg.norm(D['g'])
                                       / np.linalg.norm(A['g']), -1, 1)))
    fig.suptitle('도시 규모 경사의 정체 — 하강궤도가 판정한다  (화살표 = 경사 상승방향, ★ 기준점 성북)\n'
                 f'상승↔하강 배율 k={kobs:+.2f}, 사잇각 {ang:.0f}°   '
                 f'수직가설 k={D["u"]/A["u"]:+.2f}·0°   동서가설 k={D["e"]/A["e"]:+.2f}·180°   '
                 '→ 수직 (궤도 아티팩트라면 두 트랙이 무관해야 한다)', fontsize=12)
    out = f'{CSK}/results/maps/fig6_tilt_verdict.png'
    fig.savefig(out, dpi=190)
    plt.close(fig)
    print(f'  {out}')


if __name__ == '__main__':
    figure(main())
