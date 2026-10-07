"""
Sentinel-2 L2A NDVI (Gao et al. 2017: NDVI=(B08−B04)/(B08+B04), 구름 마스크 적용) → 100 m 공통격자.
원 논문은 QA60 구름마스크를 썼으나 2022년 이후 L2A에서는 QA60이 비어 있으므로 동등한 SCL 마스크 사용
(SCL 3 구름그림자, 8·9 구름, 10 권운, 1 결함, 11 눈 제외).
출처: Earth Search (AWS) sentinel-2-l2a COG, 무료·무인증.
"""
import os, numpy as np, pandas as pd, rasterio, pystac_client, shapely.geometry as sg
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from concurrent.futures import ThreadPoolExecutor
from pyproj import Transformer

from site_config import C, SITE
ROOT = "<WORK_ROOT>"
AOI_LL = C["aoi"]
EPSG = 32652; RES = 100
tr = Transformer.from_crs(4326, EPSG, always_xy=True)
xs, ys = tr.transform([AOI_LL[0], AOI_LL[2], AOI_LL[0], AOI_LL[2]], [AOI_LL[1], AOI_LL[1], AOI_LL[3], AOI_LL[3]])
X0, X1 = np.floor(min(xs) / RES) * RES, np.ceil(max(xs) / RES) * RES
Y0, Y1 = np.floor(min(ys) / RES) * RES, np.ceil(max(ys) / RES) * RES
W, H = int((X1 - X0) / RES), int((Y1 - Y0) / RES)
GRID = dict(x0=X0, y1=Y1, res=RES, width=W, height=H, epsg=EPSG)

def read_item(it):
    try:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES"):
            out = {}
            for k, scale in (("red", 10), ("nir", 10), ("scl", 20)):
                with rasterio.open(it.assets[k].href) as s:
                    w = from_bounds(X0, Y0, X1, Y1, s.transform)
                    out[k] = s.read(1, window=w, out_shape=(H * 10, W * 10), resampling=Resampling.nearest).astype(np.float32)
        red, nir, scl = out["red"], out["nir"], out["scl"]
        ok = ~np.isin(scl, [0, 1, 3, 8, 9, 10, 11]) & (red > 0) & (nir > 0)
        nd = np.where(ok, (nir - red) / (nir + red), np.nan)
        blk = nd.reshape(H, 10, W, 10)
        frac = np.isfinite(blk).mean((1, 3))
        with np.errstate(all="ignore"):
            m = np.nanmean(blk, (1, 3))
        m[frac < 0.5] = np.nan
        return it.properties["datetime"][:10], m, float(np.isfinite(m).mean())
    except Exception as e:
        print("ERR", it.id, e); return None

def main():
    c = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
    aoi = sg.box(*AOI_LL)
    items = [i for i in c.search(collections=["sentinel-2-l2a"], bbox=list(AOI_LL), datetime="2023-11-01/2026-10-05",
                                 query={"eo:cloud_cover": {"lt": 80}}).items()
             if sg.shape(i.geometry).contains(aoi)]
    tiles = sorted({i.id.split("_")[1] for i in items}); tile = C["mgrs"] or tiles[0]
    items = [i for i in items if i.id.split("_")[1] == tile]; print("tile", tile, tiles)
    print("items", len(items), flush=True)
    with ThreadPoolExecutor(12) as ex:
        res = [r for r in ex.map(read_item, items) if r is not None]
    res = [r for r in res if r[2] > 0.3]                      # AOI 30% 이상 맑은 장면만
    res.sort(key=lambda r: r[0])
    dates = np.array([r[0] for r in res]); stack = np.stack([r[1] for r in res])
    np.savez_compressed(f"{C['data']}/s2_ndvi_100m.npz", dates=dates, ndvi=stack, **GRID)
    pd.DataFrame({"date": dates, "clear_frac": [r[2] for r in res]}).to_csv(f"{C['data']}/s2_ndvi_dates.csv", index=False)
    print("kept", len(dates), dates[:3], dates[-3:])

if __name__ == "__main__":
    main()
