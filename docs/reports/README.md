# docs/reports

연구개발계획서·결과보고서·분석자료를 마크다운으로 옮긴 것.

**원문(PDF·PPTX·DOCX)은 사내 자료라 올리지 않고 내용만 담았다.**
고객사명·담당자 실명·내부 일정·참여율은 뺐고, 기술 내용과 수치는 원문 그대로다.

| 문서 | 종류 | 내용 | 관련 코드 |
|---|---|---|---|
| [`arctic-route-rnd-plan.md`](arctic-route-rnd-plan.md) | 연구개발계획서 | 다중센서 해빙 정보체계와 항로 위험지수. 센서별 한계 비교표, 표준 제품 정확도, 평가 지표 | [`passive-microwave/sea-ice/`](../../passive-microwave/sea-ice/) |
| [`dtm-rnd-report.md`](dtm-rnd-report.md) | 결과보고서 | 저비용 5~10 m DTM 제작 — InSAR · 스테레오 · LiDAR 세 경로 비교. 평균 오차 0.7 m (0.76%) | [`applications/dem-generation/`](../../applications/dem-generation/) |
| [`bluebon-pointing-error.md`](bluebon-pointing-error.md) | 분석보고서 | 포인팅 오차 ↔ 궤도·자세 메타데이터 상관분석. 유의 변수와 **설명하지 못한 이상치** | [`eo/bluebon/pointing/`](../../eo/bluebon/pointing/) |
| [`smelter-rnd-plan.md`](smelter-rnd-plan.md) | 연구개발계획서 | 구리 제련소 열원 모니터링. 산출물·자원·작업상 어려움 | [`eo/sentinel-2/thermal-anomaly/`](../../eo/sentinel-2/thermal-anomaly/) |
| [`onboard-processor-tradeoff.md`](onboard-processor-tradeoff.md) | 분석자료 | 온보드 프로세서 탑재 손익. 4개 시나리오, **추가 공전 3회면 역전** | — |

## 읽는 법

계획서는 "하려는 것", 결과보고서는 "한 것과 안 된 것"이다.
수치가 있는 결론은 그대로 옮겼고, **한계와 미해결 항목도 원문대로 남겼다** —
DTM 의 정량 검증지가 한 곳뿐이었다는 점, 포인팅 이상치의 원인을 찾지 못했다는 점이 그렇다.
