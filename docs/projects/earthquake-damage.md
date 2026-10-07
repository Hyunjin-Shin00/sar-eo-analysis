# earthquake-damage — Sentinel-1 DInSAR + CCD 지진 피해 분석 (2026 베네수엘라 M7.5)

SNAP(GUI)으로 만든 간섭도·코히런스를 받아 ① 코히런스 변화탐지(CCD)로 건물·도로 피해 의심구역을 등급화하고,
② DInSAR 언랩 위상을 LOS 변위로 바꿔 지표 이동을 보고, ③ Copernicus EMS(EMSR884) 피해판독·지반변위 제품과 교차검증함.

## 구성
| 폴더 | 파일 | 내용 |
|---|---|---|
| 01_dinsar | SNAP_처리체인_및_SNAPHU_파라미터.md, snaphu.conf | SNAP 처리 체인(Split→Orbit→Back-Geocoding→Interferogram→Deburst→Goldstein→TC→Snaphu Export)과 실제 언랩 설정 (DEFO/MCF, 10×10 타일) |
| 01_dinsar | slc_to_amp_geotiff.py | S1 SLC zip → 진폭(dB) GeoTIFF. 버스트 유효구간 마스크, 유효 샘플 수로 나누는 멀티룩, GCP-TPS 근사 지오코딩 |
| 02_ccd | ccd_analysis_left.py / ccd_analysis_right.py | ΔCoh = γ_pre − γ_co, γ_pre 저코히런스 마스크, 3등급(LOW≥0.2/MID≥0.4/HIGH≥0.6) 래스터·비교도 |
| 03_damage | catia_la_mar_buildings.py | AOI 건물 폴리곤 확보 (MS Global ML Building Footprints → 실패 시 OSM Overpass) |
| 03_damage | catia_lamar_ccd_analysis.py | 해안 도심 AOI 집중분석, 2등급 재분류(RISK 0.1≤ΔCoh<0.4 / HIGH≥0.4), EMSR884 피해건물 교차 |
| 03_damage | gis_quant_analysis_v2.py | 장면 전체 CCD×EMSR884×도로×단층 GIS 정량분석 |
| 03_damage | catia_lamar_final_report.py, fusion_report_v5.py | CCD+DInSAR 종합 보고서, 광학 AI·SAR·EMS 융합 HTML 보고서 |
| 04_aux | extract_venezuela_faults.py | GEM Global Active Faults 에서 베네수엘라 구간 추출 |
| 05_verify | recalc_ccd_emsr.py, recalc_dinsar.py, ramp_check.py, cv_check.py | 핸드오프 시 재계산 검증 (면적·적중률·기준선·EMS GRM 상관·CV AUC) |
| 05_verify | fig_validation.py, fig_left_dinsar.py | 검증 그림, 1일 페어 변위 지도 |

## 실행 메모
- 원 스크립트는 Windows 워크스테이션에서 작성됨. 경로 상수의 `<DATA_ROOT>` 를 데이터 루트로 바꿔야 함.
  05_verify 스크립트는 환경변수 `DATA_ROOT` 를 읽음.
- `slc_to_amp_geotiff.py` 는 `$CONDA_PREFIX/share/proj` 를 PROJ_DATA 로 지정한다 (안 하면 GDAL 이 EPSG 를 못 읽는 env 가 있음).
- 광학 건물 피해 분류 v7(로지스틱 회귀 + Gradient Boosting) 의 **학습·생성 코드는 포함돼 있지 않다** (원 작업 PC에만 존재). 산출물(gpkg/joblib/json)만 있고, `cv_check.py` 로 학습셋 구성(15,028/86/14,942)과 CV AUC(≈0.83)만 근사 재현함.
- 등급 임계치가 두 벌(3등급 0.2/0.4/0.6, 2등급 0.1/0.4) 있으니 결과 인용 시 구분할 것.
- 모든 결과는 현장 미검증 예비분석임.
