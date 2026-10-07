# applications/disaster-damage/earthquake/verify

보고서 수치를 원본에서 재계산해 검증한다.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `cv_check.py` | 변동계수(CV) 기준이 보고서 수치와 맞는지 재계산 | shp/GeoJSON · JSON | — |
| `fig_left_dinsar.py` | 좌측 궤도 DInSAR 검증 그림 생성 | GeoTIFF · shp/GeoJSON | PNG 그림 |
| `fig_validation.py` | EMS 판독 대비 검증 그림 생성 | NumPy | PNG 그림 |
| `ramp_check.py` | 언래핑 위상의 잔여 경사(ramp)가 남아 있는지 점검 | NumPy | — |
| `recalc_ccd_emsr.py` | 재계산 1: CCD 면적·EMSR884 교차·v7 분류 교차 (읽기 전용) | GeoTIFF · shp/GeoJSON · JSON | — |
| `recalc_dinsar.py` | 재계산 2: CCD 등급 래스터 · DInSAR 변위 통계 · EMS GRM 비교 (읽기 전용) | GeoTIFF | — |
