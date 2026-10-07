"""과거 재해의 피해 범위를 「얼마나 넓게, 얼마나 길게 퍼지는가」로 정리한다.

왜 이 관점인가
  · 상용 SAR 은 씬 단위로 팔리고 스포트라이트는 5×5 km 급이다.
    따라서 "몇 장 사야 하는가"는 피해의 **면적**이 아니라 **최장 축 길이**가 정한다.
  · 선로 피해는 노선을 따라 가늘고 길게 퍼지므로, 외접 사각형보다
    **최소 외접 회전 사각형의 장축**이 실제 필요 커버리지에 가깝다.

자료
  · 2019 令和元年東日本台風 — 국토지리원 浸水推定段彩図 윤곽선(6개 수계)
  · 2022 米坂線 — JAXA 災害事例集 事例15 도판에서 추출한 붕괴지 4개소
  · 2026 지바 — 이 조사의 SAR 판정 결과
"""
import os, sys, json, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np, pyproj, rasterio
from shapely.geometry import shape, box, LineString
from shapely.ops import unary_union, transform
from rasterio.features import shapes as rshapes
from rasterio.windows import from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds as tfb
from scipy import ndimage

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
GSI = ROOT/"data"/"interim"/"gsi_kuji"; OSM = ROOT/"data"/"raw"/"osm"
OUTT = ROOT/"outputs"/"tables"

# 국토지리원 파일 ↔ 수계 ↔ 그 유역을 지나는 JR 노선(가진 것만)
CASES = [
 ("2019 阿武隈川 수계",      "geo_00.geojson", None),
 ("2019 吉田川 수계",        "geo_01.geojson", None),
 ("2019 久慈川 수계",        "geo_02.geojson", "line_suigun.geojson"),
 ("2019 荒川(入間·越辺·都幾)", "geo_03.geojson", None),
 ("2019 千曲川 수계",        "geo_04.geojson", "nagano_lines.geojson"),
 ("2019 那珂川 수계",        "geo_05.geojson", None),
]


