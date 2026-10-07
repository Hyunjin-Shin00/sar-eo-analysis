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
