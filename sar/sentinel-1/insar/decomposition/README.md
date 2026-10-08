# sar/sentinel-1/insar/decomposition

상승·하강 LOS 속도를 **수직·동서 성분**으로 분해하고 두 기법을 비교함.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `build_decomposition.py` | ASC/DSC 중복기간 수직·동서 분해 → SBAS csv 4종 생성. usage: decomp_build.py [지역...] | JSON | CSV · JSON |
| `compare_all.py` | Four-way comparison: CSK PS / CSK SBAS / S1 PS / S1 SBAS. | HDF5 · NumPy | — |
| `compare_diag.py` | Two diagnostics that turn the correlation table into a conclusion. | HDF5 | — |
| `compare_run.py` | Run the four-way comparison and write results/compare/summary.json. | HDF5 | — |
| `decomp_csk_dsc.py` | CSK(상승·X밴드) + S1 DSC(하강·C밴드) 로 봄→여름 창을 수직/동서 분해함. | HDF5 · NumPy | — |
| `decompose_asc_dsc.py` | 상승/하강 궤도 LOS 를 수직 + 동서 성분으로 분해하고, 남북 경사의 정체를 판정함. | HDF5 | — |
| `gu_stats.py` | Per-자치구 summary of the four products. | HDF5 · JSON | — |
| `make_maps.py` | Seoul subsidence maps for the four products. | HDF5 · JSON | PNG 그림 |
| `season_test.py` | Does S1 reproduce the CSK number when given the same months? | HDF5 | — |
| `tilt_verdict.py` | 서울 지도에 남은 도시 규모 경사의 정체를 판정하고 그림으로 냄. | HDF5 · NumPy · JSON | PNG 그림 |
| `validate_ramp.py` | Is the NE-SW gradient in the S1 secular map ground motion or a residual ramp? | 파일 묶음 | — |
| `validate_ramp2.py` | Second pass on the NE-SW tilt, after GNSS coverage turned out to be the limit. | 파일 묶음 | — |

## 주요 인자

- `decomp_csk_dsc.py` — `--cell` `--t0` `--t1`
- `decompose_asc_dsc.py` — `--t0` `--t1`

<!-- crosslink -->
### 이 기법을 쓴 사례

- 여기 코드는 어느 자료에도 쓸 수 있는 처리임. 아래는 실제로 적용한 사건별 분석임

| 사례 | 내용 |
|---|---|
| [`applications/dam-monitoring/`](../../../../applications/dam-monitoring/) | Usoi 자연댐 — 수직·동서 변위와 시계열 웹맵 |
<!-- crosslink -->

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 진입점

```bash
python decomp_csk_dsc.py 
```
CSK(상승·X밴드) + S1 DSC(하강·C밴드) 로 봄→여름 창을 수직/동서 분해함. 왜 이 조합인가. 남은 질문은 서울 지도의 도시 규모 남북 경사가 실제 지반운동인지 잔류 궤도오차인짐. S1 ASC + S1 DSC 로도 분해는 되지만 두 트랙이 함께 덮는 구

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--t0` |  | `2026-04-04` |  |
| `--t1` |  | `2026-08-06` |  |
| `--cell` |  | `0.005` |  |

```bash
python decompose_asc_dsc.py 
```
상승/하강 궤도 LOS 를 수직 + 동서 성분으로 분해하고, 남북 경사의 정체를 판정함. InSAR 는 시선(LOS) 한 방향만 재므로 단일 궤도로는 수직과 수평을 못 가름. 상승과 하강은 동서 감도의 부호가 반대라 두 개를 세우면 풀린다(남북 감도는 양쪽 다 거의

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--t0` |  | `2025-09-09` |  |
| `--t1` |  | `2026-04-26` |  |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `build_decomposition.py` | `MIN_CELL` | `200` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `compare_diag.py`, `compare_run.py`, `gu_stats.py`, `make_maps.py`, `season_test.py`, `tilt_verdict.py`, `validate_ramp.py`, `validate_ramp2.py`
