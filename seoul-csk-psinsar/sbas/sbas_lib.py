#!/usr/bin/env python3
"""SBAS helpers: multilooked interferograms and geometry from the Seoul crop.

The coregistered SLCs are already on the master grid, so an interferogram is
just s1 * conj(s2).  We never write the full-resolution product (2 GB x 168
pairs); the looks are accumulated while streaming, so each pair only reads.
"""
import json
import os
import numpy as np
import isce  # noqa: F401
import isceobj

ROOT = '<DATA_ROOT>/CSK_PSInSAR'
SLC = f'{ROOT}/seoul/merged/SLC'
GEOM = f'{ROOT}/seoul/merged/geom_reference'
SBAS = f'{ROOT}/seoul/sbas'
BOX = json.load(open(f'{ROOT}/aux/seoul_crop_box.json'))
NR, NC = BOX['NR'], BOX['NC']
RLKS, ALKS = 10, 8
OR, OC = NR // ALKS, NC // RLKS          # 1735 x 2000


def _render(path, width, length, dtype, bands=1, scheme='BIP'):
    img = isceobj.createImage()
    img.setFilename(path); img.setWidth(width); img.setLength(length)
    img.setAccessMode('read'); img.setDataType(dtype)
    img.bands = bands; img.scheme = scheme
    img.setXmin(0); img.setXmax(width)
    img.renderHdr()


def make_ifg(d1, d2, outdir, blk_lines=400):
    """Multilooked complex interferogram for the pair (d1, d2)."""
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f'{d1}_{d2}.int')
    if os.path.exists(out) and os.path.getsize(out) == OR * OC * 8:
        return out, 'skip'

    blk_lines -= blk_lines % ALKS or 0
    acc = np.empty((OR, OC), dtype=np.complex64)
    f1 = open(f'{SLC}/{d1}/{d1}.slc', 'rb')
    f2 = open(f'{SLC}/{d2}/{d2}.slc', 'rb')
    try:
        row_out = 0
        for lo in range(0, OR * ALKS, blk_lines):
            hi = min(lo + blk_lines, OR * ALKS)
            n = hi - lo
            f1.seek(lo * NC * 8); a = np.fromfile(f1, dtype=np.complex64, count=n * NC).reshape(n, NC)
            f2.seek(lo * NC * 8); b = np.fromfile(f2, dtype=np.complex64, count=n * NC).reshape(n, NC)
            ifg = a[:, :OC * RLKS] * np.conj(b[:, :OC * RLKS])
            del a, b
            # sum over the look window
            ifg = ifg.reshape(n // ALKS, ALKS, OC, RLKS).sum(axis=(1, 3))
            acc[row_out:row_out + ifg.shape[0], :] = ifg
            row_out += ifg.shape[0]
            del ifg
    finally:
        f1.close(); f2.close()
    acc.tofile(out)
    _render(out, OC, OR, 'CFLOAT')
    return out, 'made'


def look_geometry():
    """Multilook the geometry layers onto the interferogram grid."""
    os.makedirs(f'{SBAS}/geom_reference', exist_ok=True)
    spec = [('lat.rdr', np.float64, 1, 'DOUBLE'), ('lon.rdr', np.float64, 1, 'DOUBLE'),
            ('hgt.rdr', np.float64, 1, 'DOUBLE'), ('los.rdr', np.float32, 2, 'FLOAT'),
            ('shadowMask.rdr', np.uint8, 1, 'BYTE')]
    for name, dt, nb, dtn in spec:
        src = f'{GEOM}/{name}'; dst = f'{SBAS}/geom_reference/{name}'
        exp = OR * OC * nb * (1 if dt == np.uint8 else np.dtype(dt).itemsize)
        if os.path.exists(dst) and os.path.getsize(dst) == exp:
            print(f'   skip {name}'); continue
        it = np.dtype(dt).itemsize
        outb = [np.empty((OR, OC), dtype=np.float64 if dt != np.uint8 else np.uint8)
                for _ in range(nb)]
        with open(src, 'rb') as f:
            for r in range(OR):
                for b in range(nb):
                    rows = np.empty((ALKS, OC * RLKS), dtype=dt)
                    for k in range(ALKS):
                        f.seek((((r * ALKS + k) * nb + b) * NC) * it)
                        rows[k] = np.fromfile(f, dtype=dt, count=OC * RLKS)
                    if dt == np.uint8:        # 마스크는 최빈이 아니라 '하나라도 있으면' 보수적으로
                        outb[b][r] = (rows.reshape(ALKS, OC, RLKS).max(axis=(0, 2)))
                    else:
                        outb[b][r] = rows.reshape(ALKS, OC, RLKS).mean(axis=(0, 2))
        with open(dst, 'wb') as g:
            for r in range(OR):
                for b in range(nb):
                    outb[b][r].astype(dt).tofile(g)
        _render(dst, OC, OR, dtn, bands=nb, scheme='BIL' if nb > 1 else 'BIP')
        print(f'   {name}: {OR} x {OC}')
