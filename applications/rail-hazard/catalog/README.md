# applications/rail-hazard/catalog

대상 구간(고가교·노선) 추출.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `build_hachinohe_target.py` | 八戸線 지진 피해구간 / 대조구간을 확정한다. | shp/GeoJSON | shp/GeoJSON |
| `fetch_hachinohe_allrail.py` | coherence 장면 전체(약 26x27 km)의 철도 회랑을 받는다 — 대조군을 제대로 만들기 위해. | GEOJSON | shp/GeoJSON |
| `fetch_hachinohe_viaduct.py` | 八戸線 本八戸~小中野 고가교 지오메트리와 柏崎 지명 위치를 받는다. | GEOJSON · JSON | shp/GeoJSON |
