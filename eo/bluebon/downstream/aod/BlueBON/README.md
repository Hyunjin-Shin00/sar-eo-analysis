# eo/bluebon/downstream/aod/BlueBON

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`data/`](data/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `bb_aod_calval.py` | BlueBON AOD 산출 결과 검증 — AERONET·MODIS 대조 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `bb_aod_pipeline.py` | BlueBON AOD v8 + post-smoothing end-to-end pipeline. | GeoTIFF · 파일 묶음 | — |
| `run_bb_aod.sh` | AOD 파이프라인 실행 | — | — |
| `validate_bb_aod.py` | validate_bb_aod.py — MODIS MAIAC 기반 BlueBON/S2 AOD 검증 및 radiance_scale 보정 | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |

## 주요 인자

- `bb_aod_calval.py` — `--aerosol-profile` `--aod-bias` `--aod-gain` `--atmosphere-profile` `--ddv-nir-min` `--fallback-rayleigh-offset` `--fill-sigma-px` `--input` `--maiac-aod-mean` `--maiac-ref` `--min-ddv-fraction` `--ndvi-min`
- `bb_aod_pipeline.py` — `--aerosol-profile` `--atmosphere-profile` `--auto-maiac` `--ddv-nir-min` `--earthdata-pass` `--earthdata-user` `--fill-sigma-px` `--input` `--maiac-aod-mean` `--maiac-cache` `--maiac-date-window` `--min-valid-ddv-fraction`
- `validate_bb_aod.py` — `--bb-aod` `--bb-input` `--current-scale` `--focus-lat` `--focus-lon` `--focus-radius-deg` `--no-download` `--out-dir` `--password` `--s2-aod` `--search-days` `--username`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)

### 진입점

