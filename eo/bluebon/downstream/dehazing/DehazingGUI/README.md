# eo/bluebon/downstream/dehazing/DehazingGUI

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`hooks/`](hooks/) |  |
| [`pipeline/`](pipeline/) |  |
| [`ui/`](ui/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `main.py` | TELEPIX Dehazing GUI — 진입점. | — | 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 환경변수

| 이름 | 설명 |
|---|---|
| `GDAL_DATA` | 코드 참조 |
| `PROJ_LIB` | PROJ 자료 경로 |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `main.py`
