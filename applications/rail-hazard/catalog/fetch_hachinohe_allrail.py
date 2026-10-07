"""coherence 장면 전체(약 26x27 km)의 철도 회랑을 받는다 — 대조군을 제대로 만들기 위해.

기존 대조는 같은 노선 고가 2구간(독립 창 약 4개)뿐이었다. 그것으로는
「이 400 m 가 정말 특별한가」를 답할 수 없다. 장면 안 모든 철도에 같은 탐색을 돌린다.
"""
import os, json, pathlib, time
os.environ.pop("PYTHONPATH", None)
import requests, geopandas as gpd
from shapely.geometry import LineString

OSM = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))/"data"/"raw"/"osm"
BBOX = "40.44,141.35,40.62,141.62"     # coherence 산출물 범위
Q = f"""
[out:json][timeout:180];
(
  way["railway"~"^(rail|light_rail|narrow_gauge)$"]({BBOX});
);
out geom tags;
"""

def main():
    for i in range(3):
        r = requests.post("https://overpass-api.de/api/interpreter", data={"data": Q},
                          headers={"User-Agent": "rail-disaster-sar/1.0 (research)"}, timeout=240)
        if r.status_code == 200: break
        print(f"  시도 {i+1} HTTP {r.status_code}"); time.sleep(5)
    else:
        raise SystemExit("Overpass 실패")
    js = r.json()
    rows = []
    for e in js["elements"]:
        if e["type"] != "way" or "geometry" not in e or len(e["geometry"]) < 2: continue
        t = e.get("tags", {})
        if t.get("service") in ("yard", "siding", "spur"): continue
        rows.append(dict(id=e["id"], name=t.get("name", ""), op=t.get("operator", ""),
                         bridge=t.get("bridge", ""), usage=t.get("usage", ""),
                         geometry=LineString([(p["lon"], p["lat"]) for p in e["geometry"]])))
    g = gpd.GeoDataFrame(rows, crs=4326)
    g["len_m"] = g.to_crs(32654).length.round(0)
    g.to_file(OSM/"hachinohe_allrail.geojson", driver="GeoJSON")
    print(f"철도 way {len(g)}건 · 총 연장 {g.len_m.sum()/1000:.1f} km")
    for nm, gg in g.groupby(g.name.fillna("(무명)")):
        if gg.len_m.sum() < 500: continue
        print(f"  {nm[:34]:34s} {gg.len_m.sum()/1000:6.2f} km  operator={gg.op.iloc[0][:20]}")

if __name__ == "__main__":
    main()
