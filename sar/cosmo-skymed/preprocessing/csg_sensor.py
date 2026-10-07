#!/usr/bin/env python3
"""
COSMO-SkyMed Second Generation (CSG) SLC reader for ISCE2 2.6.3.

ISCE2's COSMO_SkyMed_SLC sensor targets 1st-generation CSK products.  CSG files
carry every field ISCE2 needs but under different paths/spellings, and the image
itself moved from ``S01/SBI`` (int16 I/Q) to ``S01/IMG`` (float32 I/Q), which the
compiled ``csk.so`` extractor cannot read.

This module re-uses ISCE2's validated CSK metadata translation by presenting the
CSG file through a shim that speaks the 1st-generation layout, and replaces the
image extraction with a chunked numpy implementation.

Mapping (CSG -> what ISCE2 asks for):
    S01/IMG                                       -> S01/SBI
    root  Polarization                            -> S01  Polarisation
    S01   Doppler Centroid vs Range Time Poly     -> root Centroid vs Range Time Polynomial
    S01   Doppler Centroid vs Azimuth Time Poly   -> root Centroid vs Azimuth Time Polynomial
    S01   Doppler Rate vs Azimuth Time Polynomial -> root (same name)
    S01   Range/Azimuth Polynomial Reference Time -> root (same names)
"""

import os
import h5py
import numpy as np

import isce  # noqa: F401  (sets up ISCE2 import paths)
import isceobj
from isceobj.Sensor.COSMO_SkyMed_SLC import COSMO_SkyMed_SLC


class _Node(object):
    """Minimal read-only stand-in for an h5py Group/Dataset."""

    def __init__(self, attrs, shape=None, children=None):
        self.attrs = attrs
        self.shape = shape
        self._children = children or {}

    def __getitem__(self, key):
        node = self
        for part in key.strip('/').split('/'):
            node = node._children[part]
        return node

    def __contains__(self, key):
        try:
            self[key]
            return True
        except KeyError:
            return False


def build_csk1_view(fp, doppler_variant=''):
    """Wrap an open CSG h5py.File so it looks like a 1st-generation CSK file.

    doppler_variant: '' for the antenna Doppler centroid (matches how ISCE2
    reads 1st-gen CSK), or ' - ZD' to use the zero-Doppler variant.
    """
    root_attrs = dict(fp.attrs)
    s01_attrs = dict(fp['S01'].attrs)
    img_attrs = dict(fp['S01/IMG'].attrs)

    v = doppler_variant
    root_attrs['Centroid vs Range Time Polynomial'] = s01_attrs[
        'Doppler Centroid vs Range Time Polynomial' + v]
    root_attrs['Centroid vs Azimuth Time Polynomial'] = s01_attrs[
        'Doppler Centroid vs Azimuth Time Polynomial' + v]
    root_attrs['Doppler Rate vs Azimuth Time Polynomial'] = s01_attrs[
        'Doppler Rate vs Azimuth Time Polynomial']
    root_attrs['Range Polynomial Reference Time'] = s01_attrs[
        'Range Polynomial Reference Time']
    root_attrs['Azimuth Polynomial Reference Time'] = s01_attrs[
        'Azimuth Polynomial Reference Time']

    # ISCE2 reads polarisation from the S01 group (British spelling).
    s01_attrs['Polarisation'] = root_attrs['Polarization']

    nlines, nsamples = fp['S01/IMG'].shape[0], fp['S01/IMG'].shape[1]
    sbi = _Node(img_attrs, shape=(nlines, nsamples))
    s01 = _Node(s01_attrs, children={'SBI': sbi})
    return _Node(root_attrs, children={'S01': s01})


class COSMO_SkyMed_CSG(COSMO_SkyMed_SLC):
    """CSG-aware subclass of ISCE2's CSK SLC sensor."""

    family = 'cosmo_skymed_csg'

    #: '' = antenna Doppler centroid (1st-gen behaviour), ' - ZD' = zero-Doppler
    dopplerVariant = ''

    #: lines read per block during extraction; caps peak memory
    blockLines = 2048

    def parse(self):
        with h5py.File(self.hdf5, 'r') as fp:
            self.populateMetadata(build_csk1_view(fp, self.dopplerVariant))

    def extractImage(self):
        """Read S01/IMG (float32 I/Q) and write a complex64 SLC."""
        with h5py.File(self.hdf5, 'r') as fp:
            img = fp['S01/IMG']
            nlines, nsamples = img.shape[0], img.shape[1]
            scale = float(fp['S01/IMG'].attrs.get('Rescaling Factor', 1.0))

            outdir = os.path.dirname(self.output)
            if outdir and not os.path.isdir(outdir):
                os.makedirs(outdir)

            with open(self.output, 'wb') as out:
                for start in range(0, nlines, self.blockLines):
                    stop = min(start + self.blockLines, nlines)
                    blk = img[start:stop, :, :]
                    cpx = np.empty((stop - start, nsamples), dtype=np.complex64)
                    cpx.real = blk[:, :, 0]
                    cpx.imag = blk[:, :, 1]
                    if scale != 1.0:
                        cpx *= scale
                    cpx.tofile(out)

        self.parse()
        slcImage = isceobj.createSlcImage()
        slcImage.setFilename(self.output)
        slcImage.setXmin(0)
        slcImage.setXmax(nsamples)
        slcImage.setWidth(nsamples)
        slcImage.setLength(nlines)
        slcImage.setAccessMode('r')
        self.frame.setImage(slcImage)


def createSensor(**kwargs):
    obj = COSMO_SkyMed_CSG()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj
