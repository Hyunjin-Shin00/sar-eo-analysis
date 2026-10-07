# eo/bluebon/downstream/dehazing/DehazingGUI/hooks

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `rthook_cupy.py` | PyInstaller 런타임 hook: CuPy가 번들된 CUDA DLL을 찾도록 환경변수 설정. | — | — |
| `rthook_dll_search.py` | PyInstaller 런타임 hook: standalone dist 보증. | — | — |
| `rthook_gdal.py` | PyInstaller 런타임 hook: 번들에서 GDAL_DATA / PROJ_LIB 환경변수 설정. | CSV | — |
