#!/usr/bin/env python3
"""The deliverable layer: every PS with the quantities this study can defend.

vel_sec   secular vertical rate, annual + semi-annual removed.  Only Sentinel-1
          has the 2.6-year record needed for this; the CSK column is left null.
vel_lin   plain linear rate over the product's own record -- what a naive fit
          gives, kept so the seasonal bias is visible rather than hidden.
ann_amp   amplitude of the fitted annual cycle.
cum_win   cumulative vertical displacement over the CSK/S1 common window, the
          one quantity both sensors can be held to.
All rates are relative to the 성북 tie point and are vertical (LOS / cos inc).
"""
import json
import os
import sys

import numpy as np
from osgeo import ogr, osr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_all import CSK, OVERLAP, REF_LL, S1, fit_secular, full_rate, load_ps, reref, window_rate

FIELDS = [('vel_sec', 'secular vertical mm/yr (annual removed)'),
          ('vel_lin', 'plain linear vertical mm/yr over own record'),
          ('ann_amp', 'annual amplitude mm'),
          ('cum_win', 'cumulative vertical mm over common window'),
          ('coh', 'PS coherence (gamma)'),
          ('hgt_m', 'DEM height m'),
          ('inc_deg', 'incidence angle deg')]


def write(path, lon, lat, cols):
    drv = ogr.GetDriverByName('ESRI Shapefile')
    if os.path.exists(path):
        drv.DeleteDataSource(path)
    ds = drv.CreateDataSource(path)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer(os.path.splitext(os.path.basename(path))[0], srs, ogr.wkbPoint)
    for name, _ in FIELDS:
        fd = ogr.FieldDefn(name, ogr.OFTReal); fd.SetWidth(18); fd.SetPrecision(4)
        lyr.CreateField(fd)
    defn = lyr.GetLayerDefn()
    lyr.StartTransaction()
    for i in range(lon.size):
        ft = ogr.Feature(defn)
        for name, _ in FIELDS:
            v = cols.get(name)
            if v is not None and np.isfinite(v[i]):
                ft.SetField(name, float(v[i]))
        g = ogr.Geometry(ogr.wkbPoint); g.AddPoint_2D(float(lon[i]), float(lat[i]))
        ft.SetGeometry(g); lyr.CreateFeature(ft); ft = None
        if i % 500000 == 0 and i:
            lyr.CommitTransaction(); lyr.StartTransaction()
    lyr.CommitTransaction()
    ds = None
    with open(path.replace('.shp', '.fields.txt'), 'w') as f:
        for n, d in FIELDS:
            f.write(f'{n}\t{d}\n')
        f.write(f'\nreference\t성북 {REF_LL[1]:.6f}N {REF_LL[0]:.6f}E (300 m 평균)\n')
        f.write(f'common window\t{OVERLAP[0]} .. {OVERLAP[1]}\n')
        f.write('sign\t음수 = 침하, 양수 = 융기\n')
    return path


def build(tag, npz, out, with_secular):
    D = load_ps(npz)
    reref(D, rad=300.0)
    lin, span = full_rate(D)
    cols = {'vel_lin': lin * D['kv'], 'coh': D['coh'], 'hgt_m': D['hgt'],
            'inc_deg': np.degrees(np.arccos(1.0 / D['kv'])),
            'cum_win': window_rate(D, *OVERLAP)[1] * D['kv']}
    if with_secular:
        sec, amp, _ = fit_secular(D)
        cols['vel_sec'] = sec * D['kv']
        cols['ann_amp'] = amp * D['kv']
    p = write(out, D['lon'], D['lat'], cols)
    print(f'  {tag}: {D["lon"].size:,} 점, span {span:.2f} yr -> {p}')
    return {k: (float(np.nanmedian(v)), float(np.nanstd(v))) for k, v in cols.items()}


def main():
    os.makedirs(f'{S1}/results/gis', exist_ok=True)
    os.makedirs(f'{CSK}/results/gis', exist_ok=True)
    rep = {}
    rep['S1_PS'] = build('S1 PS', f'{S1}/results/seoul_s1_ps.npz',
                         f'{S1}/results/gis/seoul_S1_PS_final.shp', True)
    rep['CSK_PS'] = build('CSK PS', f'{CSK}/results/seoul_csk_ps.npz',
                          f'{CSK}/results/gis/seoul_CSK_PS_final.shp', False)
    with open(f'{CSK}/results/compare/final_layers.json', 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    main()
