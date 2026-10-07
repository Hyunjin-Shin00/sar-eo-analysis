#!/usr/bin/env python3
"""CSK(상승·X밴드) + S1 DSC(하강·C밴드) 로 봄→여름 창을 수직/동서 분해한다.

왜 이 조합인가. 남은 질문은 서울 지도의 도시 규모 남북 경사가 실제 지반운동인지
잔류 궤도오차인지다. S1 ASC + S1 DSC 로도 분해는 되지만 두 트랙이 함께 덮는 구간이
가을→봄뿐이고, 그 창은 ASC 자신의 해간 재현성부터 무너진다(방위 150/168/285°).
반대로 봄→여름은 ASC 가 2024·2025 두 해에 걸쳐 방위 175~182° 로 재현했고 CSK 2026
도 182° 로 겹쳤다 — 신호가 가장 튼튼한 창이다. CSK 가 마침 그 창을 덮으므로,
CSK 를 상승 자리에 넣고 DSC 를 하강 자리에 넣으면 좋은 계절에 분해할 수 있다.

두 위성은 궤도·주파수·잡음이 완전히 독립이라, 잔류 궤도오차가 같은 값으로 나올
수 없다는 판정 논리는 그대로 성립한다.
"""
import argparse
import json
import os

import h5py
import numpy as np

CSK = '<DATA_ROOT>/CSK_PSInSAR'
DSC = '<DATA_ROOT>/S1_DSC/sbas/mintpy'
OUT = f'{CSK}/results/compare'
SEOUL = (126.76, 127.19, 37.42, 37.71)
REF_LL = (127.06254, 37.607475)     # 성북


def unit_los(inc_deg, azi_deg):
    """지표->위성 단위벡터 (동, 북, 상). azimuthAngle 은 북에서 반시계 양(MintPy 규약)."""
    inc, az = np.radians(inc_deg), np.radians(azi_deg)
    return -np.sin(inc) * np.sin(az), np.sin(inc) * np.cos(az), np.cos(inc)


def csk_geometry():
    """CSK PS 점의 방위각. PS npz 에는 입사각만 있어 los.rdr 에서 방위각을 읽는다."""
    from osgeo import gdal
    gdal.UseExceptions()
    g = f'{CSK}/seoul/sbas/geom_reference'
    lat = np.fromfile(f'{g}/lat.rdr', dtype=np.float64)
    lon = np.fromfile(f'{g}/lon.rdr', dtype=np.float64)
    los = np.fromfile(f'{g}/los.rdr', dtype=np.float32)
    n = lat.size
    los = los.reshape(-1, 2) if los.size == 2 * n else los.reshape(2, -1).T
    return lat, lon, los[:, 0], los[:, 1]


def grid_rate(lon, lat, val, cell, box=SEOUL, nmin=3):
    nx = int(round((box[1] - box[0]) / cell)); ny = int(round((box[3] - box[2]) / cell))
    ix = ((lon - box[0]) / cell).astype(int); iy = ((lat - box[2]) / cell).astype(int)
    m = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny) & np.isfinite(val)
    k = iy[m] * nx + ix[m]
    s = np.bincount(k, weights=val[m], minlength=nx * ny)
    c = np.bincount(k, minlength=nx * ny).astype(float)
    out = np.where(c >= nmin, s / np.maximum(c, 1), np.nan).reshape(ny, nx)
    gx = box[0] + (np.arange(nx) + .5) * cell
    gy = box[2] + (np.arange(ny) + .5) * cell
    return out, gx, gy


