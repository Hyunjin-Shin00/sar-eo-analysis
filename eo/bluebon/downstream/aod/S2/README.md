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
