# sar/sentinel-1/water/flood

**홍수 탐지.** Edge-Otsu 자동 임계값으로 수체를 분리하고 전후 차분으로 침수역을 낸다.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`notebooks/`](notebooks/) | 임계값 전략 비교·결과 검토용 노트북. |
| [`satchat/`](satchat/) | 서비스 모듈판 — SNAP 비의존(전처리된 dB GeoTIFF 입력) + KuroSiwo 벤치마크 평가. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `analyse_flood_grd.py` | The actual analysis: what can free Sentinel-1 see of this disaster, measured. | GeoTIFF · JSON | GeoTIFF · JSON · 텍스트/로그 |
| `db_geocode.py` | 날짜별 후방산란(dB)을 간섭도와 같은 레이더 격자로 만들고 ISCE 메타데이터를 붙인다. | GeoTIFF | 텍스트/로그 |
| `flood_detect_slc.py` | 홍수 피해구역 탐지 (강임계 + 대조군 + 군집필터) — 2026 네팔 홍수 | GeoTIFF · JSON | — |
| `flood_map.py` | 탐지 결과 지도 + 주요 군집 좌표. usage: flood_map.py <TRACK> | GeoTIFF · JSON | PNG 그림 · JSON |
| `otsu_flood.py` | Otsu 임계 기반 홍수 피해구역 분할 — 2026 네팔 홍수 | GeoTIFF · JSON | — |
| `s1_processor.py` | Sentinel-1 자동 수체 탐지 및 홍수 탐지 통합 파이프라인 파일명: s1_processor7.py (전처리 전에 인셋: 자동 NaN행 기반 트리밍) | GeoTIFF · shp/GeoJSON | GeoTIFF · shp/GeoJSON · 텍스트/로그 |
| `s1_processor_benchmark.py` | 벤치마크 평가판 — 전처리된 GeoTIFF 입력으로 수체 마스크만 산출 (Sen1Flood11/KuroSiwo) | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `waterbody_mask.py` | 수체 마스크만 산출하는 경량 버전 (홍수 차분 없음) | GeoTIFF · shp/GeoJSON · 파일 묶음 | GeoTIFF · 텍스트/로그 |

## 주요 인자

- `s1_processor.py` — `--after_mask` `--aoi_shp` `--before_mask` `--dem_path` `--edge_buffer` `--flood_detection` `--flood_stats` `--initial_db_threshold` `--input_zips` `--output_dir` `--polarization` `--slope_path`
- `s1_processor_benchmark.py` — `--edge_buffer` `--initial_db_threshold` `--input_tifs` `--output_dir` `--polarization`
