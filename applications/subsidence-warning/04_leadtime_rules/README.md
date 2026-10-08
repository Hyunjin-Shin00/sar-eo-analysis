# applications/subsidence-warning/04_leadtime_rules

경보 규칙과 **리드타임 백테스트**. 과적합 검사(LOAO)도 함께.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `00_selftest.py` | 수령자용 자기검증 — 이 폴더만으로 리드타임 재계산이 되는지 확인. usage: python3 00_selftest.py | NumPy · 파일 묶음 | — |
| `fp_operational.py` | 운영 오탐(1단∩2단) 재정의·계산. usage: fp_operational.py [--bg100] | JSON | JSON |
| `leadtime_gate_op.py` | 14절(+100점판): 1단=T2k '운영규칙' 게이트 → 2단 리드타임(오탐은 게이트 미통과 배경으로 참고만). | JSON | JSON |
| `leadtime_last.py` | [최종절] 1단 통과 구역 전용 · 최단 리드 경보조건 탐색. usage: leadtime_last.py | JSON | JSON |
| `leadtime_op.py` | 상시 운영 최적화 규칙 탐색. usage: leadtime_op.py | NumPy · JSON | JSON |
| `leadtime_op2.py` | 리드타임 최소화 + 배경발화 억제 규칙 재탐색(지역별 맞춤·사건별 규칙 금지). usage: leadtime_op2.py | JSON | JSON |
| `leadtime_overfit.py` | 사고별 과적합-허용 최단 리드타임. usage: leadtime_overfit.py | JSON | CSV |
| `leadtime_region_rule.py` | 지역 단일규칙 리드타임(현실화). usage: leadtime_region_rule.py | JSON | CSV · JSON |
| `ml_loao_fast.py` | LOAO(사고 단위 일반화) - 점수 캐싱판. usage: ml_loao_fast.py | JSON | JSON |
| `rule_loao.py` | 규칙기반 1·2단의 LOAO(사고 단위 일반화) 측정. usage: rule_loao.py | JSON | JSON |
| `verify_gate_lead.py` | [검증 전용·읽기 전용] 2단 파이프라인 탐지율 주장 6개 검증. usage: verify_gate_lead.py | JSON | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 환경변수

| 이름 | 설명 |
|---|---|
| `CLAB_ROOT` | 지반침하 과제 트리 루트 |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `00_selftest.py`, `fp_operational.py`, `leadtime_backtest.py`, `leadtime_gate_op.py`, `leadtime_last.py`, `leadtime_op.py`, `leadtime_op2.py`, `leadtime_overfit.py`, `leadtime_region_rule.py`, `ml_loao_fast.py`, `rule_loao.py`, `verify_gate_lead.py`
