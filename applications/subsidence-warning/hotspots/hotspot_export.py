#!/usr/bin/env python3
"""핫스팟 → 과거 사고 대조 + shp/GeoTIFF 출력 + 지도."""
import json
import sys

import numpy as np
import pandas as pd
from scipy import ndimage

sys.path.insert(0, '<DATA_ROOT>/CSK_PSInSAR/code')
from compare_all import CSK
from hotspots import CELL_M, K_SIGMA, MIN_CELLS, MPD_LAT, MPD_LON, rsigma

ACC = ('<WORK_ROOT>/CLAB/auxiliary/subsidence_list/'
       'subsidence_accidents_geocoded_update.csv')
H = json.load(open(f'{CSK}/results/compare/hotspots.json'))
G = np.load(f'{CSK}/results/compare/hotspot_grids.npz')
R1, RC, G1, lab = G['R1'], G['RC'], G['G1'], G['lab']
lo0, la0 = float(G['lo0']), float(G['la0'])
ny, nx = R1.shape
thr = -K_SIGMA * rsigma(R1)

# ---------------------------------------------------------------- 사고 대조
a = pd.read_csv(ACC, encoding='utf-8-sig')
a = a[a['siDo'].astype(str).str.contains('서울', na=False)].dropna(subset=['lat', 'lon'])
a = a[a.lat.between(37.4, 37.72) & a.lon.between(126.75, 127.2)].copy()
a['dt'] = pd.to_datetime(a['sagoDate'].astype(str), format='%Y%m%d', errors='coerce')
a = a[a['geocodeType'].isin(['parcel', 'road'])]        # 동 단위는 위치오차 커서 제외
ai = ((a.lon - lo0) * MPD_LON / CELL_M).astype(int)
aj = ((a.lat - la0) * MPD_LAT / CELL_M).astype(int)
ok = (ai >= 0) & (ai < nx) & (aj >= 0) & (aj < ny)
a, ai, aj = a[ok], ai[ok], aj[ok]
a['anom'] = R1[aj, ai]
a = a[np.isfinite(a['anom'])]
obs = a[a.dt >= '2023-09-09']                            # S1 관측기간 내·이후
allv = R1[np.isfinite(R1)]
print(f'[사고] 서울 번지/도로 지오코딩 {len(a)}건 (격자 유효), 관측기간내 {len(obs)}건')
for tag, s in (('전체', a), ('2023-09 이후', obs)):
    if len(s) < 5:
        continue
    pct = float((allv < s['anom'].mean()).mean() * 100)
    rng = np.random.default_rng(1)
    null = np.array([rng.choice(allv, len(s)).mean() for _ in range(2000)])
    p = float((null <= s['anom'].mean()).mean())
    print(f'   {tag:12s} n={len(s):3d} 평균 이상값 {s["anom"].mean():+.3f} '
          f'vs 전역 {allv.mean():+.3f} → 무작위대비 p={p:.3f}')
# 핫스팟 폴리곤 안에 떨어진 사고 수
_l, _n = ndimage.label(np.isfinite(R1) & (R1 <= thr), structure=np.ones((3, 3)))
_sz = np.bincount(_l.ravel())
_big = np.isin(_l, np.nonzero(_sz >= MIN_CELLS)[0][1:])
inhot = int(_big[aj.values, ai.values].sum())
exp_hot = float(_big.sum()) / float(np.isfinite(R1).sum()) * len(a)
print(f'   핫스팟 폴리곤 내 사고 {inhot}건 (면적비 기대 {exp_hot:.1f}건)')
H['accident_check'] = dict(n_seoul=len(a), n_in_window=len(obs),
                           mean_anom_all=round(float(a['anom'].mean()), 3),
                           mean_anom_window=round(float(obs['anom'].mean()), 3),
                           mean_anom_global=round(float(allv.mean()), 3),
                           n_in_hotspot=inhot, n_expected=round(exp_hot, 1),
                           note='사고기록 대다수가 하수관 손상 등 수 m 규모 공동이라 100 m 격자에서 보이지 않음')

# 핫스팟별 최근접 사고
kx = lambda lo, la: np.column_stack([lo * MPD_LON, la * MPD_LAT])
from scipy.spatial import cKDTree
tree = cKDTree(kx(a.lon.values, a.lat.values))
for h in H['hotspots']:
    d, i = tree.query(kx(np.array([h['lon']]), np.array([h['lat']]))[0])
    r = a.iloc[i]
    h['acc_dist_m'] = int(d)
    h['acc_date'] = str(r['dt'].date()) if pd.notna(r['dt']) else None
    h['acc_reason'] = str(r['sagoReason'])

# ---------------------------------------------------------------- shp 출력
from osgeo import ogr, osr
srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
drv = ogr.GetDriverByName('ESRI Shapefile')
outp = f'{CSK}/results/gis/seoul_hotspots.shp'
import os
if os.path.exists(outp):
    drv.DeleteDataSource(outp)
ds = drv.CreateDataSource(outp)
ly = ds.CreateLayer('hotspots', srs, ogr.wkbPolygon, options=['ENCODING=UTF-8'])
flds = [('id', ogr.OFTInteger), ('gu', ogr.OFTString), ('area_km2', ogr.OFTReal),
        ('s1_anom', ogr.OFTReal), ('s1_min', ogr.OFTReal), ('s1_abs', ogr.OFTReal),
        ('odd', ogr.OFTReal), ('even', ogr.OFTReal), ('t', ogr.OFTReal),
        ('n_ps', ogr.OFTInteger), ('csk_anom', ogr.OFTReal), ('confirm', ogr.OFTInteger),
        ('acc_dist_m', ogr.OFTInteger), ('acc_date', ogr.OFTString),
        ('acc_reason', ogr.OFTString)]
