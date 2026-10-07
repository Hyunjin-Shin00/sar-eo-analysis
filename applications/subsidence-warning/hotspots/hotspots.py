#!/usr/bin/env python3
"""국지 침하 핫스팟 추출.

판정 기준은 '절대 속도'가 아니라 '주변 대비 국지 이상'이다.  서울 전역에는
남서가 북동보다 부푸는 실제 경사가 있고(fig6 에서 하강궤도로 수직 운동임을
확정), 절대값으로 자르면 그 경사 때문에 북동 전체가 핫스팟으로 찍힌다.
따라서 격자마다 평면 추세를 뺀 잔차에서 음의 이상만 고른다.

주 레이어는 S1 PS 의 secular 수직속도다.  보고서대로 mm/yr 로 읽을 수 있는
산출물은 이것뿐이다.  CSK 는 8.7개월(겨울→여름) 누적변위로만 쓰고, 연율로
환산하지 않은 채 '같은 자리에서 부호가 같은가'라는 확인용으로만 쓴다.
"""
import json
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, '<DATA_ROOT>/CSK_PSInSAR/code')
from compare_all import CSK, S1, fit_secular, full_rate, load_ps, reref

CELL_M = 100.0                 # 격자 한 변
NMIN_S1, NMIN_CSK = 5, 20      # 격자당 최소 PS (밀도비 6.5배 반영)
K_SIGMA = 2.5                  # 잔차 임계 (robust sigma 배수)
MIN_CELLS = 5                  # 군집 최소 격자수 = 0.05 km²
LAT0 = 37.55
MPD_LON = 111320 * np.cos(np.radians(LAT0))
MPD_LAT = 110540


def to_grid(lon, lat, val, nmin, bounds):
    """100 m 격자 평균.  반환: 평균배열(ny,nx), 개수배열."""
    lo0, la0, lo1, la1 = bounds
    nx = int(np.ceil((lo1 - lo0) * MPD_LON / CELL_M))
    ny = int(np.ceil((la1 - la0) * MPD_LAT / CELL_M))
    ix = ((lon - lo0) * MPD_LON / CELL_M).astype(int)
    iy = ((lat - la0) * MPD_LAT / CELL_M).astype(int)
    ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny) & np.isfinite(val)
    flat = iy[ok] * nx + ix[ok]
    cnt = np.bincount(flat, minlength=ny * nx).astype(float)
    tot = np.bincount(flat, weights=val[ok], minlength=ny * nx)
    with np.errstate(invalid='ignore', divide='ignore'):
        mean = tot / cnt
    mean[cnt < nmin] = np.nan
    return mean.reshape(ny, nx), cnt.reshape(ny, nx), (lo0, la0, nx, ny)


def deplane(G):
    """격자에서 1차 평면 추세 제거.  서울 전역 경사는 실제 신호지만 광역이라
    국지 이상 탐지에서는 배경이다."""
    ny, nx = G.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    m = np.isfinite(G)
    A = np.column_stack([xx[m], yy[m], np.ones(m.sum())])
    c, *_ = np.linalg.lstsq(A, G[m], rcond=None)
    plane = c[0] * xx + c[1] * yy + c[2]
    return G - plane, c


def rsigma(x):
    v = x[np.isfinite(x)]
    return 1.4826 * np.median(np.abs(v - np.median(v)))


