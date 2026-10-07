# eo/bluebon/geometric/Code/03.geometric_correction/geometric_correction/PrcsnMatching

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `Initial_matching_v3.py` | 초기 특징점 정합 — 기준영상 대비 대응점 탐색 | GeoTIFF · 이미지 | CSV · PNG 그림 |
| `Matching_performance_v3.py` | 정밀 정합과 성능 평가 — 이상점 제거, 잔차 분석 | GeoTIFF · CSV · Excel · NumPy | Excel · PNG 그림 · NumPy · 텍스트/로그 |
| `run_romav2_standalone.py` | ── RoMaV2 패키지 경로를 sys.path에 추가 (geo_unified 환경 실행 전용) ── | — | — |

## 주요 인자

- `run_romav2_standalone.py` — `--batch_size` `--dir` `--match_rate_thresh` `--setting` `--target_resolution`
