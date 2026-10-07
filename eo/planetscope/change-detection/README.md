# eo/planetscope/change-detection

시기별 변화 디지타이징 결과를 미터 단위로 계량함. 산지 절토면은 나지와 분광이 비슷해 자동 분류가 흔들리므로, 대상이 선형이고 시기가 적을 때는 손으로 그리고 계산만 코드로 하는 편이 정확함.

## 처리 흐름

```mermaid
flowchart LR
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    ps[("PlanetScope PSScene 8밴드 SR — 7시기 (2024.04~2026.09)")]
    mdl[("OSM 군사분계선 선형")]
    udm["UDM2 마스크로 구름·그림자 제거"]
    str["시기 간 동일 스트레치 적용 — 색감 흔들림 제거"]
    dig["절토·성토 구간 LineString 디지타이징 (피처 2 → 8)"]
    prj["EPSG:5179 투영 — 미터 단위 연장·거리"]
    out(["시기별 누적 연장 · 증가분 · MDL 최단거리"])
    ps --> udm
    udm --> str
    str --> dig
    mdl --> prj
    dig --> prj
    prj --> out
    class ps data
    class mdl data
    class udm proc
    class str proc
    class dig proc
    class prj proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `measure_construction.py` | 시기별 공사현황 선형(shapefile)에서 누적 연장과 군사분계선까지 최단거리를 산출함. | shp/GeoJSON · 파일 묶음 | CSV |

## 주요 인자

- `measure_construction.py` — `--csv` `--mdl` `--works`
