# eo/sentinel-2/burn-severity

**dNBR** 산불 피해등급 — 연소 후 NIR 감소·SWIR 증가를 씀.

## 처리 흐름

```mermaid
flowchart LR
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    s2[("Sentinel-2 화재 전·후")]
    geo[("GK2A · GOCI-II 정지궤도")]
    met[("기상: 풍향·풍속·습도·지표온도")]
    cld["OmniCloudMask 구름·연기 제거"]
    nbr["NBR = (NIR − SWIR) / (NIR + SWIR)"]
    dnbr["dNBR = NBR_pre − NBR_post"]
    cls{"USGS 5등급 임계 분류"}
    hot["시간 단위 화점·연기 확산 추적"]
    out(["피해 등급도 · 등급별 면적 · 확산 방향 대조"])
    s2 --> cld
    cld --> nbr
    nbr --> dnbr
    dnbr --> cls
    geo --> hot
    met --> hot
    cls --> out
    hot --> out
    class s2 data
    class geo data
    class met data
    class cld proc
    class nbr proc
    class dnbr proc
    class cls dec
    class hot proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`notebooks/`](notebooks/) | 영상 수집 → 구름·연기 마스킹 → dNBR → USGS 5등급 분류. |
