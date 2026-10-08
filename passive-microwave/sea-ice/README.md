# passive-microwave/sea-ice

해빙 농도(SIC)·두께(SIT)·표류. OSI-SAF · NSIDC · SMOS.

## 처리 흐름

```mermaid
flowchart LR
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    sic[("OSI-SAF 해빙농도 SIC (NetCDF)")]
    sit[("NSIDC · SMOS 해빙두께 SIT")]
    gfw[("Global Fishing Watch 선박 이동")]
    dl["자동 수집·처리 파이프라인"]
    grid["공간·시간 정합 → 월별 시계열 융합"]
    open{"SIC 15% 기준 항로 개방 판정 — 서부 · 중부 · 동부"}
    trend["2012–2026 장기 추세 분석"]
    out(["연도별·구간별 개방 시기 · 추세"])
    sic --> dl
    sit --> dl
    gfw --> dl
    dl --> grid
    grid --> open
    open --> trend
    trend --> out
    class sic data
    class sit data
    class gfw data
    class dl proc
    class grid proc
    class open dec
    class trend proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

<!-- crosslink -->
### 이 기법을 쓴 사례

- 여기 코드는 어느 자료에도 쓸 수 있는 처리임. 아래는 실제로 적용한 사건별 분석임

| 사례 | 내용 |
|---|---|
| [`applications/arctic-route/`](../../applications/arctic-route/) | 북극항로 개방 시기 정량화 |
<!-- crosslink -->

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`convert/`](convert/) | NetCDF → GeoTIFF (극지 투영 처리). |
| [`download/`](download/) | 원자료 자동 수집. |
| [`plot/`](plot/) | 월별 지도·표류 벡터장. |