def main():
    out = {}
    print('[1/5] PS 적재', flush=True)
    P1 = load_ps(f'{S1}/results/seoul_s1_ps.npz')
    reref(P1)
    sec, amp, lin = fit_secular(P1)
    v_s1 = sec * P1['kv']                       # 수직 secular mm/yr
    print(f'      S1  n={len(v_s1):,}  중앙값 {np.nanmedian(v_s1):+.2f} mm/yr', flush=True)

    PC = load_ps(f'{CSK}/results/seoul_csk_ps.npz')
    reref(PC)
    rate, span = full_rate(PC)
    v_csk = rate * span * PC['kv']              # 관측기간 누적 수직 mm (연율 아님)
    print(f'      CSK n={len(v_csk):,}  {span:.2f}년 누적 중앙값 '
          f'{np.nanmedian(v_csk):+.2f} mm', flush=True)

    bounds = (min(P1['lon'].min(), PC['lon'].min()), min(P1['lat'].min(), PC['lat'].min()),
              max(P1['lon'].max(), PC['lon'].max()), max(P1['lat'].max(), PC['lat'].max()))

    print('[2/5] 100 m 격자화 + 평면추세 제거', flush=True)
    G1, C1, geo = to_grid(P1['lon'], P1['lat'], v_s1, NMIN_S1, bounds)
    GC, CC, _ = to_grid(PC['lon'], PC['lat'], v_csk, NMIN_CSK, bounds)
    R1, c1 = deplane(G1)
    RC, cc = deplane(GC)
    s1sig, cksig = rsigma(R1), rsigma(RC)
    lo0, la0, nx, ny = geo
    print(f'      격자 {ny}x{nx}  유효 S1 {np.isfinite(G1).sum():,} / CSK '
          f'{np.isfinite(GC).sum():,}', flush=True)
    print(f'      잔차 robust sigma  S1 {s1sig:.2f} mm/yr   CSK {cksig:.2f} mm', flush=True)

    print(f'[3/5] 임계 {K_SIGMA}sigma 이하 군집화', flush=True)
    thr = -K_SIGMA * s1sig
    hot = np.isfinite(R1) & (R1 <= thr)
    lab, n = ndimage.label(hot, structure=np.ones((3, 3)))
    print(f'      임계 {thr:+.2f} mm/yr → 격자 {hot.sum():,}개, 연결군집 {n}개', flush=True)

    gu = json.load(open(f'{CSK}/aux/seoul_municipalities_geo.json'))

    def gu_of(lo, la):
        from matplotlib.path import Path
        for ft in gu['features']:
            g = ft['geometry']
            polys = g['coordinates'] if g['type'] == 'Polygon' else [p[0] for p in g['coordinates']]
            for ring in (polys if g['type'] == 'Polygon' else polys):
                r = np.asarray(ring if np.ndim(ring[0]) == 1 else ring[0])
                if Path(r[:, :2]).contains_point((lo, la)):
                    return ft['properties']['name']
        return '-'

    recs = []
    for i in range(1, n + 1):
        m = lab == i
        k = int(m.sum())
        if k < MIN_CELLS:
            continue
        yy, xx = np.nonzero(m)
        lo = lo0 + (xx.mean() + 0.5) * CELL_M / MPD_LON
        la = la0 + (yy.mean() + 0.5) * CELL_M / MPD_LAT
        ck = RC[m]
        ckv = ck[np.isfinite(ck)]
        recs.append(dict(
            id=0, lon=round(float(lo), 6), lat=round(float(la), 6),
            area_km2=round(k * CELL_M ** 2 / 1e6, 3), ncell=k,
            s1_anom=round(float(np.nanmean(R1[m])), 2),
            s1_min=round(float(np.nanmin(R1[m])), 2),
            s1_abs=round(float(np.nanmean(G1[m])), 2),
            n_ps=int(np.nansum(C1[m])),
            csk_anom=round(float(ckv.mean()), 2) if ckv.size else None,
            csk_cov=round(float(ckv.size / k), 2),
            confirm=bool(ckv.size >= max(2, 0.3 * k) and ckv.mean() <= -cksig),
            gu=gu_of(lo, la)))
    recs.sort(key=lambda r: r['s1_anom'])
    for j, r in enumerate(recs, 1):
        r['id'] = j
    print(f'      {MIN_CELLS}격자(0.05 km²) 이상 = {len(recs)}개, '
          f'CSK 확인 {sum(r["confirm"] for r in recs)}개', flush=True)

    print('[4/5] 저장', flush=True)
    out = dict(method=dict(cell_m=CELL_M, k_sigma=K_SIGMA, min_cells=MIN_CELLS,
                           nmin_s1=NMIN_S1, nmin_csk=NMIN_CSK,
                           s1_sigma=round(float(s1sig), 3), csk_sigma=round(float(cksig), 3),
                           threshold_mmyr=round(float(thr), 3),
                           s1_plane=[round(float(x), 4) for x in c1],
                           csk_plane=[round(float(x), 4) for x in cc],
                           layer_s1='secular vertical mm/yr (annual+semiannual removed)',
                           layer_csk=f'cumulative vertical mm over {span:.2f} yr — NOT a rate'),
               n_hotspot=len(recs), hotspots=recs)
    with open(f'{CSK}/results/compare/hotspots.json', 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    np.savez_compressed(f'{CSK}/results/compare/hotspot_grids.npz',
                        R1=R1.astype('f4'), RC=RC.astype('f4'), G1=G1.astype('f4'),
                        GC=GC.astype('f4'), C1=C1.astype('f4'), lab=lab.astype('i4'),
                        lo0=lo0, la0=la0, cell_m=CELL_M, mpd_lon=MPD_LON, mpd_lat=MPD_LAT)
    print('[5/5] 완료', flush=True)
    for r in recs[:15]:
        print(f"   #{r['id']:2d} {r['gu']:6s} {r['lat']:.5f},{r['lon']:.5f} "
              f"{r['area_km2']:.2f}km² S1 {r['s1_anom']:+.2f} (min {r['s1_min']:+.2f}) "
              f"CSK {r['csk_anom']} {'✓' if r['confirm'] else ''}")


if __name__ == '__main__':
    main()
