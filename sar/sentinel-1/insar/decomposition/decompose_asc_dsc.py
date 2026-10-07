#!/usr/bin/env python3
"""상승/하강 궤도 LOS 를 수직 + 동서 성분으로 분해하고, 남북 경사의 정체를 판정한다.

InSAR 는 시선(LOS) 한 방향만 재므로 단일 궤도로는 수직과 수평을 못 가른다. 상승과
하강은 동서 감도의 부호가 반대라 두 개를 세우면 풀린다(남북 감도는 양쪽 다 거의
0 이라 분해에서 제외한다 — 극궤도의 한계).

    d_los = u_e * de + u_u * du          (궤도별로 u 가 다르다)

이 처리의 본래 목적은 서울 지도에 남은 도시 규모 남북 경사가 실제 지반운동인지
잔류 궤도오차인지 판정하는 것이다. 잔류 궤도오차는 궤도마다 독립이라 두 트랙에
같은 값이 나올 수 없고, 실제 수직운동이면 두 LOS 에 같은 부호로 들어온다.
"""
import argparse
import json
import os

import h5py
import numpy as np

CSK = '<DATA_ROOT>/CSK_PSInSAR'
ASC = '<DATA_ROOT>/S1_PSInSAR/sbas/mintpy_noderamp'
DSC = '<DATA_ROOT>/S1_DSC/sbas/mintpy'
OUT = f'{CSK}/results/compare'
SEOUL = (126.76, 127.19, 37.42, 37.71)
REF_LL = (127.06254, 37.607475)          # 성북 — 네 산출물 공통


def load(geo, tc_min=0.5):
    """지오코딩된 시계열 + 기하. 반환 격자는 그 트랙 고유의 lat/lon 격자."""
    with h5py.File(f'{geo}/geo_timeseries_tropHgt_demErr.h5', 'r') as f:
        ts = f['timeseries'][:] * 1000.0            # mm
        A = dict(f.attrs)
        dates = np.array([np.datetime64(f'{d.decode()[:4]}-{d.decode()[4:6]}-{d.decode()[6:]}')
                          for d in f['date'][:]])
    with h5py.File(f'{geo}/geo_temporalCoherence.h5', 'r') as f:
        tc = f[list(f.keys())[0]][:]
    with h5py.File(f'{geo}/geo_geometryRadar.h5', 'r') as f:
        inc = f['incidenceAngle'][:]                # 도
        azi = f['azimuthAngle'][:]                  # 도
    ny, nx = tc.shape
    lon = float(A['X_FIRST']) + np.arange(nx) * float(A['X_STEP'])
    lat = float(A['Y_FIRST']) + np.arange(ny) * float(A['Y_STEP'])
    good = np.isfinite(ts[0]) & (tc >= tc_min) & np.isfinite(inc)
    return dict(ts=ts, dates=dates, tc=tc, inc=inc, azi=azi, lon=lon, lat=lat,
                good=good, attrs=A, direction=A.get('ORBIT_DIRECTION', '?'))


def unit_los(inc_deg, azi_deg):
    """지표 -> 위성 단위벡터의 (동, 북, 상) 성분.

    MintPy/ISCE 의 azimuthAngle 은 LOS 를 지표에 투영한 방향을 북에서 반시계로 잰
    각이다. 같은 규약을 mintpy.utils.utils0.get_unit_vector4component_of_interest
    가 쓰며, 여기서는 그 식을 그대로 옮긴다.

    sin 과 cos 을 바꿔 쓰면 동서와 남북이 뒤바뀐다. 극궤도는 남북 감도가 거의 0,
    동서 감도는 상승/하강이 반대 부호여야 하므로, 아래 두 수치로 항상 검산한다.
    """
    inc = np.radians(inc_deg)
    az = np.radians(azi_deg)
    ve = -np.sin(inc) * np.sin(az)
    vn = np.sin(inc) * np.cos(az)
    vu = np.cos(inc)
    return ve, vn, vu


