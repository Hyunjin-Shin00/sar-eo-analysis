"""八戸線 本八戸~小中野 고가교 지오메트리와 柏崎 지명 위치를 받는다.
피해 구간 = 第2柏崎高架橋(1977년 준공, 연장 1.8 km 중 약 400 m, 약 20개소 손상).
출처: ITmedia 2025-12-10 / 日経xTECH (확인 2026-09-16)"""
import os, json, pathlib, time
os.environ.pop("PYTHONPATH", None)
import requests, geopandas as gpd
from shapely.geometry import LineString, Point

OSM = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))/"data"/"raw"/"osm"
HDR = {"User-Agent": "rail-disaster-sar/1.0 (research)"}
BBOX = "40.48,141.42,40.56,141.56"

Q_RAIL = f"""
[out:json][timeout:120];
(
  way["railway"="rail"]({BBOX});
  way["railway"="light_rail"]({BBOX});
);
out geom tags;
"""
Q_PLACE = f"""
[out:json][timeout:120];
(
  node["place"]["name"~"柏崎|小中野|類家|沼館"]({BBOX});
  way["name"~"柏崎"]["highway"]({BBOX});
  node["name"~"柏崎"]({BBOX});
);
out center tags;
"""

def run(q, tag):
    for i in range(3):
        r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q},
                          headers=HDR, timeout=180)
        if r.status_code == 200:
            return r.json()
        print(f"  {tag} 시도 {i+1} → HTTP {r.status_code}"); time.sleep(5)
    raise SystemExit(f"{tag} 실패")

def main():
    js = run(Q_RAIL, "rail")
    (OSM/"hachinohe_rail.json").write_text(json.dumps(js))
    rows = []
    for e in js["elements"]:
        if e["type"] != "way" or "geometry" not in e or len(e["geometry"]) < 2: continue
        t = e.get("tags", {})
        rows.append(dict(id=e["id"], name=t.get("name", ""), bridge=t.get("bridge", ""),
                         layer=t.get("layer", ""), usage=t.get("usage", ""),
                         geometry=LineString([(p["lon"], p["lat"]) for p in e["geometry"]])))
    g = gpd.GeoDataFrame(rows, crs=4326)
    m = g.to_crs(32654); g["len_m"] = m.length.round(0)
    g.to_file(OSM/"hachinohe_rail.geojson", driver="GeoJSON")
    v = g[(g.bridge != "") & (g.name.str.contains("八戸線"))].sort_values("len_m", ascending=False)
    print(f"八戸線 교량/고가 {len(v)}건")
    c = v.to_crs(32654).geometry.centroid.to_crs(4326)
    for (i, r), p in zip(v.iterrows(), c):
        print(f"  {r.id:>10} {r.bridge:>8} {r.len_m:6.0f} m  중심 {p.x:.5f},{p.y:.5f}")

    try:
        jp = run(Q_PLACE, "place")
        (OSM/"hachinohe_place.json").write_text(json.dumps(jp))
        print("\n지명:")
        for e in jp["elements"]:
            t = e.get("tags", {})
            lon = e.get("lon") or e.get("center", {}).get("lon")
            lat = e.get("lat") or e.get("center", {}).get("lat")
            if lon: print(f"  {t.get('name','')} ({t.get('place', t.get('highway',''))}) {lon:.5f},{lat:.5f}")
    except SystemExit as ex:
        print(f"\n지명 조회 실패: {ex}")

if __name__ == "__main__":
    main()
