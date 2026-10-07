#!/usr/bin/env python
"""
홍수 피해구역 탐지 (강임계 + 대조군 + 군집필터) — 2026 네팔 홍수

Otsu가 실패한 이유: 피해구역은 분포의 두 번째 봉우리가 아니라 극단 꼬리(전체의 ~1%)에
있다. Otsu는 본체 분포를 이등분하도록 설계돼 희소 클래스를 잡지 못한다(임계 -0.12 dB,
오탐률 102%). 대신 고정 강임계를 쓰고, 동일 절차를 baseline 쌍에 적용해 오탐을 뺀다.

  탐지 = (dB_post - dB_pre <= THR) AND (연결성분 크기 >= MINPIX)
  대조 = (dB_0816 - dB_0804 <= THR) AND (동일 필터)     -> 오탐 추정

usage: flood_detect.py <TRACK> [thr_dB] [buffer_m] [min_pixels]
"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from scipy import ndimage
from osgeo import gdal, ogr, osr
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
FLOOD = ['吉隆藏布', 'Bhote Koshi', 'Trishuli Ganga River', 'Mailung Khola']
REACHES = [('국경~Timure', 28.25, 28.40), ('Timure~Syabrubesi', 28.15, 28.25),
           ('Syabrubesi~Dhunche', 28.05, 28.15), ('Haku/Mailung', 27.97, 28.05),
           ('Betrawati~Devighat', 27.88, 27.97), ('Bidur 이남', 27.85, 27.88)]


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def rasterize(gt, shape, buf_m):
    els = json.load(open(f'{BASE}/aux/osm_rivers.json'))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    src = ogr.GetDriverByName('Memory').CreateDataSource('m')
    lyr = src.CreateLayer('r', srs, ogr.wkbPolygon)
    for e in els:
        if e.get('tags', {}).get('name', '') not in FLOOD:
            continue
        g = e.get('geometry') or []
        if len(g) < 2:
            continue
        ln = ogr.Geometry(ogr.wkbLineString)
        for p in g:
            ln.AddPoint_2D(p['lon'], p['lat'])
        f = ogr.Feature(lyr.GetLayerDefn()); f.SetGeometry(ln.Buffer(buf_m / 111320.)); lyr.CreateFeature(f)
    t = gdal.GetDriverByName('MEM').Create('', shape[1], shape[0], 1, gdal.GDT_Byte)
    t.SetGeoTransform(gt); t.SetProjection(srs.ExportToWkt())
    gdal.RasterizeLayer(t, [1], lyr, burn_values=[1])
    return t.GetRasterBand(1).ReadAsArray().astype(bool)


def clean(mask, minpix):
    """연결성분이 minpix 미만이면 스펙클로 보고 제거."""
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if n == 0:
        return mask, 0
    sz = np.bincount(lab.ravel()); sz[0] = 0
    keep = np.isin(lab, np.flatnonzero(sz >= minpix))
    return keep, int((sz >= minpix).sum())


def main():
    trk = sys.argv[1]
    thr = float(sys.argv[2]) if len(sys.argv) > 2 else -6.0
    bufm = float(sys.argv[3]) if len(sys.argv) > 3 else 300.
    minpix = int(sys.argv[4]) if len(sys.argv) > 4 else 5

    D = f'{BASE}/work/stack_{trk}/merged/interferograms/20260804_20260816'
    d04, gt = rd(f'{D}/db_20260804.geo')
    d16, _ = rd(f'{D}/db_20260816.geo')
    d28, _ = rd(f'{D}/db_20260828.geo')
    dem = gdal.Warp('', f'{BASE}/DEM/nepal_aoi.wgs84.tif', format='MEM',
                    outputBounds=[gt[0], gt[3] + gt[5] * d04.shape[0],
                                  gt[0] + gt[1] * d04.shape[1], gt[3]],
                    width=d04.shape[1], height=d04.shape[0])
    H = dem.GetRasterBand(1).ReadAsArray().astype(float)
    px = abs(gt[1]) * 111320 * np.cos(np.deg2rad(28.1)); py = abs(gt[5]) * 111320
    gy, gx = np.gradient(H, py, px)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = np.degrees(np.arctan2(-gx, gy)) % 360
    rel = np.abs(((aspect - 77.0 + 180) % 360) - 180)
    bad = ((slope >= 39) & (rel < 60)) | ((slope >= 51) & (rel > 120))

    corr = rasterize(gt, d04.shape, bufm)
    good = (d04 != 0) & (d16 != 0) & (d28 != 0) & ~bad
    m = corr & good
    px_km2 = abs(gt[1] * gt[5]) * (111320 ** 2) * np.cos(np.deg2rad(28.1)) / 1e6

    co_raw = m & ((d28 - d16) <= thr)
    bs_raw = m & ((d16 - d04) <= thr)
    co, nco = clean(co_raw, minpix)
    bs, nbs = clean(bs_raw, minpix)
    co &= m; bs &= m

    print(f'임계 {thr:+.1f} dB | 회랑 {bufm:.0f} m | 최소군집 {minpix}화소(≈{minpix*px_km2*1e6/1e3:.1f}천 m²)')
    print(f'회랑 유효 {m.sum():,}화소 = {m.sum()*px_km2:.1f} km²\n')
    print(f'{"":22}{"화소":>9}{"면적":>10}{"군집수":>8}')
    print('-' * 50)
    print(f'{"co-event (홍수포함)":22}{co.sum():>9,}{co.sum()*px_km2:>9.3f}㎢{nco:>8}')
    print(f'{"baseline (정상12일)":22}{bs.sum():>9,}{bs.sum()*px_km2:>9.3f}㎢{nbs:>8}')
    net = (co.sum() - bs.sum()) * px_km2
    print(f'{"순 탐지":22}{co.sum()-bs.sum():>9,}{net:>9.3f}㎢')
    print(f'{"오탐률":22}{"":>9}{100*bs.sum()/max(co.sum(),1):>9.1f}%'
          f'   배수 {co.sum()/max(bs.sum(),1):.1f}x\n')

    lat = gt[3] + gt[5] * np.arange(d04.shape[0])
    print(f'{"구간":<22}{"회랑㎢":>8}{"탐지㎢":>9}{"대조㎢":>9}{"순㎢":>8}{"배수":>7}')
    print('-' * 66)
    rows = []
    for nm, s, n in REACHES:
        band = ((lat >= s) & (lat < n))[:, None]
        mm = m & band
        if mm.sum() < 100:
            continue
        c = (co & band).sum(); b = (bs & band).sum()
        print(f'{nm:<22}{mm.sum()*px_km2:>8.2f}{c*px_km2:>9.3f}{b*px_km2:>9.3f}'
              f'{(c-b)*px_km2:>8.3f}{c/max(b,1):>6.1f}x')
        rows.append(dict(reach=nm, corridor_km2=float(mm.sum()*px_km2),
                         detect_km2=float(c*px_km2), control_km2=float(b*px_km2),
                         net_km2=float((c-b)*px_km2)))

    outdir = f'{BASE}/analysis/{trk}'
    drv = gdal.GetDriverByName('GTiff')
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    for nm, arr in [('flood_detect', co), ('flood_control', bs), ('db_change', np.where(m, d28-d16, np.nan))]:
        p = f'{outdir}/{nm}.tif'
        ds = drv.Create(p, d04.shape[1], d04.shape[0], 1, gdal.GDT_Float32,
                        options=['COMPRESS=DEFLATE', 'TILED=YES'])
        ds.SetGeoTransform(gt); ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(np.asarray(arr, np.float32)); ds = None
    json.dump(dict(track=trk, thr_dB=thr, buffer_m=bufm, min_pixels=minpix,
                   detect_km2=float(co.sum()*px_km2), control_km2=float(bs.sum()*px_km2),
                   net_km2=float(net), reaches=rows),
              open(f'{outdir}/flood_detect.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nwrote {outdir}/flood_detect.tif, flood_control.tif, db_change.tif, flood_detect.json')


if __name__ == '__main__':
    main()
