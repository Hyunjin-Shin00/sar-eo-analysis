#!/usr/bin/env python3
"""Geocoded SBAS grids -> GeoTIFF (+ point shapefile of the valid cells).

MintPy writes geocoded HDF5 on a plain lat/lon grid, so the GeoTIFF transform
comes straight from X_FIRST/Y_FIRST/X_STEP/Y_STEP.  Vertical conversion divides
by cos(incidence); MintPy stores incidenceAngle in DEGREES (unlike our PS npz,
where `inc` is radians), so it is converted here explicitly.
"""
import argparse
import os

import h5py
import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()


def read_geo(path, dset=None):
    with h5py.File(path, 'r') as f:
        key = dset or [k for k in f.keys() if k not in ('date', 'bperp')][0]
        return f[key][:], dict(f.attrs)


def transform(A, ny, nx):
    return (float(A['X_FIRST']), float(A['X_STEP']), 0.0,
            float(A['Y_FIRST']), 0.0, float(A['Y_STEP']))


def write_tif(path, arr, A, nodata=np.nan, desc=''):
    ny, nx = arr.shape
    drv = gdal.GetDriverByName('GTiff')
    ds = drv.Create(path, nx, ny, 1, gdal.GDT_Float32,
                    ['COMPRESS=DEFLATE', 'PREDICTOR=3', 'TILED=YES'])
    ds.SetGeoTransform(transform(A, ny, nx))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.WriteArray(arr.astype(np.float32)); b.SetNoDataValue(float(nodata))
    if desc:
        b.SetDescription(desc)
    ds = None
    return path


def write_points(path, lon, lat, cols):
    if os.path.exists(path):
        ogr.GetDriverByName('ESRI Shapefile').DeleteDataSource(path)
    ds = ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(path)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer('sbas', srs, ogr.wkbPoint)
    for c in cols:
        fd = ogr.FieldDefn(c, ogr.OFTReal); fd.SetWidth(18); fd.SetPrecision(4)
        lyr.CreateField(fd)
    defn = lyr.GetLayerDefn()
    lyr.StartTransaction()
    for i in range(lon.size):
        ft = ogr.Feature(defn)
        for c in cols:
            ft.SetField(c, float(cols[c][i]))
        g = ogr.Geometry(ogr.wkbPoint); g.AddPoint_2D(float(lon[i]), float(lat[i]))
        ft.SetGeometry(g); lyr.CreateFeature(ft); ft = None
    lyr.CommitTransaction()
    ds = None
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--geo', required=True, help='MintPy geo/ directory')
    p.add_argument('--out', required=True)
    p.add_argument('--tag', required=True)
    p.add_argument('--tc-min', type=float, default=0.5)
    p.add_argument('--ts', default=None, help='geocoded timeseries h5')
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)

    vel, A = read_geo(f'{a.geo}/geo_velocity.h5', 'velocity')
    tc, _ = read_geo(f'{a.geo}/geo_temporalCoherence.h5')
    with h5py.File(f'{a.geo}/geo_geometryRadar.h5', 'r') as f:
        inc = f['incidenceAngle'][:]            # MintPy: degrees
        hgt = f['height'][:]
    kv = 1.0 / np.cos(np.radians(inc))

    good = np.isfinite(vel) & (tc >= a.tc_min)
    vlos = np.where(good, vel * 1000.0, np.nan)             # mm/yr
    vver = np.where(good, vel * 1000.0 * kv, np.nan)

    ts = a.ts or 'geo_timeseries_tropHgt_ramp_demErr.h5'
    cum = None
    if os.path.exists(f'{a.geo}/{ts}'):
        with h5py.File(f'{a.geo}/{ts}', 'r') as f:
            d = f['timeseries']
            cum = (d[-1] - d[0]) * 1000.0
            dates = [x.decode() for x in f['date'][:]]
        cum = np.where(good, cum, np.nan)
        print(f'  cumulative window {dates[0]} -> {dates[-1]}')

    outs = []
    outs.append(write_tif(f'{a.out}/{a.tag}_vel_los_mmyr.tif', vlos, A, desc='LOS velocity mm/yr'))
    outs.append(write_tif(f'{a.out}/{a.tag}_vel_vert_mmyr.tif', vver, A, desc='vertical velocity mm/yr'))
    outs.append(write_tif(f'{a.out}/{a.tag}_tempcoh.tif', np.where(np.isfinite(vel), tc, np.nan), A))
    if cum is not None:
        outs.append(write_tif(f'{a.out}/{a.tag}_cum_los_mm.tif', cum, A, desc='cumulative LOS mm'))
        outs.append(write_tif(f'{a.out}/{a.tag}_cum_vert_mm.tif', cum * kv, A, desc='cumulative vertical mm'))

    ny, nx = vel.shape
    lon = float(A['X_FIRST']) + np.arange(nx) * float(A['X_STEP'])
    lat = float(A['Y_FIRST']) + np.arange(ny) * float(A['Y_STEP'])
    LO, LA = np.meshgrid(lon, lat)
    cols = {'vel_los': vlos[good], 'vel_vert': vver[good], 'tcoh': tc[good],
            'hgt_m': hgt[good], 'inc_deg': inc[good]}
    if cum is not None:
        cols['cum_los'] = cum[good]
        cols['cum_vert'] = (cum * kv)[good]
    shp = write_points(f'{a.out}/{a.tag}_sbas.shp', LO[good], LA[good], cols)
    print(f'  valid {int(good.sum()):,} / {good.size:,} ({100*good.mean():.2f}%)')
    for o in outs + [shp]:
        print('  ', o)


if __name__ == '__main__':
    main()
