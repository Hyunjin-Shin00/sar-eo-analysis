#!/usr/bin/env python
"""
날짜별 후방산란(dB)을 간섭도와 같은 레이더 격자로 만들고 ISCE 메타데이터를 붙인다.
이후 geocodeIsce.py 로 지오코딩하면 GRD와 기능적으로 동등한 지오코딩 강도영상이 된다.

주의: SLC 진폭 DN이라 절대 sigma0 보정은 되어 있지 않다. 같은 궤도·같은 처리이므로
날짜 간 '차이'에는 보정상수가 상쇄되어 영향이 없다. 절대 dB 임계값을 쓸 때만
보정 부재를 감안해야 한다.

usage: db_geocode.py <TRACK> <date> [<date> ...]
"""
import os, sys, re
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')


def looks_int(path, rl, al):
    ds = gdal.Open(path)
    nx, ny = ds.RasterXSize, ds.RasterYSize
    ny2, nx2 = ny - ny % al, nx - nx % rl
    out = np.zeros((ny2 // al, nx2 // rl), np.float32)
    step = al * 200
    for y0 in range(0, ny2, step):
        h = min(step, ny2 - y0)
        a = ds.GetRasterBand(1).ReadAsArray(0, y0, nx2, h)
        p = (np.abs(a) ** 2).astype(np.float32)
        out[y0 // al: y0 // al + h // al] = p.reshape(h // al, al, nx2 // rl, rl).mean(axis=(1, 3))
    ds = None
    return out


def main():
    trk, dates = sys.argv[1], sys.argv[2:]
    work = f'{BASE}/work/stack_{trk}'
    cfg = [f for f in os.listdir(f'{work}/configs') if f.startswith('config_merge_igram_')][0]
    txt = open(f'{work}/configs/{cfg}').read()
    rl = int(re.search(r'range_looks\s*:\s*(\d+)', txt).group(1))
    al = int(re.search(r'azimuth_looks\s*:\s*(\d+)', txt).group(1))

    ref = f'{work}/merged/interferograms'
    pair = sorted(os.listdir(ref))[0]
    cor = f'{ref}/{pair}/filt_fine.cor'
    ds = gdal.Open(cor); NX, NY = ds.RasterXSize, ds.RasterYSize; ds = None
    print(f'looks {rl}x{al}, 격자 {NX}x{NY}')

    for d in dates:
        I = looks_int(f'{work}/merged/SLC/{d}/{d}.slc.full.vrt', rl, al)
        ny, nx = min(I.shape[0], NY), min(I.shape[1], NX)
        out = np.zeros((NY, NX), np.float32)
        sub = I[:ny, :nx]
        ok = sub > 1e-12
        out[:ny, :nx] = np.where(ok, 10 * np.log10(sub + 1e-12), 0)
        name = f'db_{d}'
        p = f'{ref}/{pair}/{name}'
        out.tofile(p)
        for ext in ('.xml', '.vrt'):
            open(p + ext, 'w').write(open(cor + ext).read().replace('filt_fine.cor', name))
        print(f'  {d}: 유효 {100*ok.mean():.1f}%  dB 5/50/95% = {np.percentile(out[:ny,:nx][ok],[5,50,95]).round(2)}  -> {name}')


if __name__ == '__main__':
    main()
