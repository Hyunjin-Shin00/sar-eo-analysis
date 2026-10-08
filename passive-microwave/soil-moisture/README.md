# passive-microwave/soil-moisture

SMAP L3E 9 km 토양수분 검증.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `verify_smap.py` | SMAP L3E (surviving test-run extract, 8 days) vs RDA in-situ from Cho 2026 Zenodo table. | CSV · Excel | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함
