#!/usr/bin/env python3
"""Crop the existing Sentinel-1 coregistered stack to the Seoul window.

The topsStack run under CLAB already coregistered 196 scenes to master 20220902,
so only the Seoul sub-window is copied out - no re-coregistration.
"""
import json, os, sys
import numpy as np
import isce  # noqa: F401
import isceobj

# 상승/하강 두 궤도가 같은 코드를 쓴다. 기본값은 기존 ASC 경로라 재실행해도 결과가 같다.
SRC = os.environ.get('S1_SRC_STACK',
                     '<WORK_ROOT>/CLAB/regions/seoul/workspace/stamps_seoul/stack/merged')
DST = os.environ.get('S1_ROOT', '<DATA_ROOT>/S1_PSInSAR')
B = json.load(open(f'{DST}/crop_box.json'))
R0, R1, C0, C1 = B['R0'], B['R1'], B['C0'], B['C1']
FW = B['full_W']
NR, NC = R1 - R0, C1 - C0


def render(path, w, l, dtn, bands=1, scheme='BIP', slc=False):
    img = isceobj.createSlcImage() if slc else isceobj.createImage()
    img.setFilename(path); img.setWidth(w); img.setLength(l); img.setAccessMode('read')
    if not slc:
        img.setDataType(dtn); img.bands = bands; img.scheme = scheme
    img.setXmin(0); img.setXmax(w); img.renderHdr()


def crop(src, dst, dtype, nb=1):
    it = np.dtype(dtype).itemsize
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        for r in range(R0, R1):
            for b in range(nb):
                fi.seek(((r * nb + b) * FW + C0) * it)
                np.fromfile(fi, dtype=dtype, count=NC).tofile(fo)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if what in ('all', 'geom'):
        spec = [('lat.rdr.full', np.float64, 1, 'DOUBLE'), ('lon.rdr.full', np.float64, 1, 'DOUBLE'),
                ('hgt.rdr.full', np.float64, 1, 'DOUBLE'), ('los.rdr.full', np.float32, 2, 'FLOAT'),
                ('shadowMask.rdr.full', np.uint8, 1, 'BYTE'), ('incLocal.rdr.full', np.float32, 2, 'FLOAT')]
        for name, dt, nb, dtn in spec:
            s = f'{SRC}/geom_reference/{name}'
            if not os.path.exists(s):
                print(f'   skip {name} (없음)'); continue
            out = name.replace('.rdr.full', '.rdr')
            d = f'{DST}/geom_reference/{out}'
            exp = NR * NC * nb * np.dtype(dt).itemsize
            if os.path.exists(d) and os.path.getsize(d) == exp:
                print(f'   skip {out}'); continue
            crop(s, d, dt, nb)
            render(d, NC, NR, dtn, bands=nb, scheme='BIL' if nb > 1 else 'BIP')
            print(f'   {out}: {os.path.getsize(d)/2**30:.2f} GiB')

    if what in ('all', 'slc'):
        dates = [l.strip() for l in open(f'{DST}/dates.txt') if l.strip()]
        exp = NR * NC * 8
        for i, dt_ in enumerate(dates, 1):
            s = f'{SRC}/SLC/{dt_}/{dt_}.slc.full'
            d = f'{DST}/SLC/{dt_}/{dt_}.slc'
            if os.path.exists(d) and os.path.getsize(d) == exp:
                print(f'   [{i}/{len(dates)}] skip {dt_}'); continue
            if not os.path.exists(s):
                print(f'   [{i}/{len(dates)}] MISSING {dt_}'); continue
            crop(s, d, np.complex64, 1)
            render(d, NC, NR, 'CFLOAT', slc=True)
            print(f'   [{i}/{len(dates)}] {dt_}: {os.path.getsize(d)/2**30:.2f} GiB', flush=True)


if __name__ == '__main__':
    main()
