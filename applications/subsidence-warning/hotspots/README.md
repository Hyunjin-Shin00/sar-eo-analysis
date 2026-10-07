# applications/subsidence-warning/hotspots

침하 핫스팟 추출·검증.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `hotspot_export.py` | 핫스팟 → 과거 사고 대조 + shp/GeoTIFF 출력 + 지도. | CSV · NumPy · JSON | PNG 그림 · JSON |
| `hotspot_validate.py` | 핫스팟 검증 — 허위양성인지 가림. | NumPy · JSON | JSON |
| `hotspots.py` | 국지 침하 핫스팟 추출. | JSON | — |
