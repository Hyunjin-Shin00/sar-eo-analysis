#!/usr/bin/env python3
"""snaphu unwrapping for the S1 SBAS pairs.

stripmapStack's unwrap.py wants a full ISCE frame shelve, which topsStack's
merged product does not provide. The only things snaphu actually needs are the
wavelength, platform altitude, local earth radius and the effective look count,
so pass them explicitly.
"""
import argparse, os
import isce  # noqa: F401
import isceobj
from contrib.Snaphu.Snaphu import Snaphu

WAVELENGTH = 0.05546576          # Sentinel-1 C-band
ALTITUDE = 693000.0              # S1 nominal orbit height (m)
EARTH_RADIUS = 6373000.0         # local radius of curvature near 37.5N (m)
# 8rg x 2az on 2.33 x 14.24 m spacing with ~2.7 x 22 m resolution
CORR_LOOKS = 9.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-i', '--ifg', required=True)
    p.add_argument('-c', '--coh', required=True)
    p.add_argument('-u', '--unw', required=True)
    p.add_argument('-r', '--rlks', type=int, default=8)
    p.add_argument('-a', '--alks', type=int, default=2)
    p.add_argument('-d', '--defomax', type=float, default=4.0)
    a = p.parse_args()

    img = isceobj.createImage(); img.load(a.ifg + '.xml')
    width, length = img.getWidth(), img.getLength()

    snp = Snaphu()
    snp.setInitOnly(False)
    snp.setInput(a.ifg); snp.setOutput(a.unw); snp.setWidth(width)
    snp.setCostMode('DEFO'); snp.setEarthRadius(EARTH_RADIUS)
    snp.setWavelength(WAVELENGTH); snp.setAltitude(ALTITUDE)
    snp.setCorrfile(a.coh); snp.setInitMethod('MST')
    snp.setCorrLooks(CORR_LOOKS); snp.setMaxComponents(20)
    snp.setCorFileFormat('FLOAT_DATA')   # FilterAndCoherence 는 1밴드 float32 를 낸다
    snp.setDefoMaxCycles(a.defomax); snp.setRangeLooks(a.rlks); snp.setAzimuthLooks(a.alks)
    snp.dumpConnectedComponents = True
    snp.prepare(); snp.unwrap()

    out = isceobj.Image.createUnwImage()
    out.setFilename(a.unw); out.setWidth(width); out.setLength(length)
    out.setAccessMode('read'); out.renderHdr()

    cc = a.unw + '.conncomp'
    if os.path.exists(cc):
        ci = isceobj.Image.createImage(); ci.setFilename(cc)
        ci.setWidth(width); ci.setLength(length); ci.setAccessMode('read')
        ci.bands = 1; ci.scheme = 'BIP'; ci.dataType = 'BYTE'
        ci.renderHdr()


if __name__ == '__main__':
    main()
