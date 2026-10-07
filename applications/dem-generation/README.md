# applications/dem-generation

**DTM 제작.** 고해상도 지형자료가 없는 지역에서 저비용으로 5~10 m DTM 을 만들 수 있는지 — InSAR DSM · 스테레오 · LiDAR 세 경로를 비교함. DSM 생성은 `sar/sentinel-1/` 과 SNAP 에서, 여기엔 LiDAR 처리와 정확도 검증만 둠.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    subgraph g0["DSM 제작 경로"]
    direction TB
    s1["Sentinel-1 InSAR — Bperp 150~300 m · 시간기선 최소"]
    csk["COSMO-SkyMed InSAR"]
    spot["SPOT-5 HRS 전·후방 스테레오"]
    end
    chain["SNAP: split → orbit → back-geocoding → 간섭도 → deburst → filter → unwrap → phase-to-elevation → TC"]
    dsm["DSM 생성"]
    slope{"slope 필터 — 경사 10° 초과는 건물·식생으로 제거"}
    fill["단계적 보간으로 빈 공간 채움 (close gaps)"]
    smooth["가우시안 평활화"]
    gt[("멕시코 0.5 m LiDAR DSM/DTM (참값)")]
    val{"정량 검증 — 평균 0.7 m (0.76%) · 최대 30 m"}
    out(["5~14 m 급 DTM · 검증 보고"])
    s1 --> chain
    chain --> dsm
    csk --> dsm
    spot --> dsm
    dsm --> slope
    slope --> fill
    fill --> smooth
    gt --> val
    smooth --> val
    val --> out
    class s1 proc
    class csk proc
    class spot proc
    class chain proc
    class dsm proc
    class slope dec
    class fill proc
    class smooth proc
    class gt data
    class val dec
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`lidar/`](lidar/) | LiDAR 포인트/래스터 수집·병합·재투영 — 검증용 참값(0.5 m) 준비. |
| [`validation/`](validation/) | 제작 DTM 과 참값의 오차 산출. 멕시코 LiDAR 지역이 유일한 정량 검증지였음. |
