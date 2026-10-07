# applications

**응용.** 위성 산출물을 받아 판정·경보·보고로 바꾸는 코드. 특정 센서에 묶이지 않음.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`arctic-route/`](arctic-route/) | 해빙 자료 + 선박 통항으로 북극항로 개방 시기를 산출함. |
| [`dam-monitoring/`](dam-monitoring/) | 자연댐 변위 모니터링 — 성분 분해와 계절성 분석. |
| [`dem-generation/`](dem-generation/) | **DTM 제작.** 고해상도 지형자료가 없는 지역에서 저비용으로 5~10 m DTM 을 만들 수 있는지 — InSAR DSM · 스테레오 · LiDAR 세 경로를 비교함. DSM 생성은 `sar/sentinel-1/` 과 SNAP 에서, 여기엔 LiDAR 처리와 정확도 검증만 둠. |
| [`disaster-damage/`](disaster-damage/) | 재난 피해 판정 — 위성 산출물을 피해 등급·노출 통계로 바꿈. |
| [`rail-hazard/`](rail-hazard/) | 철도 재해 SAR 탐지 타당성 — 대상 선정부터 탐지 가능성 종합까지. |
| [`subsidence-warning/`](subsidence-warning/) | 지반침하 조기경보 — 사고 자료 수집부터 규칙·리드타임 백테스트까지. |
| [`underwriting/`](underwriting/) | 공간정보 기반 중소 공장 인수심사 — 건물통합정보·업종 매칭. |