def utm_for(lon):
    return 32600 + int((lon + 180)//6) + 1


def metrics(g, tf):
    """면적 · 외접 사각형 · 최소 외접 회전 사각형의 장축/단축."""
    gm = transform(tf, g)
    b = gm.bounds
    r = gm.minimum_rotated_rectangle
    xs, ys = r.exterior.coords.xy
    e = [np.hypot(xs[i+1]-xs[i], ys[i+1]-ys[i]) for i in range(4)]
    e.sort()
    return gm, dict(area_km2=round(gm.area/1e6, 2),
                    bbox_km=(round((b[2]-b[0])/1000, 1), round((b[3]-b[1])/1000, 1)),
                    long_km=round(e[-1]/1000, 1), short_km=round(e[0]/1000, 1))


def scenes(gm, side_km):
    b = gm.bounds; s = side_km*1000
    nx = int(np.ceil((b[2]-b[0])/s)); ny = int(np.ceil((b[3]-b[1])/s))
    return sum(1 for i in range(nx) for j in range(ny)
               if box(b[0]+i*s, b[1]+j*s, b[0]+(i+1)*s, b[1]+(j+1)*s).intersects(gm))


def rail(fn, tf):
    p = OSM/fn
    if not p.exists(): return None
    d = json.loads(p.read_text())
    gs = [shape(f["geometry"]) for f in d["features"]
          if f.get("geometry", {}).get("type") in ("LineString", "MultiLineString")]
    return transform(tf, unary_union(gs)) if gs else None


def chiba_flood():
    VIEW = (140.100, 35.470, 140.500, 35.720)
    t = pyproj.Transformer.from_crs(4326, 32654, always_xy=True)
    x0, y0 = t.transform(VIEW[0], VIEW[1]); x1, y1 = t.transform(VIEW[2], VIEW[3])
    bb = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    sp = rasterio.open(ROOT/"outputs/samples/chiba_v2_water_pre.tif")
    sq = rasterio.open(ROOT/"outputs/samples/chiba_v2_water_post.tif")
    w = from_bounds(*bb, transform=sp.transform).round_offsets().round_lengths()
    tr = sp.window_transform(w)
    pre = sp.read(1, window=w).astype(bool); post = sq.read(1, window=w).astype(bool)
    ow = np.load(ROOT/"outputs/web/layers/_chiba_optwater_pre.npy")
    o = np.zeros(pre.shape, np.uint8)
    reproject(ow.astype(np.uint8), o, src_transform=tfb(*VIEW, ow.shape[1], ow.shape[0]),
              src_crs=rasterio.crs.CRS.from_epsg(4326), dst_transform=tr, dst_crs=sp.crs,
              resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
    new = post & ~(pre | o.astype(bool))
    lab, n = ndimage.label(new, np.ones((3, 3))); c = np.bincount(lab.ravel()); c[0] = 0
    k = np.zeros(c.size, bool); k[c >= 50] = True; new = k[lab]
    return unary_union([shape(g) for g, v in rshapes(new.astype(np.uint8), mask=new, transform=tr) if v])


def main():
    rows = []
    hdr = ("%-26s %9s %13s %9s %9s  %s" %
           ("사례", "면적", "외접(km)", "장축", "단축", "필요 씬  5 / 10 / 15 km"))
    print(hdr); print("-"*len(hdr))
    for name, fn, railfn in CASES:
        d = json.loads((GSI/fn).read_text())
        g = unary_union([shape(f["geometry"]) for f in d["features"] if f.get("geometry")])
        tf = pyproj.Transformer.from_crs(4326, utm_for(g.bounds[0]), always_xy=True).transform
        gm, m = metrics(g, tf)
        sc = [scenes(gm, s) for s in (5, 10, 15)]
        near = None
        rl = rail(railfn, tf) if railfn else None
        if rl is not None:
            near = round(rl.intersection(gm.buffer(100)).length/1000, 2)
        print("%-26s %6.1f km² %6.1f x %-5.1f %6.1f km %6.1f km  %4d / %3d / %3d%s" %
              (name, m["area_km2"], m["bbox_km"][0], m["bbox_km"][1], m["long_km"], m["short_km"],
               sc[0], sc[1], sc[2],
               "" if near is None else f"   · 노선 100 m 이내 {near} km"))
        rows.append(dict(case=name, **m, scenes_5km=sc[0], scenes_10km=sc[1], scenes_15km=sc[2],
                         rail_near_km=near))

    # 米坂線 붕괴지
    d = json.loads((ROOT/"config/aoi/yonesaka_slide_boxes.geojson").read_text())
    g = unary_union([shape(f["geometry"]) for f in d["features"]])
    tf = pyproj.Transformer.from_crs(4326, utm_for(g.bounds[0]), always_xy=True).transform
    gm, m = metrics(g, tf); sc = [scenes(gm, s) for s in (5, 10, 15)]
    rl = rail("line_yonesaka.geojson", tf)
    near = round(rl.intersection(gm.buffer(100)).length/1000, 2) if rl is not None else None
    print("%-26s %6.1f km² %6.1f x %-5.1f %6.1f km %6.1f km  %4d / %3d / %3d   · 노선 100 m 이내 %s km" %
          ("2022 米坂線 붕괴지 4개소", m["area_km2"], m["bbox_km"][0], m["bbox_km"][1],
           m["long_km"], m["short_km"], sc[0], sc[1], sc[2], near))
    rows.append(dict(case="2022 米坂線 붕괴지 4개소", **m, scenes_5km=sc[0], scenes_10km=sc[1],
                     scenes_15km=sc[2], rail_near_km=near))

    # 지바 2026 (이 조사 판정)
    gm = chiba_flood()
    b = gm.bounds; r = gm.minimum_rotated_rectangle
    xs, ys = r.exterior.coords.xy
    e = sorted(np.hypot(xs[i+1]-xs[i], ys[i+1]-ys[i]) for i in range(4))
    m = dict(area_km2=round(gm.area/1e6, 2),
             bbox_km=(round((b[2]-b[0])/1000, 1), round((b[3]-b[1])/1000, 1)),
             long_km=round(e[-1]/1000, 1), short_km=round(e[0]/1000, 1))
    sc = [scenes(gm, s) for s in (5, 10, 15)]
    print("%-26s %6.1f km² %6.1f x %-5.1f %6.1f km %6.1f km  %4d / %3d / %3d   · 노선 100 m 이내 11.50 km" %
          ("2026 지바 침수(SAR 판정)", m["area_km2"], m["bbox_km"][0], m["bbox_km"][1],
           m["long_km"], m["short_km"], sc[0], sc[1], sc[2]))
    rows.append(dict(case="2026 지바 침수(SAR 판정)", **m, scenes_5km=sc[0], scenes_10km=sc[1],
                     scenes_15km=sc[2], rail_near_km=11.50))

    L = [r["long_km"] for r in rows]
    print(f"\n장축 — 중앙 {np.median(L):.0f} km · 범위 {min(L):.0f} ~ {max(L):.0f} km")
    print(f"5 km 씬으로 덮으려면 중앙 {np.median([r['scenes_5km'] for r in rows]):.0f} 장 필요")
    (OUTT/"phase4_damage_extent.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"\n저장 {OUTT}/phase4_damage_extent.json")


if __name__ == "__main__":
    main()
