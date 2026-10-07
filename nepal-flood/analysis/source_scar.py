#!/usr/bin/env python
"""
빙하 붕괴 원점의 붕괴 흔적(scar) 탐지 — 2026 네팔 홍수

하류 홍수 탐지는 하천 300 m 버퍼 안에서만 수행하므로, 산 사면에 있는 붕괴 원점은
그 마스크에서 제외된다. 여기서는 원점 주변 박스에 같은 기준(강임계 + 연결성분 +
대조군 오탐보정)을 별도로 적용한다.

usage: source_scar.py <TRACK> [thr_dB] [min_pixels]
"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from scipy import ndimage
from osgeo import gdal, osr
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
SRC_LON, SRC_LAT = 85.5252, 28.2853     # 보고된 붕괴 좌표 (USGS/언론)
HALF = 0.0170                            # 원점 주변 ±약 1.7 km


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def clean(m, minpix):
    lab, n = ndimage.label(m, np.ones((3, 3)))
    if n == 0:
        return m, 0
    sz = np.bincount(lab.ravel()); sz[0] = 0
    return np.isin(lab, np.flatnonzero(sz >= minpix)), lab, sz


def main():
    trk = sys.argv[1]
    thr = float(sys.argv[2]) if len(sys.argv) > 2 else -6.0
    minpix = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    D = f'{BASE}/work/stack_{trk}/merged/interferograms/20260804_20260816'
    d04, gt = rd(f'{D}/db_20260804.geo')
    d16, _ = rd(f'{D}/db_20260816.geo')
    d28, _ = rd(f'{D}/db_20260828.geo')
    px_km2 = abs(gt[1] * gt[5]) * (111320 ** 2) * np.cos(np.deg2rad(28.1)) / 1e6

    box = np.zeros(d04.shape, bool)
    c0 = int((SRC_LON - HALF - gt[0]) / gt[1]); c1 = int((SRC_LON + HALF - gt[0]) / gt[1])
    r0 = int((SRC_LAT + HALF * .85 - gt[3]) / gt[5]); r1 = int((SRC_LAT - HALF * .85 - gt[3]) / gt[5])
    box[r0:r1, c0:c1] = True
    ok = box & (d04 != 0) & (d16 != 0) & (d28 != 0)

    co = np.where(ok, d28 - d16, 0.0)
    bs = np.where(ok, d16 - d04, 0.0)
    scar, lab, sz = clean(ok & (co <= thr), minpix)
    ctrl, _, _ = clean(ok & (bs <= thr), minpix)
    a_s, a_c = scar.sum() * px_km2 * 100, ctrl.sum() * px_km2 * 100

    print(f'붕괴 원점 박스 {ok.sum()*px_km2:.2f} km²  임계 {thr:+.0f} dB  최소군집 {minpix}화소')
    print(f'  사건쌍 붕괴흔적 {a_s:.1f} ha  /  대조쌍 {a_c:.1f} ha  →  {a_s/max(a_c,1e-9):.0f}배')
    top = int(np.argmax(sz)) if sz.max() else 0
    ys, xs = np.where(lab == top)
    la = gt[3] + gt[5] * ys.mean(); lo = gt[0] + gt[1] * xs.mean()
    dist = float(np.hypot((lo - SRC_LON) * 98, (la - SRC_LAT) * 111))
    mean_db = float(np.mean(co[lab == top]))
    print(f'  최대 군집 {sz[top]*px_km2*100:.1f} ha  중심 {la:.4f}N {lo:.4f}E  평균 {mean_db:.1f} dB')
    print(f'  보고 좌표와 거리 {dist*1000:.0f} m')

    drv = gdal.GetDriverByName('GTiff')
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    p = f'{BASE}/analysis/{trk}/source_scar.tif'
    ds = drv.Create(p, d04.shape[1], d04.shape[0], 1, gdal.GDT_Float32,
                    options=['COMPRESS=DEFLATE', 'TILED=YES'])
    ds.SetGeoTransform(gt); ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(scar.astype(np.float32)); ds = None
    json.dump(dict(thr_dB=thr, min_pixels=minpix, scar_ha=float(a_s), control_ha=float(a_c),
                   ratio=float(a_s / max(a_c, 1e-9)), top_ha=float(sz[top] * px_km2 * 100),
                   top_lat=float(la), top_lon=float(lo), top_mean_dB=mean_db,
                   dist_to_reported_m=dist * 1000, ref_lat=SRC_LAT, ref_lon=SRC_LON),
              open(f'{BASE}/analysis/{trk}/source_scar.json', 'w'), ensure_ascii=False, indent=1)
    print(f'  wrote {p}, source_scar.json')


if __name__ == '__main__':
    main()
