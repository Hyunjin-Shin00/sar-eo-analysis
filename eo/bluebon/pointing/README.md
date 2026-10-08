# eo/bluebon/pointing

포인팅 오차와 궤도·자세 메타데이터의 상관분석.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `along_across_cal.py` | 1. Haversine 거리 계산 (meters) | — | — |
| `analysis_combined.py` | Bluebon 포인팅 오차 통합 분석 | Excel | Excel · PNG 그림 |
| `build_analysis.py` | pointing_diff_20260408.xlsx + SatRev_metadata CSV 7개 | CSV · Excel | Excel |
| `pointing_across_along_cal.py` | 1. Haversine 거리 계산 (meters) | — | — |
| `run_pt.sh` | 포인팅 오차 산출 실행 | — | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함
