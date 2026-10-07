# sar/nextsat-2/change-detection

N2 진폭변화탐지(ACD) — 세 기법 중 유일하게 구조가 남는 관측.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    subgraph g0["위상 InSAR"]
    direction TB
    spoof["ISCE2 stripmapApp 에 CSK 센서로 위장 — N2 메타데이터 주입"]
    own["궤도 기하부터 직접 구현한 자체 파이썬 파이프라인"]
    topsapp["Sentinel-1 은 공식 ISCE2 topsApp + snaphu"]
    end
    subgraph g1["진폭 기반"]
    direction TB
    ot["Offset Tracking — NCC 정합 + 상관 피크 포물선 보간 (1/10~1/20 화소)"]
    acd["ACD — 진폭 → 멀티룩 → 지오코딩 → 로그비 dB"]
    end
    n2[("NEXTSat-2 SLC")]
    s1[("Sentinel-1 SLC")]
    lid[("LiDAR DEM · 정사영상 5 m")]
    fit{"페어 적합성 — 동일 궤도·룩 · dinc · Bperp/Bcrit · 시간차"}
    sea["DEM 기반 해수역 마스킹 (3기법 공통)"]
    sign{"부호 규약 합성신호 검증 — OT range(+) 는 멀어짐, InSAR LOS(+) 는 가까워짐"}
    ctrl{"코레지 refinement 대조실험 — WSL DrvFs vs 리눅스 네이티브 FS"}
    tide["갯벌 조위별 침수·노출 비교 (동일 5 m 격자)"]
    out(["변위·변화 지도 3종 · 기법 간 결론 일치 여부 · 조위별 노출 도면"])
    n2 --> fit
    s1 --> fit
    fit --> spoof
    fit --> own
    fit --> topsapp
    fit --> ot
    fit --> acd
    spoof --> sea
    own --> sea
    topsapp --> sea
    ot --> sea
    acd --> sea
    sea --> sign
    sign --> ctrl
    lid --> tide
    ctrl --> out
    tide --> out
    class n2 data
    class s1 data
    class lid data
    class fit dec
    class spoof proc
    class own proc
    class topsapp proc
    class ot proc
    class acd proc
    class sea proc
    class sign dec
    class ctrl dec
    class tide proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `acd_pair.py` | N2 ACD 진폭 로그비 0515->0614 (InSAR/OT와 동일 쌍). SSC 진폭, 동일 멀티룩·지오코딩. | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `acd_right_look.py` | N2 A_R ACD: 진폭 지오코딩(0402,0529,0613) + 로그비(0402->0613, 0529->0613). SSC, 동일 처리. | GeoTIFF | GeoTIFF · 텍스트/로그 |
