# applications/subsidence-warning/hotspots

침하 핫스팟 추출·검증.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `hotspot_export.py` | 핫스팟 → 과거 사고 대조 + shp/GeoTIFF 출력 + 지도. | CSV · NumPy · JSON | PNG 그림 · JSON |
| `hotspot_validate.py` | 핫스팟 검증 — 허위양성인지 가림. | NumPy · JSON | JSON |
| `hotspots.py` | 국지 침하 핫스팟 추출. | JSON | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `hotspots.py` | `MIN_CELLS` | `5` |
