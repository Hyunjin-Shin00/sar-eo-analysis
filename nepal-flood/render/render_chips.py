#!/usr/bin/env python
"""
카드뉴스용 SAR 전/후 영상 칩 + 변화 칩 렌더링.
지오코딩된 dB 영상을 그대로 쓰므로 '실제 SAR 영상'이다(합성/모식도 아님).
usage: render_chips.py <TRACK>
"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from osgeo import gdal
from PIL import Image
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
OUT = f'{BASE}/analysis/cards'
os.makedirs(OUT, exist_ok=True)

# (키, 표시명, 중심lon, 중심lat, 폭(도))
ZOOMS = [
    ('source',      '빙하 붕괴 원점 (해발 4,900 m)', 85.5252, 28.2853, 0.034),
    ('rasuwagadhi', 'Rasuwagadhi · Timure (국경)', 85.3790, 28.2790, 0.030),
    ('betrawati',   'Betrawati ~ Devighat',        85.1620, 27.9450, 0.075),
    ('bidur',       'Bidur (Nuwakot)',               85.1050, 27.8680, 0.036),
    ('nrsc',        'NRSC 지목 인프라 (Trishuli 댐 · Bhainse 교)', 85.1733, 27.9632, 0.020),
]


def rd(p):
    ds = gdal.Open(p); a = ds.GetRasterBand(1).ReadAsArray(); gt = ds.GetGeoTransform(); ds = None
    return a, gt


def crop(a, gt, lon, lat, w_deg, h_deg):
    c0 = int((lon - w_deg / 2 - gt[0]) / gt[1]); c1 = int((lon + w_deg / 2 - gt[0]) / gt[1])
    r0 = int((lat + h_deg / 2 - gt[3]) / gt[5]); r1 = int((lat - h_deg / 2 - gt[3]) / gt[5])
    r0, r1 = max(0, r0), min(a.shape[0], r1)
    c0, c1 = max(0, c0), min(a.shape[1], c1)
    return a[r0:r1, c0:c1], (r0, r1, c0, c1)


def to_img(db, lo, hi, size):
    """dB → 8bit 그레이스케일 이미지(확대)."""
    v = np.clip((db - lo) / (hi - lo), 0, 1)
    v[~np.isfinite(db) | (db == 0)] = 0
    im = Image.fromarray((v * 255).astype(np.uint8), 'L').convert('RGB')
    return im.resize(size, Image.LANCZOS)


def main():
    trk = sys.argv[1]
    D = f'{BASE}/work/stack_{trk}/merged/interferograms/20260804_20260816'
    d16, gt = rd(f'{D}/db_20260816.geo')
    d28, _ = rd(f'{D}/db_20260828.geo')
    det, _ = rd(f'{BASE}/analysis/{trk}/flood_detect.tif')
    det = det > 0
    # 붕괴 원점 흔적은 하천 버퍼 밖이라 flood_detect 에 없다. 별도 마스크를 합쳐 표시.
    sp = f'{BASE}/analysis/{trk}/source_scar.tif'
    if os.path.exists(sp):
        sc_, _ = rd(sp)
        det = det | (sc_ > 0)

    meta = {}
    for key, label, lon, lat, w in ZOOMS:
        h = w * 0.85
        a16, _ = crop(d16, gt, lon, lat, w, h)
        a28, _ = crop(d28, gt, lon, lat, w, h)
        dm, _ = crop(det.astype(np.float32), gt, lon, lat, w, h)
        ok = np.isfinite(a16) & (a16 != 0) & np.isfinite(a28) & (a28 != 0)
        if ok.sum() < 100:
            print(f'  {key}: 유효화소 부족'); continue
        lo, hi = np.percentile(np.concatenate([a16[ok], a28[ok]]), [2, 98])
        H = 900; W = int(H * a16.shape[1] / a16.shape[0])
        im16 = to_img(a16, lo, hi, (W, H))
        im28 = to_img(a28, lo, hi, (W, H))
        # 사후영상에 탐지구역 빨강 오버레이
        ov = np.array(im28).copy()
        dmi = np.array(Image.fromarray((dm * 255).astype(np.uint8), 'L').resize((W, H), Image.NEAREST)) > 127
        ov[dmi] = (0.35 * ov[dmi] + 0.65 * np.array([255, 40, 40])).astype(np.uint8)
        # 변화 dB 칩 — 원자료는 스펙클이 심해 판독이 어려우므로 표시용으로만 3x3 중앙값 평활.
        # (탐지 자체는 평활 없는 원자료 + 연결성분 필터로 수행했다)
        from scipy import ndimage as _nd
        ch = np.where(ok, a28 - a16, np.nan)
        filled = np.where(np.isfinite(ch), ch, 0.0)
        ch = np.where(ok, _nd.median_filter(filled, size=3), np.nan)
        cimg = np.zeros((*ch.shape, 3), np.uint8)
        neg = np.clip(-ch / 8.0, 0, 1); pos = np.clip(ch / 8.0, 0, 1)
        base = np.where(np.isfinite(ch), 235, 0)
        cimg[..., 0] = np.where(np.isfinite(ch), base - (pos * 180), 0)
        cimg[..., 1] = np.where(np.isfinite(ch), base - (pos * 60) - (neg * 190), 0)
        cimg[..., 2] = np.where(np.isfinite(ch), base - (neg * 190), 0)
        cim = Image.fromarray(cimg).resize((W, H), Image.LANCZOS)

        for nm, im in [('pre', im16), ('post', im28), ('post_ov', Image.fromarray(ov)), ('chg', cim)]:
            im.save(f'{OUT}/{key}_{nm}.png')
        meta[key] = dict(label=label, lon=lon, lat=lat, w_deg=w, h_deg=h,
                         px=[W, H], km_w=w * 98.0, det_px=int(dmi.sum()),
                         db_lo=float(lo), db_hi=float(hi))
        print(f'  {key:14s} {label:28s} {W}x{H}  폭 {w*98:.1f}km  dB {lo:.1f}~{hi:.1f}')
    json.dump(meta, open(f'{OUT}/chips.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nwrote {OUT}/*.png, chips.json')


if __name__ == '__main__':
    main()
