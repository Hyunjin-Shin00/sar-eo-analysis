"""Planetary Computer sentinel-1-rtc (γ0 RTC, 10 m) 에서 COSMOS-UK 3개 지점 주변 2.2 km 창만 읽어 스택 저장.
논문: σ0 GRD + SNAP(Refined Lee, SRTM 3s TC). 여기서는 γ0 RTC(지형평탄화) 사용 → 편차 요인으로 기록."""
import numpy as np, pystac_client, planetary_computer as pc, rasterio, shapely.geometry as sg
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from pyproj import Transformer
from concurrent.futures import ThreadPoolExecutor

B = "<WORK_ROOT>/case_UK_Maslanka2022"
SITES = {"CHIMN": (51.7080, -1.4788), "SHEEP": (51.5303, -1.4819), "WADDN": (51.8395, -0.9484)}
CRS = "EPSG:32630"; RES = 10; HALF = 1100; N = 2 * HALF // RES
tr = Transformer.from_crs(4326, CRS, always_xy=True)
GRID = {}
for s, (la, lo) in SITES.items():
    x, y = tr.transform(lo, la)
    x0 = np.floor((x - HALF) / 1000) * 1000; y1 = x0 * 0 + np.ceil((y + HALF) / 1000) * 1000   # km 정렬 격자
    GRID[s] = dict(x0=x0, y1=y1, xs=x, ys=y)

cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
items = list(cat.search(collections=["sentinel-1-rtc"], bbox=[-1.6, 51.4, -0.8, 51.95], datetime="2016-01-01/2019-12-31",
                        query={"sat:orbit_state": {"eq": "ascending"}, "sat:relative_orbit": {"in": [30, 132]}}).items())
print("items", len(items), flush=True)

def read(it):
    out = []
    g = sg.shape(it.geometry)
    for s, (la, lo) in SITES.items():
        if not g.contains(sg.Point(lo, la).buffer(0.02)): continue
        G = GRID[s]; T = from_origin(G["x0"], G["y1"], RES, RES)
        try:
            with rasterio.open(it.assets["vv"].href) as src, WarpedVRT(src, crs=CRS, transform=T, width=N + 100, height=N + 100,
                                                                     resampling=Resampling.nearest) as v:
                a = v.read(1).astype(np.float32)
            a[a <= 0] = np.nan
            out.append((s, it.properties["datetime"][:19], it.properties["sat:relative_orbit"], it.properties["platform"], a))
        except Exception as e:
            print("ERR", it.id, s, e, flush=True)
    return out

with ThreadPoolExecutor(16) as ex:
    res = [r for rr in ex.map(read, items) for r in rr]
for s in SITES:
    rs = sorted([r for r in res if r[0] == s], key=lambda r: r[1])
    np.savez_compressed(f"{B}/data/s1rtc_{s}.npz", dates=np.array([r[1] for r in rs]), orbit=np.array([r[2] for r in rs]),
                        platform=np.array([r[3] for r in rs]), vv=np.stack([r[4] for r in rs]),
                        x0=GRID[s]["x0"], y1=GRID[s]["y1"], res=RES, xs=GRID[s]["xs"], ys=GRID[s]["ys"])
    print(s, len(rs), flush=True)
