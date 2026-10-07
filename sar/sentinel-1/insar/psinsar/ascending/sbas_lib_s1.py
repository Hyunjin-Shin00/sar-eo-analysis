#!/usr/bin/env python3
"""S1 SBAS helpers - multilooked interferograms from the cropped coregistered stack."""
import json, os
import numpy as np
import isce  # noqa: F401
import isceobj

ROOT = os.environ.get('S1_ROOT', '<DATA_ROOT>/S1_PSInSAR')
SLC, GEOM, SBAS = f'{ROOT}/SLC', f'{ROOT}/geom_reference', f'{ROOT}/sbas'
B = json.load(open(f'{ROOT}/crop_box.json'))
NR, NC = B['R1'] - B['R0'], B['C1'] - B['C0']
RLKS, ALKS = 8, 2
OR, OC = NR // ALKS, NC // RLKS


def _render(path, w, l, dtn, bands=1, scheme='BIP'):
    img = isceobj.createImage(); img.setFilename(path)
    img.setWidth(w); img.setLength(l); img.setAccessMode('read')
    img.setDataType(dtn); img.bands = bands; img.scheme = scheme
    img.setXmin(0); img.setXmax(w); img.renderHdr()


def make_ifg(d1, d2, outdir, blk=600):
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f'{d1}_{d2}.int')
    if os.path.exists(out) and os.path.getsize(out) == OR * OC * 8:
        return out, 'skip'
    blk -= blk % ALKS
    acc = np.empty((OR, OC), dtype=np.complex64); row = 0
    with open(f'{SLC}/{d1}/{d1}.slc', 'rb') as f1, open(f'{SLC}/{d2}/{d2}.slc', 'rb') as f2:
        for lo in range(0, OR * ALKS, blk):
            hi = min(lo + blk, OR * ALKS); n = hi - lo
            f1.seek(lo * NC * 8); a = np.fromfile(f1, dtype=np.complex64, count=n * NC).reshape(n, NC)
            f2.seek(lo * NC * 8); b = np.fromfile(f2, dtype=np.complex64, count=n * NC).reshape(n, NC)
            g = (a[:, :OC * RLKS] * np.conj(b[:, :OC * RLKS])).reshape(n // ALKS, ALKS, OC, RLKS).sum(axis=(1, 3))
            acc[row:row + g.shape[0], :] = g; row += g.shape[0]
            del a, b, g
    acc.tofile(out)
    _render(out, OC, OR, 'CFLOAT')
    return out, 'made'


def look_geometry():
    os.makedirs(f'{SBAS}/geom_reference', exist_ok=True)
    spec = [('lat.rdr', np.float64, 1, 'DOUBLE'), ('lon.rdr', np.float64, 1, 'DOUBLE'),
            ('hgt.rdr', np.float64, 1, 'DOUBLE'), ('los.rdr', np.float32, 2, 'FLOAT'),
            ('shadowMask.rdr', np.uint8, 1, 'BYTE')]
    for name, dt, nb, dtn in spec:
        src, dst = f'{GEOM}/{name}', f'{SBAS}/geom_reference/{name}'
        exp = OR * OC * nb * np.dtype(dt).itemsize
        if os.path.exists(dst) and os.path.getsize(dst) == exp:
            print(f'   skip {name}'); continue
        it = np.dtype(dt).itemsize
        outb = [np.empty((OR, OC), dtype=np.float64 if dt != np.uint8 else np.uint8) for _ in range(nb)]
        with open(src, 'rb') as f:
            for r in range(OR):
                for b in range(nb):
                    rows = np.empty((ALKS, OC * RLKS), dtype=dt)
                    for k in range(ALKS):
                        f.seek((((r * ALKS + k) * nb + b) * NC) * it)
                        rows[k] = np.fromfile(f, dtype=dt, count=OC * RLKS)
                    blk = rows.reshape(ALKS, OC, RLKS)
                    outb[b][r] = blk.max(axis=(0, 2)) if dt == np.uint8 else blk.mean(axis=(0, 2))
        with open(dst, 'wb') as g:
            for r in range(OR):
                for b in range(nb):
                    outb[b][r].astype(dt).tofile(g)
        _render(dst, OC, OR, dtn, bands=nb, scheme='BIL' if nb > 1 else 'BIP')
        print(f'   {name}: {OR} x {OC}')
