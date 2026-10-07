#!/usr/bin/env python
"""카드뉴스 보조 그래픽: 구간별 막대차트 + 네팔 위치도. usage: render_extras.py <TRACK>"""
import os, sys, json, math, io, urllib.request, concurrent.futures as cf
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image, ImageDraw

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
CARDS = f'{BASE}/analysis/cards'
FP = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
font_manager.fontManager.addfont(FP)
plt.rcParams['font.family'] = font_manager.FontProperties(fname=FP).get_name()
plt.rcParams['axes.unicode_minus'] = False
BG = '#181d25'
TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'


def deg2num(lon, lat, z):
    n = 2.0 ** z
    return (lon + 180.0) / 360.0 * n, (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n


def fetch(z, x, y):
    try:
        req = urllib.request.Request(TILE.format(z=z, x=x, y=y), headers={'User-Agent': 'Mozilla/5.0'})
        return Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=25).read())).convert('RGB')
    except Exception:
        return Image.new('RGB', (256, 256), (35, 42, 50))


def locmap(W, S, E, N, z, box, size):
    x0f, y0f = deg2num(W, N, z); x1f, y1f = deg2num(E, S, z)
    x0, y0, x1, y1 = int(x0f), int(y0f), math.ceil(x1f), math.ceil(y1f)
    cv = Image.new('RGB', ((x1 - x0) * 256, (y1 - y0) * 256))
    jobs = [(xx, yy) for yy in range(y0, y1) for xx in range(x0, x1)]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for (xx, yy), im in zip(jobs, ex.map(lambda t: fetch(z, t[0], t[1]), jobs)):
            cv.paste(im, ((xx - x0) * 256, (yy - y0) * 256))
    cv = cv.crop((int((x0f - x0) * 256), int((y0f - y0) * 256),
                  int((x1f - x0) * 256), int((y1f - y0) * 256)))
    d = ImageDraw.Draw(cv)
    bx0 = (box[0] - W) / (E - W) * cv.width; bx1 = (box[2] - W) / (E - W) * cv.width
    by0 = (N - box[3]) / (N - S) * cv.height; by1 = (N - box[1]) / (N - S) * cv.height
    d.rectangle([bx0 - 2, by0 - 2, bx1 + 2, by1 + 2], outline=(255, 60, 45), width=5)
    return cv.resize(size, Image.LANCZOS)


def main():
    trk = sys.argv[1]
    det = json.load(open(f'{BASE}/analysis/{trk}/flood_detect.json'))

    # ---- 구간별 막대차트 ----
    rows = [r for r in det['reaches']]
    names = [r['reach'] for r in rows]
    dv = [r['detect_km2'] * 100 for r in rows]
    cv_ = [r['control_km2'] * 100 for r in rows]
    fig, ax = plt.subplots(figsize=(13.2, 3.7), facecolor=BG)
    ax.set_facecolor(BG)
    y = np.arange(len(names))[::-1]
    ax.barh(y + 0.19, dv, height=.38, color='#ff4c3c', label='사건 쌍 (홍수 포함)')
    ax.barh(y - 0.19, cv_, height=.38, color='#5a6675', label='대조 쌍 (정상 12일)')
    for i, (a, b) in enumerate(zip(dv, cv_)):
        ax.text(a + .3, y[i] + 0.19, f'{a:.1f} ha', va='center', color='#ff8078', fontsize=13)
        r = a / b if b > 0 else float('inf')
        ax.text(max(a, b) + 3.2, y[i], ('≥50x' if not np.isfinite(r) else f'{r:.0f}x'),
                va='center', color='#ffc43c', fontsize=14, fontweight='bold')
    ax.set_yticks(y); ax.set_yticklabels(names, color='#e6eaf0', fontsize=14)
    ax.set_xlabel('탐지 면적 (ha)  ·  상류 → 하류', color='#a8b0bc', fontsize=13)
    ax.tick_params(colors='#a8b0bc')
    for s in ax.spines.values():
        s.set_color('#4a5462')
    ax.legend(facecolor=BG, edgecolor='#4a5462', labelcolor='#e6eaf0', fontsize=13, loc='lower right')
    ax.set_title('구간별 탐지 면적 — 대조군과 비교 (노란 수치 = 배수)',
                 color='#ffc43c', fontsize=17, loc='left', pad=12)
    ax.grid(axis='x', color='#333c48', lw=.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(f'{CARDS}/reach_chart.png', dpi=155, facecolor=BG)
    print('wrote reach_chart.png')

    # ---- 위치도 ----
    im = locmap(84.00, 27.10, 86.50, 29.30, 10, (85.085, 27.82, 85.56, 28.40), (1200, 1193))
    im.save(f'{CARDS}/locmap.png')
    print('wrote locmap.png')


if __name__ == '__main__':
    main()
