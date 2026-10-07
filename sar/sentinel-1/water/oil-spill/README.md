# sar/sentinel-1/water/oil-spill

기름막은 모세관파를 감쇠시켜 어둡게 보인다 — dark spot 탐지.

## 처리 흐름

```mermaid
flowchart LR
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    s1[("Sentinel-1 GRD")]
    wind[("풍속 · 파고")]
    opt[("광학 영상")]
    cal["방사보정 → σ⁰ → 스펙클 필터"]
    dark["dark spot 추출 — 모세관파 감쇠로 Bragg 산란 저하"]
    thr{"풍속 보정 후방산란 임계 — 저풍속 구역 배제"}
    shape["형상·면적·가장자리 특징 산출"]
    cross{"광학 교차 확인으로 오탐 제거"}
    out(["기름막 폴리곤 · 면적"])
    s1 --> cal
    cal --> dark
    wind --> thr
    dark --> thr
    thr --> shape
    shape --> cross
    opt --> cross
    cross --> out
    class s1 data
    class wind data
    class opt data
    class cal proc
    class dark proc
    class thr dec
    class shape proc
    class cross dec
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`notebooks/`](notebooks/) |  |