```bash
python bb_aod_calval.py --input <값> --out <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--input` | ● |  | Path to bb_l1c_*_8band.tiff (TOA radiance, uint16 DN) |
| `--out` | ● |  | Output GeoTIFF for AOD(550) |
| `--out-qa` |  |  | Optional QA GeoTIFF |
| `--radiance-scale` |  | `0.3` | DN → radiance coefficient [W/m²/sr/μm per DN]. Replace with official s |
| `--ndvi-min` |  | `0.25` | Min NDVI for DDV selection (겨울: 0.25) |
| `--red-dark-max` |  | `0.15` | Max TOA red reflectance for DDV |
| `--ddv-nir-min` |  | `0.2` | Min NIR reflectance for DDV (vegetation reflects NIR strongly; exclude |
| `--surf-blue-red-ratio` |  | `0.4` | rho_surf_blue / rho_surf_red 기준 비율 (Kaufman 1997: 0.5, 겨울: 0.35–0.45) |
| `--no-ndvi-dependent-ratio` |  |  | NDVI-dependent ratio 비활성화 (고정 ratio 사용) |
| `--min-ddv-fraction` |  | `0.0005` |  |
| `--maiac-aod-mean` |  |  | MAIAC scene AOD 평균값 (validate_bb_aod.py 출력). 지정 시 clear 픽셀 fill에 DDV m |
| `--maiac-ref` |  |  | MAIAC AOD GeoTIFF 경로 (validate_bb_aod.py 출력물). 지정 시 MAIAC 기반 radiance_ |
| `--out-res` |  | `20` | Output resolution in metres |
| `--smooth-sigma-px` |  | `100.0` | Post-fill Gaussian smoothing sigma (5m native px). Higher = smoother s |
| `--fill-sigma-px` |  | `300.0` | Spatial fill Gaussian sigma (5m native px). default: 300. |
| `--no-py6s` |  |  |  |
| `--solar-z-deg` |  |  | Override solar zenith (degrees); default: computed from filename datet |
| `--view-z-deg` |  | `0.0` |  |
| `--rel-az-deg` |  | `0.0` |  |
| `--aerosol-profile` |  | `continental` |  |
| `--atmosphere-profile` |  | `auto` |  |
| `--target-alt-km` |  | `0.0` |  |
| `--fallback-rayleigh-offset` |  | `0.067` |  |
| `--aod-gain` |  | `4.0` |  |
| `--aod-bias` |  | `0.0` |  |

```bash
python bb_aod_pipeline.py --input <값>
```
BlueBON AOD v8 + post-smoothing end-to-end pipeline. 현재까지 가장 좋은 설정으로 판단된 v8 retrieval(`bb_aod_calval.retrieve_aod`)에 Gaussian 후처리 스무딩(`smooth_v8.py` 등

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--input` | ● |  | 입력 BlueBON L1C tiff 경로 또는 glob 패턴. 반복 가능. |
| `--out` |  |  | 단일 입력일 때의 최종 smoothed AOD 출력 경로. 다중 입력/glob 에서는 무시(자동 명명). |
| `--out-dir` |  |  | 출력 디렉토리 (default: 각 입력 파일과 동일 위치) |
| `--save-raw` |  |  | 스무딩 전 v8 결과도 `_v8.tif` 로 저장 |
| `--save-qa` |  |  | QA 레이어 `_qa.tif` 로 저장 |
| `--post-sigma-px` |  |  |  |
| `--radiance-scale` |  |  |  |
| `--solar-z-deg` |  |  |  |
| `--view-z-deg` |  | `0.0` |  |
| `--rel-az-deg` |  | `0.0` |  |
| `--maiac-aod-mean` |  |  | 수동 MAIAC scene mean AOD. 지정 시 --auto-maiac 무시. |
| `--auto-maiac` |  |  | 입력 tiff 의 날짜/bbox 로 MAIAC 자동 다운로드 후 mean 주입 |
| `--maiac-cache` |  | `./maiac_cache` | MAIAC HDF 캐시 디렉토리 (default: ./maiac_cache) |
| `--maiac-date-window` |  | `0` | MAIAC 검색 ±N 일 (default: 0 = 동일 날짜만) |
| `--earthdata-user` |  |  | NASA Earthdata username (없으면 .netrc/env 사용) |
| `--earthdata-pass` |  |  | NASA Earthdata password |
| `--ndvi-min` |  |  |  |
| `--red-dark-max` |  |  |  |
| `--ddv-nir-min` |  |  |  |
| `--surf-blue-red-ratio` |  |  |  |
| `--min-valid-ddv-fraction` |  |  |  |
| `--fill-sigma-px` |  |  |  |
| `--smooth-sigma-px` |  |  |  |
| `--out-res` |  |  |  |
| `--aerosol-profile` |  |  |  |
| `--atmosphere-profile` |  |  |  |
| `--target-alt-km` |  |  |  |
| `--no-py6s` |  |  |  |
| `--no-ndvi-dependent-ratio` |  |  | NDVI-dependent ratio 비활성화 (v8 기본은 활성) |

```bash
python validate_bb_aod.py --bb-input <값> --bb-aod <값>
```
validate_bb_aod.py — MODIS MAIAC 기반 BlueBON/S2 AOD 검증 및 radiance_scale 보정 기능 ---- 1. MODIS MCD19A2 (MAIAC AOD) 자동 다운로드 (NASA Earthdata 계정 필요) 2. 타일 h2

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--bb-input` | ● |  | bb_l1c_*_8band.tiff (원본) |
| `--bb-aod` | ● |  | bb_aod_output.tif |
| `--s2-aod` |  |  | aod_final.tif (S2, 날짜 다름) |
| `--out-dir` |  | `./validation` |  |
| `--username` |  |  |  |
| `--password` |  |  |  |
| `--current-scale` |  | `0.3` | 현재 사용된 radiance_scale |
| `--no-download` |  |  | 이미 다운로드된 .hdf 파일 사용 (out-dir 에서 검색) |
| `--focus-lat` |  | `37.2753` | 검증 관심 지점 위도 (기본: 수원 경기도청 37.2753°N) |
| `--focus-lon` |  | `127.009` | 검증 관심 지점 경도 (기본: 수원 경기도청 127.009°E) |
| `--focus-radius-deg` |  | `0.1` | 관심 지점 검색 반경 [도] (기본: 0.10 ≈ 10 km) |
| `--search-days` |  | `7` | BlueBON 날짜 기준 ±N일 MAIAC 탐색 (기본: 7) |
