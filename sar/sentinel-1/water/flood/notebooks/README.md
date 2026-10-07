# sar/sentinel-1/water/flood/notebooks

임계값 전략 비교·결과 검토용 노트북.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `flood_auto.ipynb` | 어떤 tif 파일이든 shp 영역에 맞게 잘라줌 | GeoTIFF · shp/GeoJSON | GeoTIFF · PNG 그림 · 텍스트/로그 |
| `otsu_thresholding.ipynb` | 두 영상 중복 영역에서 NDFVI, NDFI(절댓값x) 계산하고 otsu 적용 | GeoTIFF · shp/GeoJSON | GeoTIFF · shp/GeoJSON · PNG 그림 · 텍스트/로그 |
