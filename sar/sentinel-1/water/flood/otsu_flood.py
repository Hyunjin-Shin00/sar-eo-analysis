#!/usr/bin/env python
"""
Otsu 임계 기반 홍수 피해구역 분할 — 2026 네팔 홍수

물리적 근거: 사후영상은 사건 2.4일 뒤라 물은 이미 빠졌다. 대신 홍수가 식생을 벗기고
매끈한 모래/자갈/이토를 퇴적시키면 경면반사로 후방산란이 크게 떨어진다.
따라서 "낮은 dB"는 수면이 아니라 신생 퇴적·세굴면을 가리킨다.

핵심 설계 — Otsu는 잡음에도 반드시 임계값을 내놓는다. 그래서:
  co-event 쌍 (0816->0828, 홍수 포함)  와
  baseline 쌍 (0804->0816, 정상 12일) 에
완전히 동일한 절차를 적용하고, baseline에서 잡힌 면적을 오탐(false positive)으로 본다.
실제 탐지량 = co-event 면적 − baseline 면적.

usage: otsu_flood.py <TRACK> [buffer_m]
"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from osgeo import gdal, ogr, osr
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
FLOOD = ['吉隆藏布', 'Bhote Koshi', 'Trishuli Ganga River', 'Mailung Khola']
REACHES = [('국경~Timure', 28.25, 28.40), ('Timure~Syabrubesi', 28.15, 28.25),
           ('Syabrubesi~Dhunche', 28.05, 28.15), ('Haku/Mailung', 27.97, 28.05),
           ('Betrawati~Devighat', 27.88, 27.97), ('Bidur 이남', 27.85, 27.88)]


def otsu(x, nbins=256):
    """1D Otsu. 클래스 간 분산을 최대화하는 임계값."""
    x = x[np.isfinite(x)]
    lo, hi = np.percentile(x, [0.5, 99.5])
    h, edges = np.histogram(x, bins=nbins, range=(lo, hi))
    h = h.astype(float); p = h / h.sum()
    c = np.cumsum(p)
    centers = (edges[:-1] + edges[1:]) / 2
    m = np.cumsum(p * centers)
    mt = m[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        sb = (mt * c - m) ** 2 / (c * (1 - c))
    sb[~np.isfinite(sb)] = -1
    return float(centers[int(np.argmax(sb))])


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def rasterize(names, gt, shape, buf_m):
    els = json.load(open(f'{BASE}/aux/osm_rivers.json'))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    src = ogr.GetDriverByName('Memory').CreateDataSource('m')
    lyr = src.CreateLayer('r', srs, ogr.wkbPolygon)
    for e in els:
        if e.get('tags', {}).get('name', '') not in names:
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


def terrain_masks(H, gt):
    """ASC(시선방위 77도, 입사각 39도) 기하의 layover/shadow 추정."""
    px = abs(gt[1]) * 111320 * np.cos(np.deg2rad(28.1)); py = abs(gt[5]) * 111320
    gy, gx = np.gradient(H, py, px)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = np.degrees(np.arctan2(-gx, gy)) % 360
    rel = np.abs(((aspect - 77.0 + 180) % 360) - 180)
    return (slope >= 39) & (rel < 60), (slope >= 51) & (rel > 120), slope


def main():
    trk = sys.argv[1]
    bufm = float(sys.argv[2]) if len(sys.argv) > 2 else 300.
    D = f'{BASE}/work/stack_{trk}/merged/interferograms/20260804_20260816'
    d04, gt = rd(f'{D}/db_20260804.geo')
    d16, _ = rd(f'{D}/db_20260816.geo')
    d28, _ = rd(f'{D}/db_20260828.geo')

    dem = gdal.Warp('', f'{BASE}/DEM/nepal_aoi.wgs84.tif', format='MEM',
                    outputBounds=[gt[0], gt[3] + gt[5] * d04.shape[0],
                                  gt[0] + gt[1] * d04.shape[1], gt[3]],
                    width=d04.shape[1], height=d04.shape[0])
    H = dem.GetRasterBand(1).ReadAsArray().astype(float)
    lay, sha, slope = terrain_masks(H, gt)

    corr = rasterize(FLOOD, gt, d04.shape, bufm)
    good = (d04 != 0) & (d16 != 0) & (d28 != 0) & np.isfinite(d04) & np.isfinite(d16) & np.isfinite(d28)
    good &= ~lay & ~sha
    m = corr & good
    px_km2 = abs(gt[1] * gt[5]) * (111320 ** 2) * np.cos(np.deg2rad(28.1)) / 1e6
    print(f'회랑 버퍼 {bufm:.0f} m,  유효화소 {m.sum():,} ({m.sum()*px_km2:.1f} km²)')
    print(f'  (layover {100*lay[corr].mean():.1f}% / shadow {100*sha[corr].mean():.1f}% 제외)\n')

    dc = np.where(m, d28 - d16, np.nan)   # co-event 변화
    db_ = np.where(m, d16 - d04, np.nan)  # baseline 변화 (오탐 대조)

    # --- (A) 사용자 요청: 사후 절대 dB 에 Otsu ---
    t_abs = otsu(d28[m])
    print(f'[A] 사후 dB Otsu 임계 = {t_abs:.2f} dB')
    for nm, arr, lbl in [('사후 0828', d28, 'co-event'), ('사전 0816', d16, 'baseline')]:
        low = m & (arr <= t_abs)
        print(f'    {nm}: 저dB 면적 {low.sum()*px_km2:7.2f} km²')
    print('    → 두 날짜가 비슷하면 "상시 저산란지(수면·평활면)"를 잡은 것이지 홍수가 아님\n')

    # --- (B) 변화 dB 에 Otsu (권장) ---
    t_ch = otsu(dc[m])
    print(f'[B] 변화 dB Otsu 임계 = {t_ch:.2f} dB')
    res = {}
    for lbl, arr in [('co-event(0816→0828)', dc), ('baseline(0804→0816)', db_)]:
        sel = m & (arr <= t_ch)
        res[lbl] = sel
        print(f'    {lbl}: {sel.sum():>7,} 화소  {sel.sum()*px_km2:7.2f} km²')
    a_co = res['co-event(0816→0828)'].sum() * px_km2
    a_bs = res['baseline(0804→0816)'].sum() * px_km2
    print(f'    >>> 순 탐지 = {a_co:.2f} − {a_bs:.2f} = {a_co-a_bs:+.2f} km²'
          f'  (오탐률 {100*a_bs/max(a_co,1e-9):.0f}%)\n')

    # --- (C) 결합: 저dB AND 유의감소 ---
    comb_co = m & (d28 <= t_abs) & (dc <= t_ch)
    comb_bs = m & (d16 <= t_abs) & (db_ <= t_ch)
    print(f'[C] 결합(저dB ∩ 유의감소): co-event {comb_co.sum()*px_km2:.2f} km² / '
          f'baseline {comb_bs.sum()*px_km2:.2f} km² → 순 {comb_co.sum()*px_km2-comb_bs.sum()*px_km2:+.2f} km²\n')

    # --- 구간별 ---
    lat = gt[3] + gt[5] * np.arange(d04.shape[0])
    print(f'{"구간":<22}{"회랑km²":>9}{"co-event":>10}{"baseline":>10}{"순탐지":>9}{"순비율":>8}')
    print('-' * 70)
    rows = []
    for nm, s, n in REACHES:
        band = ((lat >= s) & (lat < n))[:, None]
        mm = m & band
        if mm.sum() < 100:
            print(f'{nm:<22}{mm.sum()*px_km2:>9.2f}{"—":>10}{"—":>10}{"—":>9}{"—":>8}'); continue
        c = (res['co-event(0816→0828)'] & band).sum() * px_km2
        b = (res['baseline(0804→0816)'] & band).sum() * px_km2
        tot = mm.sum() * px_km2
        print(f'{nm:<22}{tot:>9.2f}{c:>10.2f}{b:>10.2f}{c-b:>9.2f}{100*(c-b)/tot:>7.1f}%')
        rows.append(dict(reach=nm, corridor_km2=float(tot), coevent_km2=float(c),
                         baseline_km2=float(b), net_km2=float(c - b)))

    outdir = f'{BASE}/analysis/{trk}'
    os.makedirs(outdir, exist_ok=True)
    drv = gdal.GetDriverByName('GTiff')
    for nm, arr in [('otsu_coevent_mask', res['co-event(0816→0828)']),
                    ('otsu_baseline_mask', res['baseline(0804→0816)']),
                    ('db_change_coevent', dc)]:
        p = f'{outdir}/{nm}.tif'
        ds = drv.Create(p, d04.shape[1], d04.shape[0], 1, gdal.GDT_Float32,
                        options=['COMPRESS=DEFLATE', 'TILED=YES'])
        ds.SetGeoTransform(gt)
        srs = osr.SpatialReference(); srs.ImportFromEPSG(4326); ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(np.asarray(arr, np.float32)); ds = None
    json.dump(dict(track=trk, buffer_m=bufm, thresh_abs_dB=t_abs, thresh_change_dB=t_ch,
                   coevent_km2=float(a_co), baseline_km2=float(a_bs),
                   net_km2=float(a_co - a_bs), reaches=rows),
              open(f'{outdir}/otsu_summary.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nwrote {outdir}/otsu_*.tif, otsu_summary.json')


if __name__ == '__main__':
    main()