for nmf, tp in flds:
    fd = ogr.FieldDefn(nmf, tp)
    if tp == ogr.OFTString:
        fd.SetWidth(40)
    ly.CreateField(fd)
l2, nl = ndimage.label(np.isfinite(R1) & (R1 <= thr), structure=np.ones((3, 3)))
cent = {}
for i in range(1, nl + 1):
    mk = l2 == i
    if mk.sum() < MIN_CELLS:
        continue
    yy, xx = np.nonzero(mk)
    cent[i] = (lo0 + (xx.mean() + .5) * CELL_M / MPD_LON,
               la0 + (yy.mean() + .5) * CELL_M / MPD_LAT, mk)
dlo, dla = CELL_M / MPD_LON, CELL_M / MPD_LAT
for h in H['hotspots']:
    b = min(cent, key=lambda i: (cent[i][0] - h['lon']) ** 2 + (cent[i][1] - h['lat']) ** 2)
    mk = cent[b][2]
    multi = ogr.Geometry(ogr.wkbMultiPolygon)
    for yy, xx in zip(*np.nonzero(mk)):
        r = ogr.Geometry(ogr.wkbLinearRing)
        x0, y0 = lo0 + xx * dlo, la0 + yy * dla
        for px, py in ((x0, y0), (x0 + dlo, y0), (x0 + dlo, y0 + dla), (x0, y0 + dla), (x0, y0)):
            r.AddPoint_2D(px, py)
        pg = ogr.Geometry(ogr.wkbPolygon); pg.AddGeometry(r)
        multi.AddGeometry(pg)
    g = multi.UnionCascaded()
    f = ogr.Feature(ly.GetLayerDefn())
    for nmf, _ in flds:
        v = h.get(nmf)
        if v is not None:
            f.SetField(nmf, int(v) if nmf in ('confirm',) else v)
    f.SetGeometry(g); ly.CreateFeature(f); f = None
ds = None
print(f'[shp] {outp}  {len(H["hotspots"])}개 폴리곤')

# ---------------------------------------------------------------- GeoTIFF
from osgeo import gdal
tif = f'{CSK}/results/gis/seoul_S1_local_anomaly_mmyr.tif'
dst = gdal.GetDriverByName('GTiff').Create(tif, nx, ny, 1, gdal.GDT_Float32,
                                           ['COMPRESS=DEFLATE', 'TILED=YES'])
dst.SetGeoTransform((lo0, dlo, 0, la0 + ny * dla, 0, -dla))
dst.SetProjection(srs.ExportToWkt())
dst.GetRasterBand(1).WriteArray(np.flipud(R1)); dst.GetRasterBand(1).SetNoDataValue(np.nan)
dst = None
print(f'[tif] {tif}')
json.dump(H, open(f'{CSK}/results/compare/hotspots.json', 'w'), ensure_ascii=False, indent=1)

# ---------------------------------------------------------------- 지도
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
for fp in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
           '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'):
    if os.path.exists(fp):
        font_manager.fontManager.addfont(fp)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=fp).get_name()
        break
plt.rcParams['axes.unicode_minus'] = False
gu = json.load(open(f'{CSK}/aux/seoul_municipalities_geo.json'))
ext = [lo0, lo0 + nx * dlo, la0, la0 + ny * dla]
fig, ax = plt.subplots(1, 2, figsize=(21, 9.5))
for k, (A, ttl, vm) in enumerate([
        (R1, 'S1 PS secular 국지이상 (평면추세 제거)', 2.0),
        (R1, f'핫스팟 {len(H["hotspots"])}개 + 과거 지반침하 사고', 2.0)]):
    im = ax[k].imshow(A, origin='lower', extent=ext, cmap='RdYlBu_r' if k == 0 else 'Greys_r',
                      vmin=-vm, vmax=vm, interpolation='nearest')
    for ft in gu['features']:
        g = ft['geometry']
        rings = ([g['coordinates'][0]] if g['type'] == 'Polygon'
                 else [p[0] for p in g['coordinates']])
        for r in rings:
            r = np.asarray(r)
            ax[k].plot(r[:, 0], r[:, 1], '-', c='0.25', lw=.6, zorder=3)
    ax[k].set_title(ttl, fontsize=14)
    ax[k].set_xlim(ext[0], ext[1]); ax[k].set_ylim(ext[2], ext[3])
    ax[k].set_aspect(1 / np.cos(np.radians(37.55)))
    plt.colorbar(im, ax=ax[k], shrink=.8, label='mm/yr (음수=침하)')
ax[1].scatter(a.lon, a.lat, s=14, c='#1f77b4', alpha=.55, lw=0, label=f'사고 {len(a)}건', zorder=4)
for h in H['hotspots']:
    ax[1].plot(h['lon'], h['lat'], 'o', mfc='none', mec='#d62728', mew=2, ms=13, zorder=5)
    ax[1].text(h['lon'] + .004, h['lat'], str(h['id']), color='#d62728',
               fontsize=9, fontweight='bold', va='center', zorder=6)
ax[1].legend(loc='lower right', fontsize=11)
fig.suptitle('서울시 국지 침하 핫스팟 — Sentinel-1 PS secular, 2023-09 ~ 2026-04',
             fontsize=16, y=.98)
fig.tight_layout(rect=[0, 0, 1, .96])
fig.savefig(f'{CSK}/results/maps/fig7_hotspots.png', dpi=135)
print(f'[map] {CSK}/results/maps/fig7_hotspots.png')
