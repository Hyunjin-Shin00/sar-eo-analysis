# sar/nextsat-2/insar

N2 자체 파이썬 간섭처리 (ISCE2 비의존 경로).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `n2insar.py` | n2insar.py — NEXTSat-2 (X-band) 직접 InSAR 처리 모듈 (ISCE2 스푸핑 미사용) | GeoTIFF · HDF5 | — |
| `run_insar.py` | 개선 자작 파이프라인: 기하코레지 + 코히런스기반 방위/거리 정밀정합(ESD-lite) | GeoTIFF · HDF5 | GeoTIFF · PNG 그림 · JSON · 텍스트/로그 |
