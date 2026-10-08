# sar/sentinel-1/preprocessing

SLC·GRD 전처리와 스택 코레지스트레이션. 모든 기법의 공통 입구.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`descending/`](descending/) | 하강궤도 전용 수집·코레지. 상승궤도와 설정이 달라 분리함. |
| [`stack/`](stack/) | ISCE2 `stackSentinel` 기반 코레지 SLC 스택 생성 — PS/SBAS 공통 입력. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `burst_pick.py` | AOI를 덮는 Sentinel-1 버스트 선택 | JSON | JSON |
| `coreg_parallel.sh` | 부산(신규 코레지) 지역 처리: 코레지(run_files 병렬) → PS+SBAS(process_region.sh) usage: process_busan.sh REGION "TITLE" S N W  | — | — |
| `dl.py` | 선택된 버스트/장면 다운로드 (~/.netrc 인증) | JSON | — |
| `download_and_preprocess.py` | file: s1_full_pipeline_optional_shp.py Sentinel-1 데이터의 다운로드, 전처리, 수역 분석을 모두 수행하는 통합 파이프라인 AOI Shapefile 지정 여부에 | GeoTIFF · shp/GeoJSON | GeoTIFF · shp/GeoJSON · 텍스트/로그 |
| `fetch_bursts.sh` | ASF BURST 제품을 받아 SAFE 로 조립한다(전체 SLC 대비 8~10배 절약). 사용: fetch_bursts.sh <출력루트> "<W S E N>" <subswath> <라벨:절대궤도>  | — | — |
| `grd_preprocess.py` | file: S1_GRD_preprocessing.py 선택한 편파(VV/HH)만 처리하는 S1 GRD 전처리 파이프라인 | TIF · ZIP | — |
| `grd_sigma0.py` | Sentinel-1 GRD -> calibrated sigma0, geocoded, cropped to an AOI. | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `mk_safe.py` | ASF 버스트(.tiff) -> ESA SAFE 변환. 궤도별/날짜별로 SAFE 1개 생성. | 파일 묶음 | — |
| `slc_to_amp_geotiff.py` | Sentinel-1 IW SLC(.SAFE.zip) → 분석영역 지오코딩 진폭 GeoTIFF. | GeoTIFF | — |

## 주요 인자

- `grd_preprocess.py` — `--input` `--out` `--pol`
- `slc_to_amp_geotiff.py` — `--bounds` `--fill` `--looks` `--out` `--pol` `--res`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `DATA_ROOT` | 원본·중간 산출물이 놓인 데이터 루트 |
| `EARTHDATA_PASS` | NASA Earthdata 비밀번호 |
| `EARTHDATA_USER` | NASA Earthdata 계정 |

### 진입점

```bash
python grd_preprocess.py --input <값> --out <값> --pol <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--input` | ● |  | 처리할 Sentinel-1 GRD 파일 또는 파일이 포함된 폴더 경로 |
| `--out` | ● |  | 결과 파일이 저장될 폴더 |
| `--pol` | ● |  | 처리할 편파 ('VV' 또는 'VH') |

```bash
python slc_to_amp_geotiff.py --bounds <값> --out <값>
```
Sentinel-1 IW SLC(.SAFE.zip) → 분석영역 지오코딩 진폭 GeoTIFF. 지진 분석에 쓴 SLC 원본을 GIS 에서 바로 볼 수 있는 형태로 내보냄. SNAP 산출물(*.data)에는 i/q/coh 밴드만 있고 Intensity 밴드가 없어서, 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `zip` |  |  |  |
| `--bounds` | ● |  |  |
| `--out` | ● |  |  |
| `--pol` |  | `vv` |  |
| `--res` |  | `20.0` | 출력 격자(m) |
| `--looks` |  |  |  |
| `--fill` |  | `12` | 버스트 경계 빈줄 보간 반복횟수(한 번에 1px씩 확산). 0=끄기 |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `download_and_preprocess.py` | `BASE_DIR` | `<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\S1_flood_detection` |
|  | `DOWNLOAD_DIR_NAME` | `01_S1_download` |
|  | `PREPROCESS_DIR_NAME` | `02_preprocess` |
|  | `DEM_DIR_NAME` | `00_dem_slope` |
|  | `ANALYSIS_DIR_NAME` | `03_analysis` |
|  | `START_DATE` | `2025-07-11` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `grd_sigma0.py`
