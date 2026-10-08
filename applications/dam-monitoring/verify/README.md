# applications/dam-monitoring/verify

결과 재계산 검증.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_figs.py` | Handoff figures for usoi-dam, rendered directly from MintPy h5 (read-only on source). | HDF5 · 이미지 | PNG 그림 |
| `recompute.py` | Independent re-computation of Usoi Dam SBAS numbers from MintPy h5 (read-only). | HDF5 | JSON |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 환경변수

| 이름 | 설명 |
|---|---|
| `DATA_ROOT` | 원본·중간 산출물이 놓인 데이터 루트 |
| `OUT_DIR` | 산출물 디렉터리 |
