# applications/subsidence-warning/02_fusion_poc

InSAR 변위 + 지반 등급 + 지하수를 융합해 지표를 만듦.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `analyze_options.py` | 의사결정용 비교표 생성 — ★최종 선택은 사용자(클로드 단독확정 금지). | CSV | CSV |
| `config.py` | 지반침하·함몰 워닝 PoC — 공통 설정(CONFIG) | CSV · SHP | — |
| `events.py` | 싱크홀 발생점 좌표 (사용자 제공) — STEP 3 (A)제약 검증용. | — | — |
| `geol_grade.py` | 지질 기반 지반등급 산정 + 시추공 등급과 융합 (시추공 공백 보완). | CSV · shp/GeoJSON | CSV |
| `indicators.py` | 변위 3지표 산정 (STEP2)  [6·22 자료 p.7] | — | — |
| `loaders.py` | PS/SBAS 로더 + 캐시. 좌표 WGS84 -> UTM52N(m). 시계열 D컬럼 -> 누적변위 행렬. | CSV · NumPy | NumPy |
| `sasang_filter_opt.py` | 사상 AOI(AOI.xlsx 박스) 한정 — 사고 버퍼 vs 비사고 대조군 판별 필터 최적화. | CSV · PNG | CSV · PNG 그림 |
| `step1_ground_grade.py` | STEP 1 — 지반등급 판정 (정적 지반조건)  [6·22 자료 p.5] | CSV | CSV |
| `step2_fusion.py` | STEP 2 — 변위 3지표 × α 융합 → 최종 위험등급 | CSV | CSV |
| `step3_analysis.py` | STEP 3 — 싱크홀 발생지 vs 미발생지 차이분석 + (A)제약 검증 | CSV | CSV · PNG 그림 |
| `subsidence_list_analysis.py` | 과제②: 정제 지반침하 사고 리스트 전체에 '기존 위험판정 기준'을 동일 적용 | CSV | CSV · PNG 그림 |
