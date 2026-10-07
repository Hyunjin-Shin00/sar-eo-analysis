"""사상 위험구역 면적·사고 포함 여부 재계산 (shapely+pyproj)."""
import sys, json, csv
from shapely.geometry import shape, Point
from shapely.ops import transform, unary_union
from pyproj import Transformer
zones, acc = sys.argv[1], sys.argv[2]
tr = Transformer.from_crs(4326, 32652, always_xy=True).transform
g = json.load(open(zones))
polys = [transform(tr, shape(f["geometry"])) for f in g["features"]]
print("n_features", len(polys), "area_ha", [round(p.area/1e4, 2) for p in polys], "total", round(sum(p.area for p in polys)/1e4, 2))
U = unary_union(polys)
S, N, W, E = 35.1294, 35.1664, 128.9677, 129.0049
rows = [r for r in csv.DictReader(open(acc, encoding="utf-8-sig"))]
box = [r for r in rows if r["lat"] and S <= float(r["lat"]) <= N and W <= float(r["lon"]) <= E]
print("accidents in AOI box", len(box))
for r in sorted(box, key=lambda r: r["sagoDate"]):
    p = Point(tr(float(r["lon"]), float(r["lat"])))
    print(r["sagoDate"], r["geocodeType"], "inside" if U.contains(p) else "out %.0fm" % U.distance(p))
post = [r for r in box if r["sagoDate"] >= "20230101"]
print("2023+ inside", sum(U.contains(Point(tr(float(r["lon"]), float(r["lat"])))) for r in post), "/", len(post))
