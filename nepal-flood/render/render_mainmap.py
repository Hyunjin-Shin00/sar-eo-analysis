#!/usr/bin/env python
"""
카드뉴스 주 지도: ESRI World Imagery 위성 배경 + 회랑 + 탐지구역 + 지명.
usage: render_mainmap.py <TRACK> [zoom]
"""
import os, sys, json, math, io, urllib.request, concurrent.futures as cf
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from PIL import Image
from osgeo import gdal, ogr, osr
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
OUT = f'{BASE}/analysis/cards'
os.makedirs(OUT, exist_ok=True)
W, S, E, N = 85.085, 27.820, 85.560, 28.400
TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
FLOOD = ['吉隆藏布', 'Bhote Koshi', 'Trishuli Ganga River', 'Mailung Khola']


def deg2num(lon, lat, z):
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    la = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(la)) / math.pi) / 2.0 * n
    return x, y


def num2deg(x, y, z):
    n = 2.0 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def fetch(z, x, y):
    url = TILE.format(z=z, x=x, y=y)
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            return Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert('RGB')
        except Exception:
            pass
    return Image.new('RGB', (256, 256), (40, 45, 50))


def basemap(z):
    x0f, y0f = deg2num(W, N, z); x1f, y1f = deg2num(E, S, z)
    x0, y0, x1, y1 = int(math.floor(x0f)), int(math.floor(y0f)), int(math.ceil(x1f)), int(math.ceil(y1f))
    nx, ny = x1 - x0, y1 - y0
    print(f'  z={z} 타일 {nx}x{ny} = {nx*ny}장')
    canvas = Image.new('RGB', (nx * 256, ny * 256))
    jobs = [(xx, yy) for yy in range(y0, y1) for xx in range(x0, x1)]
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        for (xx, yy), im in zip(jobs, ex.map(lambda t: fetch(z, t[0], t[1]), jobs)):
            canvas.paste(im, ((xx - x0) * 256, (yy - y0) * 256))
    # 요청 범위로 정확히 crop
    px0 = int(round((x0f - x0) * 256)); py0 = int(round((y0f - y0) * 256))
    px1 = int(round((x1f - x0) * 256)); py1 = int(round((y1f - y0) * 256))
    return canvas.crop((px0, py0, px1, py1))


def main():
    trk = sys.argv[1]
    z = int(sys.argv[2]) if len(sys.argv) > 2 else 13
    bg = basemap(z)
    Wpx, Hpx = bg.size
    print(f'  배경 {Wpx}x{Hpx}')

    # --- 벡터/래스터를 배경 격자에 맞춰 렌더 ---
    gt = (W, (E - W) / Wpx, 0, N, 0, -(N - S) / Hpx)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)

    def burn(geoms):
        src = ogr.GetDriverByName('Memory').CreateDataSource('m')
        lyr = src.CreateLayer('l', srs, ogr.wkbPolygon)
        for g in geoms:
            f = ogr.Feature(lyr.GetLayerDefn()); f.SetGeometry(g); lyr.CreateFeature(f)
        t = gdal.GetDriverByName('MEM').Create('', Wpx, Hpx, 1, gdal.GDT_Byte)
        t.SetGeoTransform(gt); t.SetProjection(srs.ExportToWkt())
        gdal.RasterizeLayer(t, [1], lyr, burn_values=[1])
        return t.GetRasterBand(1).ReadAsArray().astype(bool)

    els = json.load(open(f'{BASE}/aux/osm_rivers.json'))
    geoms = []
    for e in els:
        if e.get('tags', {}).get('name', '') not in FLOOD:
            continue
        g = e.get('geometry') or []
        if len(g) < 2:
            continue
        ln = ogr.Geometry(ogr.wkbLineString)
        for p in g:
            ln.AddPoint_2D(p['lon'], p['lat'])
        geoms.append(ln.Buffer(300 / 111320.))
    corr = burn(geoms)

    det_ds = gdal.Open(f'{BASE}/analysis/{trk}/flood_detect.tif')
    det_w = gdal.Warp('', det_ds, format='MEM', outputBounds=[W, S, E, N],
                      width=Wpx, height=Hpx, resampleAlg='max')
    det = det_w.GetRasterBand(1).ReadAsArray() > 0
    sp = f'{BASE}/analysis/{trk}/source_scar.tif'
    if os.path.exists(sp):
        sw = gdal.Warp('', gdal.Open(sp), format='MEM', outputBounds=[W, S, E, N],
                       width=Wpx, height=Hpx, resampleAlg='max')
        det = det | (sw.GetRasterBand(1).ReadAsArray() > 0)

    arr = np.array(bg).astype(np.float32)
    # 회랑 = 옅은 청록 반투명
    edge = corr & ~np.roll(corr, 3, 0) | corr & ~np.roll(corr, -3, 0) | \
           corr & ~np.roll(corr, 3, 1) | corr & ~np.roll(corr, -3, 1)
    arr[corr] = 0.82 * arr[corr] + 0.18 * np.array([80, 220, 235], np.float32)
    arr[edge] = 0.35 * arr[edge] + 0.65 * np.array([90, 235, 245], np.float32)
    # 탐지구역 = 진한 빨강 (3px 확대해 가시성 확보)
    from scipy import ndimage
    detd = ndimage.binary_dilation(det, np.ones((3, 3)), iterations=2)
    arr[detd] = 0.12 * arr[detd] + 0.88 * np.array([255, 45, 45], np.float32)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    img.save(f'{OUT}/mainmap.png')
    json.dump(dict(W=W, S=S, E=E, N=N, px=[Wpx, Hpx], zoom=z),
              open(f'{OUT}/mainmap.json', 'w'))
    print(f'  wrote {OUT}/mainmap.png  ({Wpx}x{Hpx})  탐지화소 {det.sum():,}')


if __name__ == '__main__':
    main()
