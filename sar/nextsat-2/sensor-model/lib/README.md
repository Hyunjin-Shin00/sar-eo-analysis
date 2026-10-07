# sar/nextsat-2/sensor-model/lib

센서모델 라이브러리 — 읽기·궤도·기하·대기·지형·시뮬레이션.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `dem.py` | DEM 접근 — Copernicus GLO-30 (EPSG:4326, 1", EGM2008 정표고, Point 등록). | GeoTIFF | — |
| `geometry.py` | Step 3~5. 거리-도플러 엄밀센서모델 — geo2rdr / rdr2geo / 룩사이드. | — | — |
| `n2reader.py` | Step 0-1. NEXTSat-2 LV1A SSC(HDF5) 읽기 + 영상 격자 <-> (방위시각 t, 슬랜트거리 R) 정의. | HDF5 | — |
| `orbit.py` | Step 2. 궤도 보간 — 상태벡터(1 s 간격, 60점)를 연속함수 S(t), V(t), A(t) 로. | — | — |
| `simulate.py` | Step 7. DEM 기반 SAR 지형 시뮬레이션 + 실영상 멀티룩 + 2D 정합. | — | — |
| `tropo.py` | 대류권 전파지연 — 표준대기 기반 간이 모델 (Saastamoinen 건조항 + 습윤항 근사). | — | — |
