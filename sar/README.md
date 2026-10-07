# sar

**능동 마이크로파(SAR).** 위성별로 나누고, 그 아래 분석 기법별로 묶었다.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`_common/`](_common/) | SAR 공통 유틸 — 센서와 무관하게 쓰는 것들. |
| [`cosmo-skymed/`](cosmo-skymed/) | **COSMO-SkyMed / CSG (X-band).** 상용 고해상도 SAR. |
| [`nextsat-2/`](nextsat-2/) | **차세대소형위성 2호 (국산 X-band).** 어떤 상용·공개 SW도 지원하지 않아 처리기를 직접 만들었다. |
| [`sentinel-1/`](sentinel-1/) | **Sentinel-1 (C-band).** 가장 많이 쓴 위성. 전처리 → 기법별 분석 순서로 배치했다. |
| [`umbra/`](umbra/) | **Umbra (25 cm 상용 SAR).** SICD 복소 데이터를 직접 파싱한다. |