def plane(LO, LA, v, m):
    x = (LO[m] - LO[m].mean()) * 111.320 * np.cos(np.radians(37.55))
    y = (LA[m] - LA[m].mean()) * 110.540
    A = np.column_stack([x, y, np.ones_like(x)])
    sol, *_ = np.linalg.lstsq(A, v[m], rcond=None)
    fit = A @ sol
    return dict(grad=float(np.hypot(sol[0], sol[1]) * 10),
                az=float(np.degrees(np.arctan2(sol[0], sol[1])) % 360),
                r2=float(1 - np.var(v[m] - fit) / np.var(v[m])),
                n=int(m.sum()), std=float(np.std(v[m])))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--t0', default='2026-04-04')
    p.add_argument('--t1', default='2026-08-06')
    p.add_argument('--cell', type=float, default=0.005)   # 약 500 m
    a = p.parse_args()

    # ---- CSK PS -> LOS 속도 --------------------------------------------------
    Z = np.load(f'{CSK}/results/seoul_csk_ps.npz')
    day = Z['day'].astype('datetime64[D]')
    m = (day >= np.datetime64(a.t0)) & (day <= np.datetime64(a.t1))
    t = (day[m] - day[m][0]).astype(int) / 365.25
    A_ = np.column_stack([t, np.ones_like(t)])
    sol, *_ = np.linalg.lstsq(A_, Z['disp_mm'][:, m].T, rcond=None)
    vlos_c = sol[0]                                  # mm/yr, LOS (양수=위성쪽)
    print(f'CSK {int(m.sum())}에폭 [{day[m][0]} .. {day[m][-1]}]  {vlos_c.size:,}점')

    glat, glon, ginc, gazi = csk_geometry()
    from scipy.spatial import cKDTree
    kx = lambda lo, la: np.column_stack([np.asarray(lo) * 111.320 * np.cos(np.radians(37.55)),
                                         np.asarray(la) * 110.540])
    ok = np.isfinite(glat) & np.isfinite(glon) & (glat > 0)
    tree = cKDTree(kx(glon[ok], glat[ok]))
    _, j = tree.query(kx(Z['lon'], Z['lat']), k=1)
    azi_c = gazi[ok][j]
    inc_c = np.degrees(np.asarray(Z['inc_deg'], float))   # npz 는 라디안
    print(f'  CSK inc 중앙 {np.median(inc_c):.2f}°  azi 중앙 {np.median(azi_c):.2f}°')

    # ---- DSC -> LOS 속도 -----------------------------------------------------
    with h5py.File(f'{DSC}/geo/geo_timeseries_tropHgt_demErr.h5', 'r') as f:
        ts = f['timeseries'][:] * 1000.0
        At = dict(f.attrs)
        dd = np.array([np.datetime64(f'{x.decode()[:4]}-{x.decode()[4:6]}-{x.decode()[6:]}')
                       for x in f['date'][:]])
    with h5py.File(f'{DSC}/geo/geo_temporalCoherence.h5', 'r') as f:
        tc = f[list(f.keys())[0]][:]
    with h5py.File(f'{DSC}/geo/geo_geometryRadar.h5', 'r') as f:
        inc_d2 = f['incidenceAngle'][:]; azi_d2 = f['azimuthAngle'][:]
    md = (dd >= np.datetime64(a.t0)) & (dd <= np.datetime64(a.t1))
    td = (dd[md] - dd[md][0]).astype(int) / 365.25
    Ad = np.column_stack([td, np.ones_like(td)])
    ny, nx = tc.shape
    sol, *_ = np.linalg.lstsq(Ad, ts[md].reshape(md.sum(), -1), rcond=None)
    vlos_d2 = sol[0].reshape(ny, nx)
    good_d = np.isfinite(vlos_d2) & (tc >= 0.5)
    lon_d = float(At['X_FIRST']) + np.arange(nx) * float(At['X_STEP'])
    lat_d = float(At['Y_FIRST']) + np.arange(ny) * float(At['Y_STEP'])
    LOd, LAd = np.meshgrid(lon_d, lat_d)
    print(f'DSC {int(md.sum())}에폭 [{dd[md][0]} .. {dd[md][-1]}]  유효 {good_d.sum():,}화소')
    print(f'  DSC inc 중앙 {np.median(inc_d2[good_d]):.2f}°  azi 중앙 {np.median(azi_d2[good_d]):.2f}°')

    # ---- 공통 격자 -----------------------------------------------------------
    gc, gx, gy = grid_rate(Z['lon'], Z['lat'], vlos_c, a.cell, nmin=20)
    ic, _, _ = grid_rate(Z['lon'], Z['lat'], inc_c, a.cell, nmin=20)
    ac, _, _ = grid_rate(Z['lon'], Z['lat'], azi_c, a.cell, nmin=20)
    s = good_d
    gd, _, _ = grid_rate(LOd[s], LAd[s], vlos_d2[s], a.cell, nmin=3)
    idd, _, _ = grid_rate(LOd[s], LAd[s], inc_d2[s], a.cell, nmin=3)
    add, _, _ = grid_rate(LOd[s], LAd[s], azi_d2[s], a.cell, nmin=3)
    LO, LA = np.meshgrid(gx, gy)
    mm = np.isfinite(gc) & np.isfinite(gd)
    print(f'\n격자 {a.cell*111.3*1000:.0f} m, 공통 셀 {mm.sum():,}')

    # 기준점 재정렬
    d0 = np.hypot((LA - REF_LL[1]) * 110540, (LO - REF_LL[0]) * 111320 * np.cos(np.radians(37.55)))
    rm = (d0 <= max(700, a.cell * 111320)) & mm
    gc = gc - np.nanmean(gc[rm]); gd = gd - np.nanmean(gd[rm])
    print(f'  성북 {max(700, a.cell*111320):.0f} m 내 {rm.sum()}셀로 재정렬')

    rep = {'window': [a.t0, a.t1], 'cell_deg': a.cell, 'n_cells': int(mm.sum())}
    pc = plane(LO, LA, gc, mm); pd_ = plane(LO, LA, gd, mm)
    r = float(np.corrcoef(gc[mm], gd[mm])[0, 1])
    print('\n== LOS 평면 경사 ==')
    print(f'  CSK(상승)  {pc["grad"]:.3f} mm/yr/10km  방위 {pc["az"]:5.0f}°  R²={pc["r2"]:.3f}  std {pc["std"]:.2f}')
    print(f'  DSC(하강)  {pd_["grad"]:.3f} mm/yr/10km  방위 {pd_["az"]:5.0f}°  R²={pd_["r2"]:.3f}  std {pd_["std"]:.2f}')
    print(f'  두 LOS 상관 r={r:+.3f}')
    rep['plane_los'] = {'CSK': pc, 'DSC': pd_, 'r': r}

    ec, nc, uc = unit_los(ic, ac)
    ed, nd, ud = unit_los(idd, add)
    print('\n== 단위벡터 검산 (동/북/상) ==')
    print(f'  CSK  e {np.nanmedian(ec[mm]):+.3f}  n {np.nanmedian(nc[mm]):+.3f}  u {np.nanmedian(uc[mm]):+.3f}')
    print(f'  DSC  e {np.nanmedian(ed[mm]):+.3f}  n {np.nanmedian(nd[mm]):+.3f}  u {np.nanmedian(ud[mm]):+.3f}')
    if np.nanmedian(ec[mm]) * np.nanmedian(ed[mm]) > 0:
        raise SystemExit('동서 부호가 같다 — 방위각 규약 오류')
    det = ec * ud - ed * uc
    okm = mm & (np.abs(det) > 1e-2)
    du = np.full(gc.shape, np.nan); de = np.full(gc.shape, np.nan)
    de[okm] = (gc[okm] * ud[okm] - gd[okm] * uc[okm]) / det[okm]
    du[okm] = (ec[okm] * gd[okm] - ed[okm] * gc[okm]) / det[okm]
    print(f'\n== 분해 (|det| 중앙 {np.nanmedian(np.abs(det[okm])):.3f}) ==')
    print(f'  수직 중앙 {np.nanmedian(du[okm]):+6.2f} mm/yr  std {np.nanstd(du[okm]):5.2f}')
    print(f'  동서 중앙 {np.nanmedian(de[okm]):+6.2f} mm/yr  std {np.nanstd(de[okm]):5.2f}')
    pu = plane(LO, LA, du, okm); pe = plane(LO, LA, de, okm)
    print(f'  수직 경사 {pu["grad"]:.3f} mm/yr/10km 방위 {pu["az"]:5.0f}° R²={pu["r2"]:.3f}')
    print(f'  동서 경사 {pe["grad"]:.3f} mm/yr/10km 방위 {pe["az"]:5.0f}° R²={pe["r2"]:.3f}')
    rep['decomp'] = {'n': int(okm.sum()),
                     'up': dict(median=float(np.nanmedian(du[okm])), std=float(np.nanstd(du[okm])), plane=pu),
                     'east': dict(median=float(np.nanmedian(de[okm])), std=float(np.nanstd(de[okm])), plane=pe)}

    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(f'{OUT}/csk_dsc_decomp.npz', lon=LO, lat=LA, vlos_csk=gc, vlos_dsc=gd,
                        vup=du, veast=de, mask=okm)
    with open(f'{OUT}/csk_dsc_decomp.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/csk_dsc_decomp.npz, .json')


if __name__ == '__main__':
    main()
