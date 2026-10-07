#!/usr/bin/env python
"""
NRSC/ISRO(Charter Call 1209 AOI-02)가 지목한 인프라 피해가 우리 SAR에서 보이는지 검증.
대상: Trishuli 수력 댐, Bhainse Aama 신교 (좌표는 NRSC 도엽 경위선에서 환산).
카드뉴스 PNG는 수정하지 않고 별도 그림으로만 저장한다.
usage: nrsc_check.py <TRACK>
"""
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
from matplotlib.patches import Circle
from osgeo import gdal
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
FP = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
font_manager.fontManager.addfont(FP)
plt.rcParams['font.family'] = font_manager.FontProperties(fname=FP).get_name()
plt.rcParams['axes.unicode_minus'] = False

FEAT = [('Trishuli 수력 댐', 85.1711, 27.9629),
        ('Bhainse Aama 신교', 85.1756, 27.9636)]
# NRSC 도엽 범위(경위선 환산) + 판독 여유
W, E = 85.1620, 85.1810
S, N = 27.9560, 27.9710


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def crop(a, gt):
    c0 = int((W - gt[0]) / gt[1]); c1 = int((E - gt[0]) / gt[1])
    r0 = int((N - gt[3]) / gt[5]); r1 = int((S - gt[3]) / gt[5])
    return a[r0:r1, c0:c1]


def main():
    trk = sys.argv[1]
    D = f'{BASE}/work/stack_{trk}/merged/interferograms/20260804_20260816'
    d16, gt = rd(f'{D}/db_20260816.geo')
    d28, _ = rd(f'{D}/db_20260828.geo')
    d04, _ = rd(f'{D}/db_20260804.geo')
    det, _ = rd(f'{BASE}/analysis/{trk}/flood_detect.tif')
    a16, a28, a04 = crop(d16, gt), crop(d28, gt), crop(d04, gt)
    dm = crop(det, gt) > 0
    ok = (a16 != 0) & (a28 != 0) & (a04 != 0)
    co = np.where(ok, a28 - a16, np.nan)
    bs = np.where(ok, a16 - a04, np.nan)
    ext = [W, E, S, N]
    lo, hi = np.nanpercentile(np.concatenate([a16[ok], a28[ok]]), [2, 98])

    fig, ax = plt.subplots(1, 4, figsize=(23, 5.6), facecolor='#12151a')
    panels = [(a16, '사건 전  2026-08-16 (SAR 강도)', 'gray', (lo, hi)),
              (a28, '사건 후  2026-08-28 (SAR 강도)', 'gray', (lo, hi)),
              (co, '후방산란 변화 (사건쌍)  붉음=감소', 'RdBu', (-10, 10)),
              (bs, '후방산란 변화 (대조쌍, 정상 12일)  붉음=감소', 'RdBu', (-10, 10))]
    for i, (arr, ttl, cm, vl) in enumerate(panels):
        A = ax[i]
        A.set_facecolor('#12151a')
        im = A.imshow(np.where(ok, arr, np.nan), extent=ext, origin='upper',
                      cmap=cm, vmin=vl[0], vmax=vl[1], interpolation='nearest')
        if i == 1:
            ys, xs = np.where(dm)
            if len(ys):
                A.scatter(W + (xs + .5) * (E - W) / dm.shape[1],
                          N - (ys + .5) * (N - S) / dm.shape[0],
                          s=95, marker='s', facecolors='none', edgecolors='#ff3b30', linewidths=1.6,
                          label='SAR 탐지 화소')
                A.legend(loc='lower left', fontsize=9, facecolor='#12151a',
                         edgecolor='#4a5462', labelcolor='w')
        for nm, flo, fla in FEAT:
            A.add_patch(Circle((flo, fla), 0.0013, fill=False, ec='#ffd23c', lw=2.2))
            A.annotate(nm, (flo, fla), xytext=(0, 15), textcoords='offset points',
                       color='#ffd23c', fontsize=10, ha='center',
                       bbox=dict(fc='#000000cc', ec='none', pad=1.6))
        A.set_title(ttl, color='#e8ecf2', fontsize=12)
        A.tick_params(colors='#98a2b0', labelsize=8)
        for s in A.spines.values():
            s.set_color('#4a5462')
        if i >= 2:
            fig.colorbar(im, ax=A, shrink=.72, label='dB')
    fig.suptitle('NRSC/ISRO 지목 인프라 피해가 SAR에서 보이는가 — Trishuli 수력 댐 · Bhainse Aama 신교\n'
                 'Sentinel-1D ASC · 30 m 격자 (원의 반지름 약 140 m)',
                 color='#ffd23c', fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.88])
    out = f'{BASE}/analysis/nrsc_infra_check.png'
    fig.savefig(out, dpi=140, facecolor='#12151a')
    print('wrote', out)

    # 수치 요약
    px_m = 29.0
    print(f'\n{"대상":<20}{"최근접 탐지":>12}{"120m내 최저":>13}{"120m내 대조 최저":>17}')
    print('-' * 64)
    res = []
    for nm, flo, fla in FEAT:
        c = int((flo - gt[0]) / gt[1]); r = int((fla - gt[3]) / gt[5])
        w = max(1, int(round(120 / px_m)))
        sl = (slice(r - w, r + w + 1), slice(c - w, c + w + 1))
        m = (d16[sl] != 0) & (d28[sl] != 0) & (d04[sl] != 0)
        cmin = float((d28[sl] - d16[sl])[m].min()); bmin = float((d16[sl] - d04[sl])[m].min())
        ys, xs = np.where(det > 0)
        dist = np.hypot((gt[0] + gt[1] * xs - flo) * 98.3, (gt[3] + gt[5] * ys - fla) * 110.9)
        dmin = float(dist.min() * 1000)
        print(f'{nm:<20}{dmin:>10.0f} m{cmin:>11.1f} dB{bmin:>15.1f} dB')
        res.append(dict(name=nm, lon=flo, lat=fla, nearest_detect_m=dmin,
                        coevent_min_dB=cmin, baseline_min_dB=bmin))
    json.dump(res, open(f'{BASE}/analysis/nrsc_infra_check.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
