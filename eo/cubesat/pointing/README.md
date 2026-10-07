# eo/cubesat/pointing

포인팅 오차와 궤도·자세 메타데이터의 상관분석.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `along_across_cal.py` | 1. Haversine 거리 계산 (meters) | — | — |
| `analysis_combined.py` | Bluebon 포인팅 오차 통합 분석 | Excel | Excel · PNG 그림 |
| `build_analysis.py` | pointing_diff_20260408.xlsx + SatRev_metadata CSV 7개 | CSV · Excel | Excel |
