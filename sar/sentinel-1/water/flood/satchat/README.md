# sar/sentinel-1/water/flood/satchat

서비스 모듈판 — SNAP 비의존(전처리된 dB GeoTIFF 입력) + KuroSiwo 벤치마크 평가.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `eval_kurosiwo.py` | KuroSiwo AOI08(actid 567) 타일별 Edge-Otsu 수체마스크 vs MLU 라벨 재계산 | GeoTIFF · JSON · 파일 묶음 | — |
| `s1_flood_nosnap.py` | Sentinel-1 전처리된 GeoTIFF 기반 자동 수체 탐지 & 홍수 탐지 (snappy 전혀 사용 안 함, 인풋은 dB/TC 완료된 GeoTIFF) + Copernicus DEM 자동 다운로드 | GeoTIFF · shp/GeoJSON | GeoTIFF · shp/GeoJSON · 텍스트/로그 |
| `s1_flood_snap.py` | Sentinel-1 GRD 자동 전처리 및 수체·홍수 탐지 ZIP(SAFE) 원본 + 전처리된 TIF(선형 σ0) 모두 지원 + 배치 모드 파일명: s1_processor6.py | GeoTIFF · shp/GeoJSON | GeoTIFF · 텍스트/로그 |

## 주요 인자

- `s1_flood_nosnap.py` — `--after_mask` `--aoi_shp` `--before_mask` `--dem_path` `--edge_buffer` `--flood_detection` `--flood_stats` `--initial_db_threshold` `--input_tifs` `--output_dir` `--slope_path` `--slope_threshold`
- `s1_flood_snap.py` — `--aoi_shp` `--batch_root` `--dem_path` `--flood_detection` `--flood_stats` `--inputs` `--output_dir` `--polarization`
