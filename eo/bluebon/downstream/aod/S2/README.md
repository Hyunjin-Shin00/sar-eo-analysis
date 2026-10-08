# eo/bluebon/downstream/aod/S2

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `S2_AOD_calval.py` | Sentinel-2 AOD 산출·검증 전 과정 | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `bb_aod_calval.py` | Sentinel-2 기준 AOD 검보정 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `bb_aod_pipeline.py` | BlueBON AOD v8 + post-smoothing end-to-end pipeline. | GeoTIFF · 파일 묶음 | — |
| `blend_ddv_maiac.py` | DDV-confidence weighted blend of BB Brovey + MAIAC. | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `blend_ddv_maiac_hdf.py` | DDV-confidence weighted blend reading MAIAC directly from HDF. | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `fit_to_maiac.py` | Fit BlueBON AOD to MAIAC via per-pixel linear regression. | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `pansharpen_to_maiac.py` | Pan-sharpening style fusion: BlueBON high-res + MAIAC absolute level. | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `s2_aod_cal.py` | Sentinel-2 AOD 산출 | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `smooth_v8.py` | bb_aod_v8.tif에 추가 Gaussian 스무딩만 적용해 출력. | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `validate_bb_aod.py` | validate_bb_aod.py — MODIS MAIAC 기반 BlueBON/S2 AOD 검증 및 radiance_scale 보정 | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |

## 주요 인자

- `S2_AOD_calval.py` — `--aerosol-profile` `--aod-bias` `--aod-gain` `--atmosphere-profile` `--earthdata-password` `--earthdata-username` `--fallback-rayleigh-blue-offset` `--min-ddv-fraction` `--modis-cache` `--ndvi-min` `--no-py6s` `--out`
- `bb_aod_calval.py` — `--aerosol-profile` `--aod-bias` `--aod-gain` `--atmosphere-profile` `--ddv-nir-min` `--fallback-rayleigh-offset` `--fill-sigma-px` `--input` `--maiac-aod-mean` `--maiac-ref` `--min-ddv-fraction` `--ndvi-min`
- `bb_aod_pipeline.py` — `--aerosol-profile` `--atmosphere-profile` `--auto-maiac` `--ddv-nir-min` `--earthdata-pass` `--earthdata-user` `--fill-sigma-px` `--input` `--maiac-aod-mean` `--maiac-cache` `--maiac-clip-high-mult` `--maiac-date-window`
- `blend_ddv_maiac.py` — `--bb` `--length-m` `--maiac` `--out` `--qa`
- `blend_ddv_maiac_hdf.py` — `--bb` `--bb-date` `--length-m` `--maiac-dir` `--out` `--qa` `--qa-best`
- `pansharpen_to_maiac.py` — `--mode`
- `s2_aod_cal.py` — `--aod-bias` `--aod-gain` `--ndvi-min` `--out` `--out-qa` `--out-res` `--rayleigh-blue-offset` `--safe` `--surf-blue-a` `--surf-blue-b` `--swir1-max`
- `smooth_v8.py` — `--in` `--out` `--sigma-px`
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
python S2_AOD_calval.py --safe <값> --out <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--safe` | ● |  | Path to Sentinel-2 L1C SAFE directory |
| `--out` | ● |  | Output GeoTIFF path for AOD550 |
| `--out-qa` |  |  | Optional QA GeoTIFF output path |
| `--out-modis` |  |  | Optional collocated MODIS AOD GeoTIFF output path |
| `--validation-csv` |  |  |  |
| `--validation-json` |  |  |  |
| `--modis-cache` |  | `./modis_cache` | Directory for downloaded MODIS files |
| `--run-validation` |  |  | Download MODIS MCD19A2 and compute validation statistics |
| `--ndvi-min` |  | `0.25` |  |
| `--swir1-max` |  | `0.22` |  |
| `--surf-blue-a` |  | `0.5` |  |
| `--surf-blue-b` |  | `0.005` |  |
| `--aod-gain` |  | `4.0` | Fallback linear gain (used only when Py6S unavailable) |
| `--aod-bias` |  | `0.0` | Fallback linear bias (used only when Py6S unavailable) |
| `--fallback-rayleigh-blue-offset` |  | `0.02` | Rayleigh offset used only when Py6S unavailable |
| `--min-ddv-fraction` |  | `0.001` | Minimum fraction of scene that must be DDV (default: 0.001 = 0.1%%) |
| `--out-res` |  | `20` |  |
| `--no-py6s` |  |  | Disable Py6S and use fallback linear calibration |
| `--solar-z-deg` |  |  | Override solar zenith angle (degrees); default: auto from metadata |
| `--view-z-deg` |  |  | Override view zenith angle (degrees); default: auto from metadata |
| `--rel-az-deg` |  |  | Override relative azimuth angle (degrees); default: auto from metadata |
| `--aerosol-profile` |  | `continental` |  |
| `--atmosphere-profile` |  | `auto` | Atmosphere profile for 6S; 'auto' detects from scene date and latitude |
| `--target-alt-km` |  | `0.0` |  |
| `--earthdata-username` |  |  |  |
| `--earthdata-password` |  |  |  |

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
| `--maiac-clip-high-mult` |  |  | DDV AOD 상한 = MAIAC_mean × 이 값 (default: 3.0). MAIAC mean 제공 시에만 적용. -- |
| `--no-maiac-clip` |  |  | MAIAC-anchored DDV upper clipping 비활성 |
| `--maiac-scale-ddv` |  |  | DDV median 을 MAIAC mean 에 맞도록 선형 스케일 (기본 OFF). scale 이 [0.5, 2.0] 밖이면  |

```bash
python blend_ddv_maiac.py 
```
DDV-confidence weighted blend of BB Brovey + MAIAC. Where DDV pixels are nearby → trust BB high-res structure. Where DDV is sparse / absent → fall bac

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--bb` |  | `bb_aod_v8_brovey_sm.tif` |  |
| `--qa` |  | `bb_aod_v8_qa.tif` |  |
| `--maiac` |  | `./validation/maiac_aod_2026-02-20.tif` |  |
| `--out` |  | `bb_aod_blend.tif` |  |
| `--length-m` |  | `500.0` | DDV influence length scale (m); weight=exp(-dist/L) |

