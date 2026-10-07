#!/usr/bin/env python
"""
노출 분석 (인구 / 건물 / 도로 / 시설) — 2026 네팔 홍수

인구는 WorldPop 2020 UN보정 constrained(93 m). 30 m 격자로 옮길 때 셀 합을 그대로
쓰면 중복 계상되므로 **면적당 밀도로 변환한 뒤 화소 면적을 곱한다.**

노출 정의 2단계:
  ① 분석 회랑  = 홍수 수계 300 m 버퍼 (UNOSAT의 'analysed area'에 대응)
  ② 탐지 피해구역 = 후방산란 -6 dB 이상 감소 + 군집 >=5화소, 여기에 인접 200 m 포함
     (SAR가 잡는 것은 강한 지표 변화이고 실제 피해는 그 주변까지 미치므로 버퍼를 둔다)

usage: exposure.py <TRACK>
"""
import os, sys, json, math
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from scipy import ndimage
from osgeo import gdal, ogr, osr
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
FLOOD = ['吉隆藏布', 'Bhote Koshi', 'Trishuli Ganga River', 'Mailung Khola']
DISTRICTS = ['Rasuwa', 'Nuwakot', 'Dhading', 'Gyirong County']


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def mem_layer(geoms, gtype=ogr.wkbPolygon):
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    src = ogr.GetDriverByName('Memory').CreateDataSource('m')
    lyr = src.CreateLayer('l', srs, gtype)
    for g in geoms:
        f = ogr.Feature(lyr.GetLayerDefn()); f.SetGeometry(g); lyr.CreateFeature(f)
    return src, lyr


def burn(lyr, gt, shape):
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    t = gdal.GetDriverByName('MEM').Create('', shape[1], shape[0], 1, gdal.GDT_Byte)
    t.SetGeoTransform(gt); t.SetProjection(srs.ExportToWkt())
    gdal.RasterizeLayer(t, [1], lyr, burn_values=[1])
    return t.GetRasterBand(1).ReadAsArray().astype(bool)


def river_geoms(buf_m):
    els = json.load(open(f'{BASE}/aux/osm_rivers.json'))
    out = []
    for e in els:
        if e.get('tags', {}).get('name', '') not in FLOOD:
            continue
        g = e.get('geometry') or []
        if len(g) < 2:
            continue
        ln = ogr.Geometry(ogr.wkbLineString)
        for p in g:
            ln.AddPoint_2D(p['lon'], p['lat'])
        out.append(ln.Buffer(buf_m / 111320.))
    return out


