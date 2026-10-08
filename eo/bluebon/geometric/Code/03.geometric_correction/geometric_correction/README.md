# eo/bluebon/geometric/Code/03.geometric_correction/geometric_correction

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`PrcsnMatching/`](PrcsnMatching/) |  |
| [`config/`](config/) |  |
| [`core/`](core/) |  |
| [`models/`](models/) |  |
| [`pipeline/`](pipeline/) |  |
| [`utils/`](utils/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `__init__.py` | Geometric Correction Pipeline | — | — |
| `exceptions.py` | 커스텀 예외 클래스 정의 | — | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함
