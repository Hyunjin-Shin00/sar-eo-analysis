#!/usr/bin/env python3
"""Screen Seoul's exposed-bedrock massifs as PS-InSAR reference-point candidates.

The reference must be geotechnically stable (bedrock, not alluvium/fill) AND
radar-visible.  At CSG's 18-22 deg incidence, layover eats any slope steeper
than the incidence angle that faces the sensor.  This ascending, right-looking
stack is illuminated from the WSW, so WEST-facing slopes steeper than ~20 deg
are unusable, while gentle ground and east-facing slopes survive.

Lithology below follows the well-known Seoul massifs (Jurassic granite /
Precambrian Gyeonggi gneiss) and MUST be confirmed against a KIGAM 1:50,000
geological map before the reference is fixed.  Radar criteria (amplitude
dispersion, coherence) can only be applied after coregistration.
"""
import json
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

DEM = '<DATA_ROOT>/CSK_PSInSAR/DEM/GLO30_SeoulCSG.wgs84.tif'
INC = 20.05          # mean incidence angle, deg
HALF = 0.0075        # ~750 m half-box

# name, lat, lon, lithology
MASSIFS = [
    ('북한산',      37.6590, 126.9805, 'granite'),
    ('도봉산',      37.6899, 127.0148, 'granite'),
    ('수락산',      37.6836, 127.0640, 'granite'),
    ('불암산',      37.6461, 127.0899, 'granite'),
    ('인왕산',      37.5806, 126.9585, 'granite'),
    ('북악산',      37.5925, 126.9812, 'granite'),
    ('관악산',      37.4450, 126.9640, 'granite'),
    ('청계산',      37.4322, 127.0561, 'granite'),
    ('아차산',      37.5544, 127.1010, 'gneiss'),
    ('용마산',      37.5722, 127.0958, 'gneiss'),
    ('대모산',      37.4762, 127.0730, 'gneiss'),
    ('구룡산',      37.4706, 127.0555, 'gneiss'),
    ('우면산',      37.4713, 127.0125, 'gneiss'),
    ('남산',        37.5512, 126.9882, 'gneiss'),
    ('안산(서대문)', 37.5742, 126.9518, 'granite'),
]


def main():
    ds = gdal.Open(DEM)
    gt = ds.GetGeoTransform()
    dem = ds.ReadAsArray().astype(np.float64)

    # metres per degree at Seoul's latitude
    mx = 111320.0 * np.cos(np.radians(37.55))
    my = 110540.0
    gy, gx = np.gradient(dem, my * abs(gt[5]), mx * gt[1])   # d(h)/d(north), d(h)/d(east)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    # aspect: compass bearing the slope faces
    aspect = (np.degrees(np.arctan2(-gx, gy)) + 360) % 360

    print(f"{'massif':14s} {'암종':7s} {'표고m':>10s} {'평균경사':>8s} "
          f"{'layover위험%':>12s} {'가용%':>7s}  판정")
    print('-' * 78)
    rows = []
    for name, lat, lon, lith in MASSIFS:
        c = int((lon - gt[0]) / gt[1]); r = int((lat - gt[3]) / gt[5])
        dc = int(HALF / gt[1]); dr = int(HALF / abs(gt[5]))
        sl = slope[r - dr:r + dr, c - dc:c + dc]
        asp = aspect[r - dr:r + dr, c - dc:c + dc]
        h = dem[r - dr:r + dr, c - dc:c + dc]
        # west-facing = aspect 202.5..337.5 deg; layover where such slope > incidence
        westish = ((asp > 202.5) & (asp < 337.5))
        layover = float((westish & (sl > INC)).mean() * 100)
        usable = float((sl < INC * 0.75).mean() * 100)   # gentle enough to be safe
        verdict = ('양호' if layover < 10 and usable > 40 else
                   '보통' if layover < 25 else '불리(layover)')
        rows.append((name, lith, h.mean(), sl.mean(), layover, usable, verdict))
        print(f"{name:14s} {lith:7s} {h.mean():10.1f} {sl.mean():7.1f}° "
              f"{layover:11.1f}% {usable:6.1f}%  {verdict}")

    best = sorted([r for r in rows if r[6] == '양호'], key=lambda r: -r[5])
    print('\n=== 1차 추천 (layover 적고 완경사 비율 높은 순) ===')
    for r in best[:5]:
        print(f"  {r[0]:14s} {r[1]:7s} 완경사 {r[5]:.1f}%  layover {r[4]:.1f}%")
    if not best:
        print('  없음 - 기준을 완화하거나 산기슭 평탄부를 별도로 잘라야 함')

    out = '<DATA_ROOT>/CSK_PSInSAR/aux/bedrock_candidates.json'
    with open(out, 'w') as f:
        json.dump([dict(name=r[0], lithology=r[1], lat=m[1], lon=m[2],
                        mean_elev=r[2], mean_slope=r[3],
                        layover_pct=r[4], gentle_pct=r[5], verdict=r[6])
                   for r, m in zip(rows, MASSIFS)], f, ensure_ascii=False, indent=2)
    print(f'\n  저장: {out}')


if __name__ == '__main__':
    main()
