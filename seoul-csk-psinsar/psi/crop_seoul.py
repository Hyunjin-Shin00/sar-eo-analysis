#!/usr/bin/env python3
"""Crop the coregistered stack and geometry to the Seoul bounding window.

Writes raw binaries byte-identical in layout to the originals (single-band
sequential, or 2-band BIL for los/incLocal) plus ISCE .xml/.vrt, so every
downstream tool sees the same formats it saw before - only smaller.
"""
import json, os, sys
import numpy as np
import isce, isceobj

R = '<DATA_ROOT>/CSK_PSInSAR'
BOX = json.load(open(f'{R}/aux/seoul_crop_box.json'))
R0, R1, C0, C1 = BOX['R0'], BOX['R1'], BOX['C0'], BOX['C1']
NR, NC = BOX['NR'], BOX['NC']
FW = BOX['full_W']
OUT = f'{R}/seoul'

# name -> (dtype, nbands, isce data_type, image factory)
LAYERS = {
    'lat.rdr':        (np.float64, 1, 'DOUBLE'),
    'lon.rdr':        (np.float64, 1, 'DOUBLE'),
    'hgt.rdr':        (np.float64, 1, 'DOUBLE'),
    'los.rdr':        (np.float32, 2, 'FLOAT'),
    'incLocal.rdr':   (np.float32, 2, 'FLOAT'),
    'simamp.rdr':     (np.float32, 1, 'FLOAT'),
    'shadowMask.rdr': (np.uint8,   1, 'BYTE'),
}


def crop_raw(src, dst, dtype, nb):
    """Copy the window, preserving single-band or 2-band BIL layout."""
    it = np.dtype(dtype).itemsize
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        for r in range(R0, R1):
            for b in range(nb):
                fi.seek(((r * nb + b) * FW + C0) * it)
                np.fromfile(fi, dtype=dtype, count=NC).tofile(fo)


def render_xml(path, dtype, nb, dtname, scheme='BIL', slc=False):
    img = isceobj.createSlcImage() if slc else isceobj.createImage()
    img.setFilename(path)
    img.setWidth(NC); img.setLength(NR)
    img.setAccessMode('read')
    if not slc:
        img.setDataType(dtname)
        img.bands = nb
        img.scheme = scheme if nb > 1 else 'BIP'
    img.setXmin(0); img.setXmax(NC)
    img.renderHdr()


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'

    if what in ('all', 'geom'):
        print(f'== geometry -> {OUT}/merged/geom_reference  ({NR} x {NC})')
        for name, (dt, nb, dtn) in LAYERS.items():
            s = f'{R}/stack/merged/geom_reference/{name}'
            d = f'{OUT}/merged/geom_reference/{name}'
            if not os.path.exists(s):
                print(f'   skip {name} (원본 없음)'); continue
            if os.path.exists(d) and os.path.getsize(d) == NR * NC * nb * np.dtype(dt).itemsize:
                print(f'   skip {name} (완료)'); continue
            crop_raw(s, d, dt, nb)
            render_xml(d, dt, nb, dtn)
            print(f'   {name}: {os.path.getsize(d)/2**30:.2f} GiB')

    if what in ('all', 'slc'):
        dates = sorted(os.listdir(f'{R}/stack/merged/SLC'))
        print(f'== SLC {len(dates)}개 -> {OUT}/merged/SLC')
        exp = NR * NC * 8
        for dt_ in dates:
            s = f'{R}/stack/merged/SLC/{dt_}/{dt_}.slc'
            d = f'{OUT}/merged/SLC/{dt_}/{dt_}.slc'
            if os.path.exists(d) and os.path.getsize(d) == exp:
                print(f'   skip {dt_}'); continue
            crop_raw(s, d, np.complex64, 1)
            render_xml(d, np.complex64, 1, 'CFLOAT', slc=True)
            print(f'   {dt_}: {os.path.getsize(d)/2**30:.2f} GiB')


if __name__ == '__main__':
    main()
