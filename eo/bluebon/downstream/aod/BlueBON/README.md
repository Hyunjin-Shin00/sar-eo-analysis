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
