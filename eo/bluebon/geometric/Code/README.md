# eo/bluebon/geometric/Code

정합·RPC 적합·스트립 보정·일괄 처리.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`03.geometric_correction/`](03.geometric_correction/) |  |
| [`web_app/`](web_app/) | 처리 상태를 보는 웹 UI (FastAPI + React). |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `Download_BlueBON.py` | 처리 대상 장면을 시트에서 읽어 내려받기 | CSV | CSV |
| `Full_processing_v2.py` | BlueBON 기하보정 통합 파이프라인 v2 | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `Strip_correction_3D.py` | Strip_correction_3D.py | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `Strip_correction_all.py` | Strip_correction_all.py | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `batch_processing.py` | BlueBON 배치 기하보정 처리 스크립트 | GeoTIFF · 파일 묶음 | — |
| `eval_utils.py` | 정합 정확도 평가 유틸 (RMSE·잔차 통계) | GeoTIFF | PNG 그림 |
| `pipeline_config.py` | BlueBON Pipeline Configuration | TIF · TIFF | — |
| `pipeline_gui.py` | BlueBON Geometric Correction Pipeline — GUI Interface (tkinter) | GeoTIFF | — |

## 주요 인자

- `Full_processing_v2.py` — `--center-lat` `--center-lon` `--input` `--intermediate` `--lat` `--lon` `--res` `--save-intermediate` `--segment`
- `Strip_correction_3D.py` — `--base_dir` `--legacy_dem` `--modern_dem` `--target`
- `Strip_correction_all.py` — `--base_dir` `--direction` `--legacy_dem` `--strict-dem-nodata`
- `batch_processing.py` — `--batch-count` `--dry-run` `--match-window-sec` `--no-download` `--only-perform-o` `--output-dir` `--sheet` `--tiff-dir`
