# sar/sentinel-1/water/soil-moisture/korea_gao2017

Gao 2017 (S1+S2 변화탐지) — 국내 가평·화성 적용.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `01_download.sh` | ASF에서 Sentinel-1 GRD 다운로드 (~/.netrc Earthdata 인증), 4개 병렬 | — | — |
| `02_snap_batch.sh` | 다운로드된 GRD 전부를 SNAP 그래프로 처리 (Gao 2017 전처리: 궤도·열잡음·σ0 보정·SRTM 30m 지형보정, 스페클필터 없음, 10 m), 인자 r=역순 | — | — |
| `03_s2_ndvi.py` | Sentinel-2 L2A NDVI (Gao et al. 2017: NDVI=(B08−B04)/(B08+B04), 구름 마스크 적용) → 100 m 공통격자. | GeoTIFF | CSV |
| `04_gao2017_change_detection.py` | Gao, Zribi, Escorihuela & Baghdadi (2017) Sensors 17(9):1966, doi:10.3390/s17091966 | GeoTIFF · CSV · NumPy · 파일 묶음 | GeoTIFF · CSV · 텍스트/로그 |
| `05_validate_figs.py` | Gao(2017) 방법 1·2 결과 검증(RDA 현장) + 그림. 논문 보고값과 같은 지표(RMSE, ubRMSE, bias, R). | CSV · NumPy · JSON | CSV · PNG 그림 |
| `06_region_rain_response.py` | 지역 평균 위성 토양수분(Gao 방법1) vs 선행강수지수(API, k=0.8) — 관측소 한 점이 아닌 지도 전체의 강수 반응 검증. | CSV | CSV · PNG 그림 |
| `site_config.py` | 지점 설정. 환경변수 SITE=GP/HS (기본 GP) | CSV | — |
