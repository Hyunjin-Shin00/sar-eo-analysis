# sar/sentinel-1/water/soil-moisture

후방산란 변화로 표층 토양수분을 산출함. 논문 3편을 수정 없이 재현함.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    subgraph g0["재현 대상 3편"]
    direction TB
    uk["영국 Maslanka 2022 — TU Wien 변화탐지"]
    us["미국 Ma 2020 — Oh-2004 + Water Cloud Model 격자탐색 역산"]
    kr["국내 Gao 2017 — NDVI 등급별 건조기준 / 시간차분"]
    end
    rtc[("Planetary Computer S1 RTC — 관측소 주변 3.2 km 창만 원격 판독")]
    norm["화소별 β 로 40° 정규화 (중앙 −0.092 dB/°)"]
    agg["10 m → 100 / 250 / 500 / 1000 m 선형 평균"]
    rssm["건조·습윤 기준 P10 · P90 ± 범위/8 → rSSM 0–100 %"]
    val{"COSMOS-UK 3개소 · SCAN · 농촌진흥청 10 cm 비교 — r² · RMSE 12조합"}
    api{"보조 검증 — 지도 전체 평균 vs 선행강수지수 API (k = 0.8)"}
    out(["상대 토양수분 지도 · 논문 표 대조 결과"])
    rtc --> uk
    uk --> norm
    norm --> agg
    agg --> rssm
    rssm --> val
    us --> val
    kr --> val
    val --> api
    api --> out
    class uk proc
    class us proc
    class kr proc
    class rtc data
    class norm proc
    class agg proc
    class rssm proc
    class val dec
    class api dec
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`korea_gao2017/`](korea_gao2017/) | Gao 2017 (S1+S2 변화탐지) — 국내 가평·화성 적용. |
| [`pinn_cho2026/`](pinn_cho2026/) | Cho 2026 PINN-WCM 재구현 시도 (동료심사 전 논문, 검증용). |
| [`uk_maslanka2022/`](uk_maslanka2022/) | Maslanka 2022 (TU Wien 변화탐지) — 영국 COSMOS-UK 재현. |
| [`us_ma2020/`](us_ma2020/) | Ma 2020 (Oh + WCM) — 미국 SCAN 재현. **재현 실패 기록 포함.** |
| [`verify/`](verify/) | 원본 산출물에서 핵심 수치를 다시 계산해 문서와 대조함. |
| [`viz/`](viz/) | 지도 합성·위치 정합 확인용 그림 생성. |
