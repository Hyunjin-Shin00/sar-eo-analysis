# eo/sentinel-2/thermal-anomaly/notebooks

단일 날짜 TAI, 누적 TAIsum, SWIR 위색 합성.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `false_color.ipynb` | SWIR 위색 합성 — 고온 지점 육안 확인 | GeoTIFF · CSV · shp/GeoJSON | GeoTIFF · PNG 그림 · 텍스트/로그 |
| `tai.ipynb` | 단일 날짜 TAI(열이상지수) 산출·임계값 설정 | GeoTIFF · CSV · shp/GeoJSON · 파일 묶음 | GeoTIFF · CSV · 텍스트/로그 |
| `tai_sum.ipynb` | 입력 및 출력 경로 설정 | GeoTIFF · CSV · shp/GeoJSON | GeoTIFF · CSV · 텍스트/로그 |
