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

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `DATA_ROOT` | 원본·중간 산출물이 놓인 데이터 루트 |

### 진입점

```bash
python s1_flood_nosnap.py --input_tifs <값> --output_dir <값> --before_mask <값> --after_mask <값> --output_dir <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--input_tifs` | ● |  | 전처리된 S1 dB GeoTIFF 경로(1개 이상) |
| `--output_dir` | ● |  | 산출물 기본 폴더 |
| `--aoi_shp` |  |  | AOI Shapefile 경로(없으면 AOI 미사용) |
| `--dem_path` |  |  | 외부 DEM GeoTIFF 경로(없으면 자동 다운로드) |
| `--slope_path` |  |  | 외부 Slope GeoTIFF 경로(없으면 자동 계산) |
| `--initial_db_threshold` |  |  | Edge Otsu 초기 임계값(dB) |
| `--slope_threshold` |  | `5.0` | 경사 임계값(도) |
| `--edge_buffer` |  | `5` | Edge 감지 후 버퍼링 횟수 |
| `--flood_detection` |  | `no` | 두 시점 수체마스크로 홍수탐지 수행 여부 |
| `--flood_stats` |  | `no` | 홍수 결과 픽셀/면적 통계 로그 출력 |
| `--before_mask` | ● |  | 이전 시점 수체 마스크 경로 |
| `--after_mask` | ● |  | 이후 시점 수체 마스크 경로 |
| `--output_dir` | ● |  | 산출물 폴더(내부적으로 flood_mask 폴더 사용) |
| `--flood_stats` |  | `no` | 픽셀/면적 통계 로그 출력 |

```bash
python s1_flood_snap.py --output_dir <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--inputs` |  |  | ZIP(.SAFE.zip) 또는 전처리된 TIF(선형 σ0) |
| `--batch_root` |  |  | 루트 폴더: 하위 폴더별로 SL2*VV*.tif + MS1*VV*.tif 한 쌍을 찾아 수체탐지만 수행 |
| `--output_dir` | ● |  |  |
| `--polarization` |  | `VV` | ZIP 전처리시에만 사용 |
| `--aoi_shp` |  |  | AOI shapefile (ZIP/전처리TIF 모두에 대해 클립) |
| `--dem_path` |  |  | External DEM (ZIP 전처리시에만 사용) |
| `--flood_detection` |  | `yes` |  |
| `--flood_stats` |  | `yes` |  |
