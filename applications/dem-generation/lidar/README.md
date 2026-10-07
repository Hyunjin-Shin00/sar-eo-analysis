# applications/dem-generation/lidar

LiDAR 포인트/래스터 수집·병합·재투영 — 검증용 참값(0.5 m) 준비.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `download_lidar.ipynb` | OpenTopography LiDAR 타일 목록 조회·내려받기 | TXT | 텍스트/로그 |
| `merge_tiles.ipynb` | LiDAR 타일 병합 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `reproject.ipynb` | LiDAR DSM/DTM 재투영·해상도 정렬 | GeoTIFF | GeoTIFF |
