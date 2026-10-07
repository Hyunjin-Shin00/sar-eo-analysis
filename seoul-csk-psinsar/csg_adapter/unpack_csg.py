#!/usr/bin/env python3
"""Unpack one CSG scene into the ISCE2 stripmapStack SLC layout.

Produces  <slcdir>/<date>.slc , <date>.slc.xml , <date>.slc.vrt , data(.dat/.dir)
exactly like stripmapStack's unpackFrame_CSK.py, so the downstream
stackStripMap.py workflow is unchanged.
"""
import argparse
import glob
import os
import shelve
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import isce  # noqa: F401
from csg_sensor import COSMO_SkyMed_CSG


def cmdLineParse():
    p = argparse.ArgumentParser(description='Unpack a CSG SLC into ISCE2 format.')
    p.add_argument('-i', '--input', dest='h5dir', required=True,
                   help='directory holding the CSG .h5 (or the .h5 itself)')
    p.add_argument('-o', '--output', dest='slcdir', required=True,
                   help='output SLC directory, named <YYYYMMDD>')
    p.add_argument('--block', dest='block', type=int, default=2048,
                   help='lines per I/O block (caps peak memory)')
    return p.parse_args()


def unpack(h5dir, slcname, block=2048):
    if os.path.isfile(h5dir) and h5dir.endswith('.h5'):
        fname = h5dir
    else:
        cands = [f for f in glob.glob(os.path.join(h5dir, '**', '*.h5'), recursive=True)
                 if os.path.basename(f).startswith('CSG_')]
        if not cands:
            raise SystemExit('no CSG_*.h5 under %s' % h5dir)
        fname = sorted(cands)[0]

    os.makedirs(slcname, exist_ok=True)
    date = os.path.basename(slcname)

    obj = COSMO_SkyMed_CSG()
    obj.hdf5 = fname
    obj.blockLines = block
    obj.output = os.path.join(slcname, date + '.slc')

    obj.extractImage()
    obj.frame.getImage().renderHdr()
    obj.extractDoppler()

    with shelve.open(os.path.join(slcname, 'data')) as db:
        db['frame'] = obj.frame

    return fname, obj.frame


if __name__ == '__main__':
    inps = cmdLineParse()
    src, frame = unpack(inps.h5dir.rstrip('/'), inps.slcdir.rstrip('/'), inps.block)
    print('%s -> %s  (%d x %d)' % (os.path.basename(src), inps.slcdir,
                                   frame.getNumberOfLines(), frame.getNumberOfSamples()))
