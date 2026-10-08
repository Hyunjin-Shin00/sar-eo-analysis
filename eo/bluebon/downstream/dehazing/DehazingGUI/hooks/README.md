# eo/bluebon/downstream/dehazing/DehazingGUI/hooks

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `rthook_cupy.py` | PyInstaller 런타임 hook: CuPy가 번들된 CUDA DLL을 찾도록 환경변수 설정. | — | — |
| `rthook_dll_search.py` | PyInstaller 런타임 hook: standalone dist 보증. | — | — |
| `rthook_gdal.py` | PyInstaller 런타임 hook: 번들에서 GDAL_DATA / PROJ_LIB 환경변수 설정. | CSV | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 환경변수

| 이름 | 설명 |
|---|---|
| `CUDA_HOME` | 코드 참조 |
| `CUDA_PATH` | 코드 참조 |
| `CUPY_ACCELERATORS` | 코드 참조 |
| `PATH` | 코드 참조 |
