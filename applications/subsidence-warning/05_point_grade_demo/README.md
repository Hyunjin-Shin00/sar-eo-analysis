# applications/subsidence-warning/05_point_grade_demo

지점 등급 판정 데모.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `apply_risk_rule.py` | SBAS 결과 → 위험규칙(T2k) 적용 → 위험구역 산출 — 부산 사상~하단 | GeoTIFF · CSV · JSON | shp/GeoJSON · JSON · 텍스트/로그 · GeoTIFF |
| `grade_point.py` | 지점 등급 판정 — 정상 / 주의 / 위험 — 부산 사상~하단 | CSV · NumPy · JSON | JSON |
| `make_polygons.py` | AOI(분석 영역)·관심 지역 폴리곤을 GeoJSON 으로 뽑는다. | GEOJSON | JSON |
| `run_sbas_demo.py` | 데모용 고속 SBAS — 부산 사상~하단 (Sentinel-1 ASC track 54) | CSV · NumPy · JSON · 파일 묶음 | CSV · shp/GeoJSON · NumPy · 텍스트/로그 |
| `zone_danger.py` | 위험 구역을 폴리곤으로 그린 보고서 지도. | NumPy · JSON | PNG 그림 · 텍스트/로그 |

## 주요 인자

- `apply_risk_rule.py` — `--asof` `--grid` `--min_area_ha` `--out` `--sbas` `--smooth`
- `grade_point.py` — `--asof` `--lat` `--lon` `--out` `--quiet` `--sbas`
- `make_polygons.py` — `--addr` `--handover` `--lat` `--lon` `--name` `--out` `--side`
- `run_sbas_demo.py` — `--cache` `--jobs` `--out` `--precomputed` `--shp` `--snaphu` `--verify`
