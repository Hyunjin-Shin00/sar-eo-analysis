# sar/_common

SAR 공통 유틸 — 센서와 무관하게 쓰는 것들.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `check_slc_metadata.py` | 1) Sentinel-1 SLC ZIP 파일 경로 (네가 준 그대로) | ZIP | — |
| `compute_baseline.py` | N2/S1 페어별 기하 조건 계산: Bperp, 입사각(master/secondary), dinc, h_amb, Bperp/Bcrit. | 파일 묶음 | — |
| `landmask.py` | SRTM 1Sec HGT 로 육지 마스크를 만듦. | GeoTIFF | — |