def main():
    trk = sys.argv[1]
    det, gt = rd(f'{BASE}/analysis/{trk}/flood_detect.tif')
    det = det > 0
    shape = det.shape
    summ = json.load(open(f'{BASE}/analysis/{trk}/flood_detect.json'))
    px_m2 = abs(gt[1] * gt[5]) * (111320 ** 2) * math.cos(math.radians(28.1))
    px_km2 = px_m2 / 1e6

    # --- 마스크 ---
    src_c, lyr_c = mem_layer(river_geoms(300))
    corridor = burn(lyr_c, gt, shape)
    # 탐지구역 + 200 m 인접
    r = max(1, int(round(200 / math.sqrt(px_m2))))
    det_buf = ndimage.binary_dilation(det, ndimage.generate_binary_structure(2, 2), iterations=r)

    # --- 인구: WorldPop 을 밀도로 변환 후 격자에 맞춤 ---
    wp = gdal.Open(f'{BASE}/aux/npl_worldpop2020.tif')
    wgt = wp.GetGeoTransform()
    wp_px_m2 = abs(wgt[1] * wgt[5]) * (111320 ** 2) * math.cos(math.radians(28.1))
    a = wp.GetRasterBand(1).ReadAsArray().astype(np.float64)
    nd = wp.GetRasterBand(1).GetNoDataValue()
    a[(a == nd) | ~np.isfinite(a)] = 0.0
    dens = a / wp_px_m2                                   # 명/m²
    mem = gdal.GetDriverByName('MEM').Create('', wp.RasterXSize, wp.RasterYSize, 1, gdal.GDT_Float64)
    mem.SetGeoTransform(wgt); mem.SetProjection(wp.GetProjection())
    mem.GetRasterBand(1).WriteArray(dens)
    warped = gdal.Warp('', mem, format='MEM', resampleAlg='bilinear',
                       outputBounds=[gt[0], gt[3] + gt[5] * shape[0], gt[0] + gt[1] * shape[1], gt[3]],
                       width=shape[1], height=shape[0])
    popd = warped.GetRasterBand(1).ReadAsArray()          # 명/m²
    pop = popd * px_m2                                    # 화소당 명
    print(f'WorldPop 2020(UN보정, 93 m) → 30 m 밀도 재배치. 장면 총인구 {pop.sum():,.0f}명\n')

    # --- 행정구역 ---
    adm = json.load(open(f'{BASE}/aux/osm_admin.json'))
    dmask = {}
    for e in adm:
        nm = e.get('tags', {}).get('name:en') or e.get('tags', {}).get('name', '')
        if nm not in DISTRICTS:
            continue
        # relation 멤버 way는 경계선 조각이다. 각각을 폴리곤으로 닫으면 슬리버만 남으므로
        # 전체를 MultiLineString 으로 모아 Polygonize 로 면을 복원한다.
        mls = ogr.Geometry(ogr.wkbMultiLineString)
        for mem_ in e.get('members', []):
            if mem_.get('role') not in (None, '', 'outer'):
                continue
            g = mem_.get('geometry') or []
            if len(g) < 2:
                continue
            ln = ogr.Geometry(ogr.wkbLineString)
            for p in g:
                ln.AddPoint_2D(p['lon'], p['lat'])
            mls.AddGeometry(ln)
        if mls.GetGeometryCount() == 0:
            continue
        poly = mls.Polygonize()
        if poly is None or poly.IsEmpty():
            continue
        polys = [poly.GetGeometryRef(i).Clone() for i in range(poly.GetGeometryCount())] \
                if poly.GetGeometryCount() else [poly]
        s_, l_ = mem_layer(polys)
        dmask[nm] = burn(l_, gt, shape)

    # --- OSM 인프라 ---
    infra = json.load(open(f'{BASE}/aux/osm_infra.json'))
    bcen, roads, places, plants = [], [], [], []
    for e in infra:
        t = e.get('tags', {}); g = e.get('geometry') or []
        if 'building' in t and g:
            bcen.append((sum(p['lon'] for p in g) / len(g), sum(p['lat'] for p in g) / len(g)))
        elif 'highway' in t and len(g) > 1:
            roads.append((t.get('highway'), [(p['lon'], p['lat']) for p in g]))
        elif 'place' in t:
            if e.get('lon') is not None:
                places.append((t.get('name', '?'), t.get('place'), e['lon'], e['lat']))
        elif t.get('power') == 'plant':
            if g:
                plants.append((t.get('name', '?'), sum(p['lon'] for p in g)/len(g), sum(p['lat'] for p in g)/len(g)))
            elif e.get('lon') is not None:
                plants.append((t.get('name', '?'), e['lon'], e['lat']))

    def at(mask, lon, lat):
        c = int((lon - gt[0]) / gt[1]); r_ = int((lat - gt[3]) / gt[5])
        return 0 <= r_ < shape[0] and 0 <= c < shape[1] and mask[r_, c]

    def road_km(mask):
        tot = 0.0
        for hw, pts in roads:
            for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                if at(mask, mx, my):
                    tot += math.hypot((x2 - x1) * 98.0, (y2 - y1) * 111.0)
        return tot

    print('=' * 74)
    print(f'{"":24}{"분석 회랑(300m)":>18}{"탐지 피해구역+200m":>22}')
    print('-' * 74)
    rows = {}
    for lbl, mask in [('분석 회랑(300m)', corridor), ('탐지 피해구역+200m', det_buf & corridor)]:
        rows[lbl] = dict(area_km2=float(mask.sum() * px_km2), pop=float(pop[mask].sum()),
                         bldg=sum(1 for lo, la in bcen if at(mask, lo, la)),
                         road_km=road_km(mask),
                         places=[p for p in places if at(mask, p[2], p[3])],
                         plants=[p for p in plants if at(mask, p[1], p[2])])
    a1, a2 = rows['분석 회랑(300m)'], rows['탐지 피해구역+200m']
    print(f'{"면적":24}{a1["area_km2"]:>16.1f}㎢{a2["area_km2"]:>20.2f}㎢')
    print(f'{"인구 (WorldPop 2020)":24}{a1["pop"]:>15,.0f}명{a2["pop"]:>19,.0f}명')
    print(f'{"건물 (OSM)":24}{a1["bldg"]:>15,}동{a2["bldg"]:>19,}동')
    print(f'{"도로 (OSM)":24}{a1["road_km"]:>15.1f}km{a2["road_km"]:>18.1f}km')
    print(f'{"취락":24}{len(a1["places"]):>15}개{len(a2["places"]):>19}개')
    print(f'{"발전소":24}{len(a1["plants"]):>15}개{len(a2["plants"]):>19}개')
    print('=' * 74)

    print('\n[군(district)별 — 분석 회랑 기준]')
    print(f'{"군":<18}{"회랑㎢":>9}{"회랑인구":>11}{"탐지㎢":>9}{"노출인구":>11}{"건물":>9}')
    print('-' * 68)
    drows = []
    for nm, dm in dmask.items():
        c = corridor & dm; e = det_buf & corridor & dm
        if c.sum() < 10:
            continue
        row = dict(district=nm, corr_km2=float(c.sum()*px_km2), corr_pop=float(pop[c].sum()),
                   det_km2=float(e.sum()*px_km2), det_pop=float(pop[e].sum()),
                   bldg=sum(1 for lo, la in bcen if at(e, lo, la)))
        print(f'{nm:<18}{row["corr_km2"]:>9.1f}{row["corr_pop"]:>11,.0f}'
              f'{row["det_km2"]:>9.2f}{row["det_pop"]:>11,.0f}{row["bldg"]:>9,}')
        drows.append(row)

    print('\n[탐지 피해구역 인근 취락]')
    for nm, kind, lo, la in a2['places'][:20]:
        print(f'   {nm} ({kind})  {la:.4f}N {lo:.4f}E')
    print('\n[탐지 피해구역 인근 발전시설]')
    for p in a2['plants']:
        print(f'   {p[0]}  {p[2]:.4f}N {p[1]:.4f}E')

    out = dict(track=trk, px_km2=px_km2,
               corridor={k: v for k, v in a1.items() if k not in ('places', 'plants')},
               detected={k: v for k, v in a2.items() if k not in ('places', 'plants')},
               corridor_places=len(a1['places']), detected_places=[p[0] for p in a2['places']],
               detected_plants=[p[0] for p in a2['plants']], districts=drows,
               thr_dB=summ['thr_dB'], detect_km2=summ['detect_km2'],
               control_km2=summ['control_km2'], net_km2=summ['net_km2'])
    json.dump(out, open(f'{BASE}/analysis/{trk}/exposure.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nwrote {BASE}/analysis/{trk}/exposure.json')


if __name__ == '__main__':
    main()
