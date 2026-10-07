# ISCE2 topsStack 처리 파이프라인

Sentinel-1 SLC 데이터를 PSInSAR(StaMPS) 입력 형식으로 전처리하는 파이프라인.
`stackSentinel.py`가 생성한 13개의 run 파일을 순서대로 실행함.

---

## 처리 파라미터

| 항목 | 값 |
|------|----|
| ISCE2 버전 | 2.6.4 |
| 워크플로우 | `slc` (PSInSAR용 코레지스트레이션 SLC 스택) |
| 코레지스트레이션 | NESD (Enhanced Spectral Diversity) |
| 기준 날짜 | 20240213 (44장 시계열 시간 중앙값) |
| 처리 날짜 수 | 44장 (2023-05-25 ~ 2024-10-22, 12일 반복) |
| 바운딩박스 (SNWE) | 25.31 27.39 117.24 120.07 |
| Azimuth looks | 1 |
| Range looks | 4 |
| 병렬 처리 | 8 프로세스 |

---

## 입력 데이터

| 종류 | 경로 |
|------|------|
| Sentinel-1 SLC | `../sentinel-1/` (44개 zip) |
| 정밀 궤도 (POEORB) | `../orbit/` |
| DEM | `../DEM/output_hh_WGS84.dem` |

---

## 처리 단계

### run_01 — 기준 SLC 언패킹 + 지형 처리

기준 날짜(20240213) SLC를 zip에서 burst 단위로 언패킹하고,
DEM을 이용해 레이더 좌표계로 변환(topo)하여 각 burst의 지형 정보(위경도, 고도, 입사각 등)를 계산함.

```
입력: config_reference
출력: reference/ (burst SLC, geometry 파일들)
```

---

### run_02 — Secondary SLC 언패킹

43개 secondary 날짜의 SLC를 burst 단위로 언패킹함.
8개씩 병렬로 처리(`&` + `wait` 구조)됨.

```
입력: config_secondary_YYYYMMDD × 43
출력: secondarys/YYYYMMDD/ (burst SLC)
```

---

### run_03 — 기선(Baseline) 평균 계산

각 secondary 날짜와 기준 날짜 간의 수직 기선(perpendicular baseline)을 계산함.
PSInSAR에서 고도-위상 변환 계수(Kz) 계산에 사용됨.

```
출력: baselines/ (날짜별 기선 정보)
```

---

### run_04 — Burst Overlap 추출

IW 모드의 인접 burst 간 중첩(overlap) 영역을 추출함.
이 overlap 영역은 ESD(Enhanced Spectral Diversity) 코레지스트레이션의 입력으로 사용됨.

```
출력: overlap/ (burst overlap SLC)
```

---

### run_05 — Overlap 영역 geo2rdr

burst overlap 영역에서 기준-secondary 간 픽셀 오프셋을 geometry 기반으로 초기 추정함.
이후 ESD 정밀 보정의 초기값으로 사용됨.

---

### run_06 — Overlap 영역 리샘플링

run_05의 초기 오프셋을 기반으로 overlap 영역의 secondary burst를 기준 격자로 리샘플링함.
리샘플링된 결과로 ESD 코히런스를 추정함.

---

### run_07 — 날짜 쌍 미스레지스트레이션 추정

각 날짜 쌍의 azimuth 방향 미스레지스트레이션(sub-pixel 오프셋)을 ESD로 추정함.
burst 간 위상 불연속을 최소화하는 방향으로 정밀 오프셋을 계산함.

---

### run_08 — 시계열 미스레지스트레이션 추정

run_07에서 날짜 쌍별로 구한 미스레지스트레이션을 시계열 전체에 걸쳐 일관되게 추정함.
네트워크 기반 최소제곱법으로 각 날짜의 절대 오프셋을 결정함.

---

### run_09 — 전체 Burst geo2rdr

전체 burst 영역에서 geometry 기반 초기 오프셋을 계산함.
run_08의 시계열 미스레지스트레이션 추정값을 반영함.

---

### run_10 — 전체 Burst 리샘플링

run_09의 오프셋을 이용해 모든 secondary burst를 기준 날짜 격자로 정밀 리샘플링함.
이 단계가 핵심 코레지스트레이션 단계로, 처리 시간이 가장 오래 걸림.

```
출력: coreg_secondarys/YYYYMMDD/ (코레지스트레이션된 burst SLC)
```

---

### run_11 — 스택 유효 영역 추출

모든 날짜에서 공통으로 유효한 픽셀 영역을 계산함.
일부 날짜에서 데이터가 없는 가장자리 영역을 마스킹 처리함.

---

### run_12 — Reference + Secondary SLC 병합

burst 단위로 처리된 결과를 subswath 단위로 병합(merge)하고,
최종적으로 전체 장면(scene) 단위의 코레지스트레이션된 SLC 스택을 생성함.

```
출력: merged/SLC/YYYYMMDD/ (최종 SLC 스택)
       merged/geom_reference/ (geometry 파일: lat, lon, los, dem, inc 등)
```

---

### run_13 — 기선 그리드 생성

픽셀 단위의 수직 기선 그리드를 생성함.
StaMPS의 고도 오차 추정(DEM error estimation) 단계에 사용됨.

```
출력: merged/baselines/ (픽셀별 기선 그리드)
```

---

## 실행 방법

```bash
# 전체 자동 실행 (백그라운드)
nohup bash <DATA_ROOT>/16_PSInSAR/run_all_steps.sh \
  > <DATA_ROOT>/16_PSInSAR/ISCE2_processing/process.log 2>&1 &

# 진행 모니터링
tail -f <DATA_ROOT>/16_PSInSAR/ISCE2_processing/process.log
```

## 에러 발생 시

```bash
# 어느 단계에서 멈췄는지 확인
tail -50 <DATA_ROOT>/16_PSInSAR/ISCE2_processing/process.log

# 해당 단계 로그 상세 확인 (예: run_10에서 실패한 경우)
cat <DATA_ROOT>/16_PSInSAR/ISCE2_processing/run_10_fullBurst_resample.log

# 해당 단계부터 재시작
bash <DATA_ROOT>/16_PSInSAR/ISCE2_processing/run_files/run_10_fullBurst_resample
```

---

## 다음 단계 (StaMPS 전처리)

run_13까지 완료되면 `merged/` 디렉토리에 코레지스트레이션된 SLC 스택이 생성됨.
이후 StaMPS_Python으로 PSInSAR 처리를 진행함.

```bash
cd <DATA_ROOT>/16_PSInSAR/StaMPS_Python
isce2stamps
mt_prep_isce 0.4
mt_extract_info_isce
mt_extract_cands
python timeseries_S1/python/psi_python/stamps.py -s 1 -e 8
```
