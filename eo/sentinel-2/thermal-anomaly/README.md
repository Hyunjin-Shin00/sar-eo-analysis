# eo/sentinel-2/thermal-anomaly

**TAI** 열이상지수 — SWIR이 고온체에 반응하는 성질로 제련소 가동을 판정한다.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`notebooks/`](notebooks/) | 단일 날짜 TAI, 누적 TAIsum, SWIR 위색 합성. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `geocode_smelters.py` | Geocode copper smelters and write coordinates back to Excel. | Excel | Excel |

## 주요 인자

- `geocode_smelters.py` — `--cache` `--delay` `--email` `--input` `--output`
