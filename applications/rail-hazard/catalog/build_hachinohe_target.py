"""八戸線 지진 피해구간 / 대조구간을 확정한다.

피해 보고(확인 2026-09-16)
  ITmedia 2025-12-10  https://www.itmedia.co.jp/news/articles/2512/10/news078.html
  日経xTECH            https://xtech.nikkei.com/atcl/nxt/column/18/00142/02493/
  → 本八戸―小中野 간 약 20개소 고가교 손상(콘크리트 박락·철근 노출).
    그 중 「第2柏崎高架橋」(1977년 준공) 연장 약 1.8 km 중 약 400 m 에서 기둥 다수 曲げ破壊.
    내진보강 대상 외. 12/30 09시 전선 운전재개(철도 운영사 12/19 발표).

피해구간 = 本八戸~小中野 연속 고가(OSM viaduct way 4개, 합 약 1.97 km)
대조구간 = 같은 八戸線·같은 시가지의 그 구간 밖 고가(서쪽 本八戸 이서, 동쪽 小中野 이동)
  → 「고가교라는 산란체」 성질을 통제한 대조군이다.
第2柏崎高架橋 400 m 의 정확한 시종점은 공개자료로 특정되지 않으므로
  구간을 통째로 잡되 way 별로 따로 집계해 어디서 신호가 나는지 본다.
"""
import os, pathlib
os.environ.pop("PYTHONPATH", None)
import geopandas as gpd

ROOT = pathlib.Path(os.environ.get("WORK_ROOT", "<WORK_ROOT>"))
OSM = ROOT/"data"/"raw"/"osm"; CFG = ROOT/"config"/"aoi"
CFG.mkdir(parents=True, exist_ok=True)

DAMAGE = {24356753: "本八戸 동측", 244791785: "柏崎 서", 244791772: "柏崎 접속",
          24356762: "柏崎~小中野(★第2柏崎 후보)"}
BOUND  = {24356729: "小中野역 구내"}
CTRL   = {24356776: "本八戸 이서", 244791768: "小中野 이동", 244791771: "長苗代 방면",
          244791775: "陸奥湊 부근", 105012137: "陸奥湊 동측"}

def main():
    g = gpd.read_file(OSM/"hachinohe_rail.geojson")
    v = g[(g.bridge.fillna("") != "") & (g.name.fillna("").str.contains("八戸線"))].copy()
    v["id"] = v["id"].astype(int)
    def role(i):
        if i in DAMAGE: return "피해구간"
        if i in BOUND:  return "경계"
        if i in CTRL:   return "대조"
        return "기타"
    v["역할"] = v.id.map(role)
    v["구간명"] = v.id.map({**DAMAGE, **BOUND, **CTRL})
    m = v.to_crs(32654); v["len_m"] = m.length.round(0)
    c = m.geometry.centroid.to_crs(4326); v["lon"] = c.x.round(5); v["lat"] = c.y.round(5)
    v = v[v.역할 != "기타"][["id", "역할", "구간명", "bridge", "len_m", "lon", "lat", "geometry"]]
    v = v.sort_values(["역할", "len_m"], ascending=[True, False])
    v.to_file(CFG/"hachinohe_viaduct.geojson", driver="GeoJSON")
    print(v.drop(columns="geometry").to_string(index=False))
    for r, gg in v.groupby("역할"):
        print(f"  {r}: {len(gg)}개 way, 합 {gg.len_m.sum():.0f} m")
    print(f"\n저장 {CFG/'hachinohe_viaduct.geojson'}")

if __name__ == "__main__":
    main()
