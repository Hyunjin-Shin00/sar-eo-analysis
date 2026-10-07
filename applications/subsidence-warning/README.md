# applications/subsidence-warning

지반침하 조기경보 — 사고 자료 수집부터 규칙·리드타임 백테스트까지.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    sbas[("SBAS 시계열 — 간섭쌍 824 · 6,250점 × 212에폭")]
    bore[("시추공 92,307공 SPT N값 + 지질도")]
    acc[("지반침하 사고기록")]
    alpha["지반등급 α — 연약 0.6 / 주의 0.8 / 양호 1.0"]
    idx["3지표 × α — 속도 · 최근 2년 누적 · 2구간 추세"]
    scr["SBAS hotspot 스크리닝 → 반경 30 m PS 확인 2단 결합"]
    fuse["역속도법(Fukuzono) 붕괴예상시점 + DBSCAN eps 100 m 클러스터 알람"]
    wf["워크포워드 12지표 → 72 파생 (증가량 · 표준화)"]
    gate{"1단 게이트 — 배경 대비 백분위 · Youden"}
    alarm{"2단 경보 — AND · K회 연속"}
    val["대조군 400곳 · LOAO · GBM 비교 · 광역 확장"]
    out(["정상/주의/위험 판정 · 리드타임 · 위험구역 GeoJSON"])
    bore --> alpha
    sbas --> idx
    alpha --> idx
    idx --> scr
    scr --> fuse
    fuse --> wf
    wf --> gate
    gate --> alarm
    acc --> val
    alarm --> val
    val --> out
    class sbas data
    class bore data
    class acc data
    class alpha proc
    class idx proc
    class scr proc
    class fuse proc
    class wf proc
    class gate dec
    class alarm dec
    class val proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`01_accident_data/`](01_accident_data/) | 지반침하 사고 이력 수집·지오코딩 (공공데이터). |
| [`02_fusion_poc/`](02_fusion_poc/) | InSAR 변위 + 지반 등급 + 지하수를 융합해 지표를 만듦. |
| [`03_alarm_pipeline/`](03_alarm_pipeline/) | AOI 단위 경보 파이프라인 — 속도 역수(invvel) 기반 판정. |
| [`04_leadtime_rules/`](04_leadtime_rules/) | 경보 규칙과 **리드타임 백테스트**. 과적합 검사(LOAO)도 함께. |
| [`05_point_grade_demo/`](05_point_grade_demo/) | 지점 등급 판정 데모. |
| [`06_recheck/`](06_recheck/) | 판정 결과 재검증. |
| [`hotspots/`](hotspots/) | 침하 핫스팟 추출·검증. |
