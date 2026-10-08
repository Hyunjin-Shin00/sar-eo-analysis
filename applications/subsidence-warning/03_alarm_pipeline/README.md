# applications/subsidence-warning/03_alarm_pipeline

AOI 단위 경보 파이프라인 — 속도 역수(invvel) 기반 판정.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `aoi.py` | AOI.xlsx → region별 {bbox(S,N,W,E), 사고점, 사고일, 기준점, 기간}. events.py로 사고좌표/일자 보강. | Excel | — |
| `backtest.py` | (5) 백테스팅 — 사고 리스트 = 정답. 사고 이전 시점(asof)으로 알람 클러스터가 사고좌표 | CSV | CSV · 텍스트/로그 |
| `fuse_cluster.py` | (4) 융합 스코어링 & DBSCAN 클러스터 알람. | CSV | — |
| `gims.py` | (1-1)(B) GIMS 국가지하수측정망 지하수위 방아쇠 레이어. | CSV | CSV · 텍스트/로그 |
| `invvel.py` | 역속도법(Fukuzono 1985) — 침하 가속 시 1/v 가 시간에 대해 선형 감소하며 0에서 붕괴(t_f). | — | — |
| `pcfg.py` | 파이프라인 공통 설정. 기존 sinkhole/ 검증자산(loaders·indicators·config·events)을 재사용. | CSV · XLSX | — |
| `run_pipeline.py` | 싱크홀 사전 알람 파이프라인 0~5단계 일괄 실행 (AOI 한정). | CSV | CSV · shp/GeoJSON |

## 주요 인자

- `run_pipeline.py` — `--aoi` `--date-from` `--date-to` `--gims-key` `--skip-backtest`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `GIMS_KEY` | 국가지하수정보센터 인증키 |
| `GIMS_KEY_DEPTH` | 국가지하수정보센터 수위 인증키 |
| `GIMS_KEY_STATION` | 국가지하수정보센터 관측소 인증키 |

### 진입점

```bash
python run_pipeline.py 
```
싱크홀 사전 알람 파이프라인 0~5단계 일괄 실행 (AOI 한정). 0 인벤토리(00_inventory_report.md, 사전작성) 1 GIMS 지하수(옵션) 3 피처(InSAR 3지표+역속도, 지반α) 4 융합→DBSCAN 클러스터 알람(gpkg/csv) 5 백테스

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--aoi` |  |  | 처리할 region 콤마목록(기본 전체 7) |
| `--date-from` |  |  | (예약) 시작일 YYYYMMDD |
| `--date-to` |  |  | asof 종료일 YYYYMMDD(기본 전체기간) |
| `--gims-key` |  |  | GIMS Decoding 서비스키(옵션) |
| `--skip-backtest` |  |  |  |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `aoi.py`, `backtest.py`, `fuse_cluster.py`, `gims.py`, `invvel.py`
