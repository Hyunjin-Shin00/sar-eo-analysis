# eo/planetscope/change-detection

시기별 변화 디지타이징 결과를 미터 단위로 계량한다. 산지 절토면은 나지와 분광이 비슷해 자동 분류가 흔들리므로, 대상이 선형이고 시기가 적을 때는 손으로 그리고 계산만 코드로 하는 편이 정확했다.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `measure_construction.py` | 시기별 공사현황 선형(shapefile)에서 누적 연장과 군사분계선까지 최단거리를 산출한다. | shp/GeoJSON · 파일 묶음 | CSV |

## 주요 인자

- `measure_construction.py` — `--csv` `--mdl` `--works`
