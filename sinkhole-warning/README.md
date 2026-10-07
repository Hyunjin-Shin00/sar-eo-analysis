# sinkhole-warning — InSAR 기반 지반침하(싱크홀) 위험 판정·경보·리드타임 백테스트

Sentinel-1 PS/SBAS 변위 위에 지반등급(시추공 SPT·수치지질도)과 공공 지반침하 사고 원장을 얹어
"사고 이전에 위험 신호가 있었는가"를 백테스트하고, 한 지역(부산 사상~하단)에 대해 점 등급·위험구역 데모까지 만든 코드.
PS/SBAS 처리 자체는 `insar-ground` 모듈 소관이다.

> 원본 로직 그대로 옮겼고 경로만 일반화했다(`<DATA_ROOT>` = 지역별 PS/SBAS·보조자료 루트, `<WORK_ROOT>` = 작업 폴더).
> 일부 스크립트는 번들에 없는 내부 모듈(`sweep_config.py`, `swept_loader.py` 등)을 import 하므로 그대로는 실행되지 않는다. 읽기용 참고 구현이다.
> 자격증명은 전부 환경변수: `DATA_GO_KR_KEY`(공공데이터포털), `VWORLD_KEY`, `KAKAO_KEY`, `GIMS_KEY` / `GIMS_KEY_STATION` / `GIMS_KEY_DEPTH`.

## 구성

| 폴더 | 내용 |
|---|---|
| `01_accident_data/` | 국토안전관리원 지하안전정보 Open API 전수 수집(`collect_subsidence.py`, 스레드풀+20 TPS 하드캡), 사고원인 `sagoReason` 재수집(`fetch_reasons.py`), VWorld→Kakao 2단 지오코딩, 원인 5분류 라벨(`cause_api_label.py`) |
| `02_fusion_poc/` | 1차 PoC: 시추공 지반등급 α(`step1`), 지질도 보완(`geol_grade`), PS/SBAS 3지표(속도·최근2년 누적·2구간 추세)×α 융합(`step2`), 7개 AOI 케이스 검증·임계치 스윕(`step3`), 판정 옵션 비교(`analyze_options`), 전국 사고리스트 백테스트+대조군(`subsidence_list_analysis`), 사상 판별 필터(`sasang_filter_opt`) |
| `03_alarm_pipeline/` | 융합 알람 파이프라인: 역속도법(Fukuzono) t_f(`invvel`), 점 위험점수→DBSCAN 클러스터 알람(`fuse_cluster`), GIMS 지하수 방아쇠(최종 설계에서 제외, 키 없으면 skip), 백테스트(`backtest`) |
| `04_leadtime_rules/` | 워크포워드 12지표(→72 파생) 시계열, 1단 게이트(배경 대비 백분위 결합·Youden 임계) + 2단 경보(AND·K회 연속) 탐색, 운영 오탐 FP_op, LOAO 교차검증(`rule_loao`, `ml_loao_fast`), 자기검증(`00_selftest.py`) |
| `05_point_grade_demo/` | 사상~하단 데모: 언랩 간섭쌍 → SBAS 역산(`run_sbas_demo`), 주소·기준일 → 정상/주의/위험 판정(`grade_point`), 위험구역 폴리곤(`apply_risk_rule`, `zone_danger`, `make_polygons`) |
| `06_recheck/` | 핸드오프 정리 시 재계산 스크립트(사상 2단 규칙, 위험구역 면적·사고 포함) |

## 실행 메모
- Python 3.8, numpy·scipy·pandas·geopandas·shapely·pyproj·scikit-learn. pyproj 충돌 때문에 `env -u PYTHONPATH` 로 실행.
- 거리 계산은 UTM 52N(EPSG:32652), 시추공 좌표는 EPSG:5186.
- 부호 규약: 변위 − = 침하. 리드타임 시계열(`04`)은 침하=양수로 뒤집어 저장.
- 모든 임계치·버퍼·DBSCAN 파라미터는 잠정값이며, 지역별 규칙은 사고 표본으로 직접 고른 in-sample 값이다(아래 한계 참조).

## 한계(코드 사용 전 필독)
- 사고 지점 버퍼 최대값 방식은 위치 판별력이 거의 없다: 무작위 비사고 지점 400곳에 같은 파이프라인을 돌리면 "탐지율" 82.5%(사고 79.3%).
- 지역별 규칙은 사고에서 임계를 뽑아 in-sample 성능이 낙관적이다. 사고 하나씩 빼는 LOAO 에서 규칙 39.4%, GBM 16.9% 로 떨어진다.
- InSAR 는 지표 변위만 본다. 지하 공동이나 순간 붕괴는 직접 보이지 않는다. 송도 매립지처럼 침하가 커도 붕괴가 없는 곳이 있다.
