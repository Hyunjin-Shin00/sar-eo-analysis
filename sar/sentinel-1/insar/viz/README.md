# sar/sentinel-1/insar/viz

변위 결과 시각화.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_clickmap.py` | 일반화 PS/SBAS 클릭맵. OSM/Esri, 빨강=침하 파랑=융기, 클릭→시계열, 기준영역 마커, POI(선택). | shp/GeoJSON · JSON | 텍스트/로그 |

## 주요 인자

- `make_clickmap.py` — `--no_poi` `--out` `--poi` `--poi_label` `--ref` `--shp` `--title`
