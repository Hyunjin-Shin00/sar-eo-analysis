#!/usr/bin/env python
"""탐지 결과 지도 + 주요 군집 좌표. usage: flood_map.py <TRACK>"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from scipy import ndimage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from osgeo import gdal
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
SITES = [('붕괴원점', 85.5194, 28.2765), ('Rasuwagadhi', 85.3792, 28.2810),
         ('Syabrubesi', 85.3336, 28.1622), ('Dhunche', 85.2971, 28.1004),
         ('Haku Besi', 85.2400, 28.0200), ('Betrawati', 85.1836, 27.9704),
         ('Devighat', 85.1667, 27.8933), ('Bidur', 85.1500, 27.8700)]
for p in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
    if os.path.exists(p):
        font_manager.fontManager.addfont(p)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=p).get_name()
plt.rcParams['axes.unicode_minus'] = False


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def main():
    trk = sys.argv[1]
    d = f'{BASE}/analysis/{trk}'
    det, gt = rd(f'{d}/flood_detect.tif')
    chg, _ = rd(f'{d}/db_change.tif')
    summ = json.load(open(f'{d}/flood_detect.json'))
    det = det > 0
    ext = [gt[0], gt[0] + gt[1] * det.shape[1], gt[3] + gt[5] * det.shape[0], gt[3]]
    px_km2 = abs(gt[1] * gt[5]) * (111320 ** 2) * np.cos(np.deg2rad(28.1)) / 1e6

    # 주요 군집 좌표
    lab, n = ndimage.label(det, structure=np.ones((3, 3)))
    sz = np.bincount(lab.ravel()); sz[0] = 0
    order = np.argsort(-sz)[:12]
    print(f'{"순위":>3}{"면적(ha)":>10}{"중심 위도":>11}{"중심 경도":>11}{"평균변화":>10}   최근접 지점')
    print('-' * 74)
    rows = []
    for i, l in enumerate(order, 1):
        if sz[l] == 0:
            break
        ys, xs = np.where(lab == l)
        la = gt[3] + gt[5] * ys.mean(); lo = gt[0] + gt[1] * xs.mean()
        near = min(SITES, key=lambda s: (s[1] - lo) ** 2 + (s[2] - la) ** 2)
        dist = np.hypot((near[1] - lo) * 98, (near[2] - la) * 111)
        print(f'{i:>3}{sz[l]*px_km2*100:>10.2f}{la:>11.4f}{lo:>11.4f}'
              f'{np.nanmean(chg[lab == l]):>9.1f}dB   {near[0]} ({dist:.1f} km)')
        rows.append(dict(rank=i, ha=float(sz[l]*px_km2*100), lat=float(la), lon=float(lo),
                         mean_dB=float(np.nanmean(chg[lab == l])),
                         nearest=near[0], dist_km=float(dist)))
    json.dump(rows, open(f'{d}/flood_clusters.json', 'w'), ensure_ascii=False, indent=1)

    fig, axes = plt.subplots(1, 2, figsize=(16, 9), constrained_layout=True)
    im = axes[0].imshow(chg, extent=ext, origin='upper', cmap='RdBu_r', vmin=-8, vmax=8)
    axes[0].set_title(f'후방산란 변화 (0816→0828, dB)\n붉음 = 감소', fontsize=12)
    fig.colorbar(im, ax=axes[0], shrink=.6, label='dB')

    axes[1].imshow(np.where(np.isfinite(chg), 0.85, np.nan), extent=ext, origin='upper',
                   cmap='gray', vmin=0, vmax=1)
    ys, xs = np.where(det)
    axes[1].scatter(gt[0] + gt[1] * xs, gt[3] + gt[5] * ys, s=6, c='red', marker='s', linewidths=0)
    axes[1].set_title(f'탐지 구역 (≤{summ["thr_dB"]:.0f} dB, 군집≥5화소)\n'
                      f'순 {summ["net_km2"]*100:.1f} ha, 대조군 대비 '
                      f'{summ["detect_km2"]/max(summ["control_km2"],1e-9):.0f}배', fontsize=12)
    for ax in axes:
        ax.set_xlabel('경도'); ax.set_ylabel('위도')
        ax.set_xlim(85.08, 85.45); ax.set_ylim(27.85, 28.35)
        for nm, lo, la in SITES:
            ax.plot(lo, la, '^', ms=7, mfc='yellow', mec='k', mew=.8)
            ax.annotate(nm, (lo, la), fontsize=8, xytext=(5, 3), textcoords='offset points',
                        bbox=dict(fc='white', alpha=.65, pad=.8, lw=0))
    fig.suptitle('2026 네팔 홍수 — Sentinel-1D ASC 후방산란 감소 기반 피해구역 탐지', fontsize=13)
    out = f'{d}/flood_map.png'
    fig.savefig(out, dpi=130)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
