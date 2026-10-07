#!/usr/bin/env python
"""
고도+기준결맞음 2차원 매칭 검정 — 2026 네팔 홍수

Δcoh 지도의 지배적 패턴은 홍수가 아니라 고도다: 고산부는 기준쌍(08-04~08-16)에서
습설로 탈결맞음됐다가 사건쌍(08-16~08-28)에서 건조/무설이 되어 결맞음이 크게 올랐다.
회랑은 전부 저지대이므로, 장면 전체를 대조군으로 쓰면 이 고도 효과가 통째로
"회랑이 더 나쁨"으로 새어든다.

여기서는 (고도 밴드 x 기준결맞음 밴드) 격자로 셀을 나누고, 각 셀 안에서만
회랑 vs 비회랑을 비교한 뒤 회랑 화소수로 가중 평균한다. 같은 고도·같은 초기
결맞음 조건에서 회랑만 더 떨어졌는지가 남는 질문이 된다.

usage: corridor_matched2.py <TRACK> [buffer_m]
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
EXCL = ['Langtang Khola', 'Melamchi Khola', 'Indrawati river', 'Likhu Khola',
        'Tadi Khola', 'Falaakhu River', '东林藏布']
REACHES = [('국경~Timure', 28.25, 28.40), ('Timure~Syabrubesi', 28.15, 28.25),
           ('Syabrubesi~Dhunche', 28.05, 28.15), ('Haku/Mailung', 27.97, 28.05),
           ('Betrawati~Devighat', 27.88, 27.97), ('Bidur 이남', 27.85, 27.88)]
HB = [0, 800, 1200, 1600, 2000, 2600, 3400, 9000]          # 고도 밴드 (m)
CB_ = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.70, 1.01]      # 기준결맞음 밴드


def rasterize(names, gt, shape, buf_deg):
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
        f = ogr.Feature(lyr.GetLayerDefn()); f.SetGeometry(ln.Buffer(buf_deg)); lyr.CreateFeature(f)
    t = gdal.GetDriverByName('MEM').Create('', shape[1], shape[0], 1, gdal.GDT_Byte)
    t.SetGeoTransform(gt); t.SetProjection(srs.ExportToWkt())
    gdal.RasterizeLayer(t, [1], lyr, burn_values=[1])
    return t.GetRasterBand(1).ReadAsArray().astype(bool)


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def matched_diff(dcoh, cb, H, sel_in, sel_out, min_n=100, verbose=False):
    """(고도 x 기준결맞음) 셀별 중앙값 차이를 회랑 화소수로 가중 평균."""
    tot_w = tot_d = 0.0
    cells = []
    for h0, h1 in zip(HB[:-1], HB[1:]):
        hb = (H >= h0) & (H < h1)
        for c0, c1 in zip(CB_[:-1], CB_[1:]):
            cbb = (cb >= c0) & (cb < c1)
            mi = sel_in & hb & cbb
            mo = sel_out & hb & cbb
            ni, no = int(mi.sum()), int(mo.sum())
            if ni < min_n or no < min_n:
                continue
            di, do = float(np.median(dcoh[mi])), float(np.median(dcoh[mo]))
            tot_w += ni; tot_d += (di - do) * ni
            cells.append((h0, h1, c0, c1, ni, no, di, do, di - do))
    if verbose:
        print(f'{"고도(m)":<14}{"coh_base":<12}{"회랑n":>8}{"대조n":>9}{"회랑Δ":>9}{"대조Δ":>9}{"차이":>9}')
        print('-' * 72)
        for h0, h1, c0, c1, ni, no, di, do, dd in cells:
            print(f'{h0}-{h1:<9}{c0:.2f}-{c1:<7.2f}{ni:>8,}{no:>9,}{di:>9.3f}{do:>9.3f}{dd:>9.3f}')
        print('-' * 72)
    return (tot_d / tot_w if tot_w else float('nan')), int(tot_w), len(cells)


def main():
    trk = sys.argv[1]
    bufm = float(sys.argv[2]) if len(sys.argv) > 2 else 150.
    d = f'{BASE}/analysis/{trk}'
    dcoh, gt = rd(f'{d}/dcoh.tif')
    cb, _ = rd(f'{d}/coh_baseline.tif')
    dem = gdal.Warp('', f'{BASE}/DEM/nepal_aoi.wgs84.tif', format='MEM',
                    outputBounds=[gt[0], gt[3] + gt[5] * dcoh.shape[0],
                                  gt[0] + gt[1] * dcoh.shape[1], gt[3]],
                    width=dcoh.shape[1], height=dcoh.shape[0])
    H = dem.GetRasterBand(1).ReadAsArray().astype(float)

    corr = rasterize(FLOOD, gt, dcoh.shape, bufm / 111320.)
    excl = rasterize(EXCL, gt, dcoh.shape, 600 / 111320.)
    valid = np.isfinite(dcoh) & (cb > 0)
    cin, cout = corr & valid, (~corr) & (~excl) & valid

    print(f'=== 고도 x 기준결맞음 2D 매칭 (버퍼 {bufm:.0f} m) ===')
    print(f'회랑 고도 범위: {np.percentile(H[cin],[5,50,95]).round(0)} m')
    print(f'대조 고도 범위: {np.percentile(H[cout],[5,50,95]).round(0)} m\n')
    tot, w, nc = matched_diff(dcoh, cb, H, cin, cout, verbose=True)
    print(f'매칭 셀 {nc}개, 가중 회랑화소 {w:,}')
    print(f'>>> 고도·결맞음 매칭 후 회랑 초과 Δcoh = {tot:+.4f}')
    print('    (음수여야 홍수 기인 탈결맞음. 0 근처면 앞선 -0.081은 고도 교란이었다는 뜻)\n')

    print('=== 구간별 (같은 매칭 적용) ===')
    lat = gt[3] + gt[5] * np.arange(dcoh.shape[0])
    rows = []
    print(f'{"구간":<24}{"회랑n":>8}{"매칭셀":>7}{"초과Δcoh":>11}{"중앙고도":>10}')
    print('-' * 62)
    for nm, s, n in REACHES:
        band = ((lat >= s) & (lat < n))[:, None]
        mi = cin & band
        if mi.sum() < 200:
            print(f'{nm:<24}{mi.sum():>8,}{"—":>7}{"—":>11}{"—":>10}'); continue
        # 대조군은 같은 위도대로 제한하지 않는다(고도로 이미 매칭됨)
        v, w2, nc2 = matched_diff(dcoh, cb, H, mi, cout, min_n=50)
        print(f'{nm:<24}{mi.sum():>8,}{nc2:>7}{v:>11.4f}{np.median(H[mi]):>9.0f}m')
        rows.append(dict(reach=nm, n=int(mi.sum()), cells=nc2, excess_dcoh=float(v),
                         median_elev=float(np.median(H[mi]))))
    json.dump(dict(track=trk, buffer_m=bufm, overall_excess_dcoh=float(tot), reaches=rows),
              open(f'{d}/corridor_matched2.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
