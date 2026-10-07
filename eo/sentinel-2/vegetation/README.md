# eo/sentinel-2/vegetation

식생지수 시계열 — NDVI·EVI. 건조 기후에서는 일반 임계값이 작동하지 않아 다시 잡아야 함.

## 처리 흐름

```mermaid
flowchart LR
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    s2[("Sentinel-2 — 연중 구름 30% 미만")]
    dsm[("ALOS DSM")]
    gmw[("GMW 맹그로브 폴리곤")]
    med["median 합성 영상 제작"]
    lim{"후보 제한 — DSM 30 m 미만 ∧ NDVI 0.15 초과"}
    feat["입력 변수 — NDVI · MVI 등 다수 지수"]
    rf["Random Forest 분류 (GEE)"]
    ts["2020–2024 월별·연별 NDVI 시계열"]
    out(["맹그로브 분포도 · 태풍 전후 회복 추적"])
    s2 --> med
    med --> lim
    dsm --> lim
    lim --> feat
    feat --> rf
    gmw --> rf
    rf --> ts
    ts --> out
    class s2 data
    class dsm data
    class gmw data
    class med proc
    class lim dec
    class feat proc
    class rf proc
    class ts proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `evi_highres.ipynb` | 고해상도 광학 EVI 산출 — 건조지역 임계값 조정 | GeoTIFF | GeoTIFF |
| `ndvi_timeseries.ipynb` | Sentinel-2 NDVI 시계열 산출 — 도시 녹지 분류 | GeoTIFF | GeoTIFF · 텍스트/로그 |
