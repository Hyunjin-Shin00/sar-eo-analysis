#!/usr/bin/env python3
"""Export a PS result (npz) to Shapefile / GeoPackage via OGR.

geopandas is not in this env and the `insar` env has a broken pyproj, so write
with osgeo.ogr directly. Shapefile has a 2 GB limit and 10-char field names, so
the per-epoch time series goes to GeoPackage; the shapefile carries the summary
fields only.
"""
import argparse, os
import numpy as np
from osgeo import ogr, osr
ogr.UseExceptions(); osr.UseExceptions()


def export(npz, out_base, fmt='both', coh_min=None, max_pts=None, with_ts=False):
    Z = np.load(npz)
    lon, lat = Z['lon'], Z['lat']
    vel = Z['vel_mm_yr']; coh = Z['coh']; hgt = Z['hgt_m']; inc = Z['inc_deg']  # inc 는 라디안
    disp = Z['disp_mm']; day = Z['day']
    sel = np.ones(lon.size, bool)
    if coh_min: sel &= coh >= coh_min
    if max_pts and sel.sum() > max_pts:
        idx = np.where(sel)[0]
        keep = np.random.default_rng(0).choice(idx, max_pts, replace=False)
        sel = np.zeros_like(sel); sel[keep] = True
    n = int(sel.sum())
    # LOS -> 수직 환산 (순수 수직 변형 가정), inc 는 라디안으로 저장돼 있음
    kv = 1.0 / np.cos(inc[sel])
    d_end = disp[sel, -1]
    dates = [str(d)[:10] for d in day.astype('datetime64[D]')]

    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    targets = []
    if fmt in ('shp', 'both'): targets.append(('ESRI Shapefile', out_base + '.shp', False))
    if fmt in ('gpkg', 'both'): targets.append(('GPKG', out_base + '.gpkg', with_ts))

    for drv_name, path, ts in targets:
        if os.path.exists(path):
            ogr.GetDriverByName(drv_name).DeleteDataSource(path)
        ds = ogr.GetDriverByName(drv_name).CreateDataSource(path)
        lyr = ds.CreateLayer('ps', srs, ogr.wkbPoint)
        flds = [('vel_los', ogr.OFTReal), ('vel_vert', ogr.OFTReal),
                ('disp_los', ogr.OFTReal), ('disp_vert', ogr.OFTReal),
                ('coh', ogr.OFTReal), ('hgt_m', ogr.OFTReal), ('inc_deg', ogr.OFTReal)]
        if ts:
            flds += [(f'd_{s.replace("-","")}', ogr.OFTReal) for s in dates]
        for nm, t in flds:
            fd = ogr.FieldDefn(nm, t); fd.SetWidth(18); fd.SetPrecision(4); lyr.CreateField(fd)
        defn = lyr.GetLayerDefn()
        lyr.StartTransaction()
        LO, LA, V, C, H, I = lon[sel], lat[sel], vel[sel], coh[sel], hgt[sel], inc[sel]
        D = disp[sel, :] if ts else None
        for k in range(n):
            f = ogr.Feature(defn)
            f.SetField('vel_los', float(V[k])); f.SetField('vel_vert', float(V[k] * kv[k]))
            f.SetField('disp_los', float(d_end[k])); f.SetField('disp_vert', float(d_end[k] * kv[k]))
            f.SetField('coh', float(C[k])); f.SetField('hgt_m', float(H[k]))
            f.SetField('inc_deg', float(np.degrees(I[k])))
            if ts:
                for j, s in enumerate(dates):
                    f.SetField(f'd_{s.replace("-","")}', float(D[k, j]))
            g = ogr.Geometry(ogr.wkbPoint); g.AddPoint_2D(float(LO[k]), float(LA[k]))
            f.SetGeometry(g); lyr.CreateFeature(f); f = None
            if k % 200000 == 0: lyr.CommitTransaction(); lyr.StartTransaction()
        lyr.CommitTransaction(); ds = None
        print(f"   {path}  {n:,} 점  {os.path.getsize(path)/2**20:.1f} MB")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('npz'); p.add_argument('out_base')
    p.add_argument('--fmt', default='both'); p.add_argument('--coh-min', type=float)
    p.add_argument('--max-pts', type=int); p.add_argument('--with-ts', action='store_true')
    a = p.parse_args()
    export(a.npz, a.out_base, a.fmt, a.coh_min, a.max_pts, a.with_ts)