```bash
python blend_ddv_maiac_hdf.py 
```
DDV-confidence weighted blend reading MAIAC directly from HDF. 원본 HDF에서 모든 orbit/tile의 raw AOD 픽셀을 읽어 BB 격자로 직접 매핑. 캐시 GeoTIFF 사용 시 발생하는 NaN 손실을 방지.

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--bb` |  | `bb_aod_v8_brovey_sm.tif` |  |
| `--qa` |  | `bb_aod_v8_qa.tif` |  |
| `--maiac-dir` |  | `./validation` | Directory containing MCD19A2*.hdf files |
| `--bb-date` |  | `2026051` | Same-day MAIAC DOY (YYYYDDD); A2026051 = Feb 20 |
| `--out` |  | `bb_aod_blend_hdf.tif` |  |
| `--length-m` |  | `500.0` |  |
| `--qa-best` |  |  | Filter MAIAC pixels to QA_AOD=0 (best quality only) |

```bash
python pansharpen_to_maiac.py 
```
Pan-sharpening style fusion: BlueBON high-res + MAIAC absolute level. Two modes: --mode linear : additive linear fit at 1 km, apply delta to native BB

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `bb_path` |  | `bb_aod_v7.tif` |  |
| `out_path` |  | `bb_aod_v7_pansharp.tif` |  |
| `--mode` |  | `brovey` |  |

```bash
python s2_aod_cal.py --safe <값> --out <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--safe` | ● |  | Path to Sentinel-2 L1C SAFE directory |
| `--out` | ● |  | Output GeoTIFF path for AOD550 |
| `--out-qa` |  |  | Optional output GeoTIFF path for QA |
| `--ndvi-min` |  | `0.3` |  |
| `--swir1-max` |  | `0.5` |  |
| `--surf-blue-a` |  | `0.5` |  |
| `--surf-blue-b` |  | `0.005` |  |
| `--rayleigh-blue-offset` |  | `0.02` |  |
| `--aod-gain` |  | `4.0` |  |
| `--aod-bias` |  | `0.0` |  |
| `--out-res` |  | `20` |  |

```bash
python smooth_v8.py 
```
bb_aod_v8.tif에 추가 Gaussian 스무딩만 적용해 출력.

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--in` |  | `bb_aod_v8.tif` |  |
| `--out` |  | `bb_aod_v8_sm.tif` |  |
| `--sigma-px` |  | `20.0` | 추가 Gaussian sigma (출력 격자 픽셀 단위). default=20 (~400m at 20m) |

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

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `fit_to_maiac.py`