def regrid(src, lon_t, lat_t, val):
    """최근접 격자 재배치 (두 트랙의 지오코딩 격자가 조금 다르다)."""
    ix = np.clip(np.searchsorted(src['lon'], lon_t), 0, src['lon'].size - 1)
    iy = np.clip(np.searchsorted(-src['lat'], -lat_t), 0, src['lat'].size - 1)
    return val[np.ix_(iy, ix)]


def window_rate(D, t0, t1):
    """창 안 모든 에폭에 직선적합한 속도(mm/yr). 두 에폭 차분은 대기지연을 통째로 싣는다."""
    day = D['dates'].astype('datetime64[D]')
    m = (day >= np.datetime64(t0)) & (day <= np.datetime64(t1))
    t = (day[m] - day[m][0]).astype(int) / 365.25
    A = np.column_stack([t, np.ones_like(t)])
    ny, nx = D['ts'].shape[1:]
    sol, *_ = np.linalg.lstsq(A, D['ts'][m].reshape(m.sum(), -1), rcond=None)
    return sol[0].reshape(ny, nx), int(m.sum()), str(day[m][0]), str(day[m][-1])


def plane(lon2d, lat2d, v, m):
    x = (lon2d[m] - lon2d[m].mean()) * 111.320 * np.cos(np.radians(37.55))
    y = (lat2d[m] - lat2d[m].mean()) * 110.540
    A = np.column_stack([x, y, np.ones_like(x)])
    sol, *_ = np.linalg.lstsq(A, v[m], rcond=None)
    fit = A @ sol
    return dict(grad=float(np.hypot(sol[0], sol[1]) * 10),
                az=float(np.degrees(np.arctan2(sol[0], sol[1])) % 360),
                r2=float(1 - np.var(v[m] - fit) / np.var(v[m])),
                n=int(m.sum()), std=float(np.std(v[m])))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--t0', default='2025-09-09')
    p.add_argument('--t1', default='2026-04-26')
    a = p.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print('== 로드 ==')
    A = load(f'{ASC}/geo'); Dd = load(f'{DSC}/geo')
    for tag, X in (('ASC', A), ('DSC', Dd)):
        d = X['dates']
        print(f'  {tag} {X["direction"]}  {X["ts"].shape}  {d[0]}~{d[-1]} {len(d)}에폭  '
              f'inc 중앙 {np.median(X["inc"][X["good"]]):.2f}°  azi 중앙 {np.median(X["azi"][X["good"]]):.2f}°')

    # 공통 창 속도
    print(f'\n== 공통 창 {a.t0} ~ {a.t1} 선형속도 ==')
    rep = {'window': [a.t0, a.t1], 'reference': {'lon': REF_LL[0], 'lat': REF_LL[1]}}
    vA, nA, s0, s1 = window_rate(A, a.t0, a.t1)
    vD, nD, s2, s3 = window_rate(Dd, a.t0, a.t1)
    print(f'  ASC {nA}에폭 [{s0}..{s1}]   DSC {nD}에폭 [{s2}..{s3}]')
    rep['epochs'] = {'ASC': nA, 'DSC': nD, 'ASC_span': [s0, s1], 'DSC_span': [s2, s3]}

    # DSC 격자를 ASC 격자에 맞춘다
    LO, LA = np.meshgrid(A['lon'], A['lat'])
    vD_r = regrid(Dd, A['lon'], A['lat'], vD)
    gD_r = regrid(Dd, A['lon'], A['lat'], Dd['good'])
    incD = regrid(Dd, A['lon'], A['lat'], Dd['inc'])
    aziD = regrid(Dd, A['lon'], A['lat'], Dd['azi'])
    m = A['good'] & gD_r & (LO >= SEOUL[0]) & (LO <= SEOUL[1]) & (LA >= SEOUL[2]) & (LA <= SEOUL[3])
    print(f'  두 트랙 공통 유효화소 {m.sum():,}')

    # 기준점에서 0 이 되도록 (두 트랙 각각)
    d0 = np.hypot((LA - REF_LL[1]) * 110540, (LO - REF_LL[0]) * 111320 * np.cos(np.radians(37.55)))
    rm = (d0 <= 300) & m
    vA = vA - np.nanmean(vA[rm]); vD_r = vD_r - np.nanmean(vD_r[rm])
    print(f'  기준점 재정렬: 성북 300 m 내 {rm.sum()}화소')

    # ---- 1. 경사 비교 (판정의 핵심) ---------------------------------------
    print('\n== LOS 평면 경사 — 궤도마다 독립인 양 ==')
    pA = plane(LO, LA, vA, m); pD = plane(LO, LA, vD_r, m)
    print(f'  ASC  경사 {pA["grad"]:.3f} mm/yr/10km  방위 {pA["az"]:5.0f}°  R²={pA["r2"]:.3f}  std {pA["std"]:.2f}')
    print(f'  DSC  경사 {pD["grad"]:.3f} mm/yr/10km  방위 {pD["az"]:5.0f}°  R²={pD["r2"]:.3f}  std {pD["std"]:.2f}')
    r = float(np.corrcoef(vA[m], vD_r[m])[0, 1])
    print(f'  두 LOS 속도 상관 r={r:+.3f}')
    rep['plane_los'] = {'ASC': pA, 'DSC': pD, 'r_los': r}

    # ---- 2. 수직/동서 분해 ------------------------------------------------
    eA, nAv, uA = unit_los(A['inc'], A['azi'])
    eD, nDv, uD = unit_los(incD, aziD)
    print('\n== 시선 단위벡터 검산 (동/북/상) ==')
    for tag, (e, n, u) in (('ASC', (eA, nAv, uA)), ('DSC', (eD, nDv, uD))):
        print(f'  {tag}  e {np.median(e[m]):+.3f}  n {np.median(n[m]):+.3f}  u {np.median(u[m]):+.3f}')
    if np.median(eA[m]) * np.median(eD[m]) > 0:
        raise SystemExit('동서 성분 부호가 같다 — 방위각 규약이 틀렸다. 분해 중단.')
    if max(abs(np.median(nAv[m])), abs(np.median(nDv[m]))) > 0.25:
        raise SystemExit('남북 성분이 너무 크다 — 극궤도라면 0 에 가까워야 한다. 분해 중단.')
    det = eA * uD - eD * uA
    ok = m & (np.abs(det) > 1e-3)
    de = np.full(vA.shape, np.nan); du = np.full(vA.shape, np.nan)
    de[ok] = (vA[ok] * uD[ok] - vD_r[ok] * uA[ok]) / det[ok]
    du[ok] = (eA[ok] * vD_r[ok] - eD[ok] * vA[ok]) / det[ok]
    print('\n== 수직/동서 분해 ==')
    print(f'  기하 행렬식 |det| 중앙 {np.median(np.abs(det[ok])):.3f} (0 에 가까우면 분해 불안정)')
    print(f'  수직  중앙 {np.nanmedian(du[ok]):+6.2f} mm/yr  std {np.nanstd(du[ok]):5.2f}')
    print(f'  동서  중앙 {np.nanmedian(de[ok]):+6.2f} mm/yr  std {np.nanstd(de[ok]):5.2f}')
    pu = plane(LO, LA, du, ok); pe = plane(LO, LA, de, ok)
    print(f'  수직 경사 {pu["grad"]:.3f} mm/yr/10km 방위 {pu["az"]:5.0f}° R²={pu["r2"]:.3f}')
    print(f'  동서 경사 {pe["grad"]:.3f} mm/yr/10km 방위 {pe["az"]:5.0f}° R²={pe["r2"]:.3f}')
    rep['decomp'] = {'n': int(ok.sum()),
                     'up': dict(median=float(np.nanmedian(du[ok])), std=float(np.nanstd(du[ok])), plane=pu),
                     'east': dict(median=float(np.nanmedian(de[ok])), std=float(np.nanstd(de[ok])), plane=pe)}

    np.savez_compressed(f'{OUT}/asc_dsc_decomp.npz', lon=LO, lat=LA, vlos_asc=vA, vlos_dsc=vD_r,
                        vup=du, veast=de, mask=ok, inc_asc=A['inc'], inc_dsc=incD,
                        azi_asc=A['azi'], azi_dsc=aziD)
    with open(f'{OUT}/asc_dsc_decomp.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f'\n-> {OUT}/asc_dsc_decomp.npz, .json')


if __name__ == '__main__':
    main()
