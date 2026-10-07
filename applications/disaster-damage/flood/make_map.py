#!/usr/bin/env python
"""
결맞음 변화 지도 생성 — 2026 네팔 홍수
usage: make_map.py <TRACK>
입력: analysis/<TRACK>/{dcoh,coh_baseline,coh_coevent,loss_mask}.tif
출력: analysis/<TRACK>/dcoh_map.png
"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from osgeo import gdal
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
SITES = [
    ('붕괴원점', 85.5194, 28.2765), ('Rasuwagadhi', 85.3792, 28.2810),
    ('Syabrubesi', 85.3336, 28.1622), ('Dhunche', 85.2971, 28.1004),
    ('Haku Besi', 85.2400, 28.0200), ('Betrawati', 85.1836, 27.9704),
    ('Devighat', 85.1667, 27.8933), ('Bidur', 85.1500, 27.8700),
]
for p in ['/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
          '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
    if os.path.exists(p):
        font_manager.fontManager.addfont(p)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=p).get_name()
        break
plt.rcParams['axes.unicode_minus'] = False


def rd(p):
    ds = gdal.Open(p)
    return ds.GetRasterBand(1).ReadAsArray(), ds.GetGeoTransform()


def extent(gt, shp):
    return [gt[0], gt[0] + gt[1] * shp[1], gt[3] + gt[5] * shp[0], gt[3]]


def main():
    trk = sys.argv[1]
    d = f'{BASE}/analysis/{trk}'
    dcoh, gt = rd(f'{d}/dcoh.tif')
    cb, _ = rd(f'{d}/coh_baseline.tif')
    cc, _ = rd(f'{d}/coh_coevent.tif')
    summ = json.load(open(f'{d}/summary.json'))
    ext = extent(gt, dcoh.shape)

    fig, axes = plt.subplots(1, 3, figsize=(19, 8), constrained_layout=True)
    for ax, arr, ttl, cmap, vlim in [
            (axes[0], cb, f"기준 결맞음\n{summ['baseline_pair']} (정상 12일)", 'viridis', (0, 1)),
            (axes[1], cc, f"사건 결맞음\n{summ['coevent_pair']} (홍수 포함)", 'viridis', (0, 1)),
            (axes[2], dcoh, 'Δ 결맞음 (사건 − 기준)\n음(붉음) = 사건에 의한 탈결맞음', 'RdBu', (-0.6, 0.6))]:
        im = ax.imshow(arr, extent=ext, origin='upper', cmap=cmap, vmin=vlim[0], vmax=vlim[1])
        ax.set_title(ttl, fontsize=12)
        ax.set_xlabel('경도'); ax.set_ylabel('위도')
        for nm, lo, la in SITES:
            if ext[0] <= lo <= ext[1] and ext[2] <= la <= ext[3]:
                ax.plot(lo, la, 'k^', ms=6, mfc='yellow', mew=1.0)
                ax.annotate(nm, (lo, la), fontsize=8, xytext=(4, 3),
                            textcoords='offset points', color='k',
                            bbox=dict(fc='white', alpha=.6, pad=.8, lw=0))
        fig.colorbar(im, ax=ax, shrink=.75)
    fig.suptitle(f'2026 네팔 홍수 결맞음 변화 탐지 — {trk} (Sentinel-1D, VV)\n'
                 f"유의저하 {summ['loss_km2']:.2f} km² (Δcoh ≤ {summ['drop_thresh']}, "
                 f"기준결맞음 ≥ {summ['coh_min']})", fontsize=13)
    out = f'{d}/dcoh_map.png'
    fig.savefig(out, dpi=130)
    print('wrote', out)


if __name__ == '__main__':
    main()
