# sar/sentinel-1/water/flood

**홍수 탐지.** Edge-Otsu 자동 임계값으로 수체를 분리하고 전후 차분으로 침수역을 냄.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    s1[("Sentinel-1 GRD 사전·사후")]
    dem[("Copernicus DEM 30 m")]
    jrc[("JRC 영구수체")]
    pre["SNAP 전처리: 궤도 · 열잡음 · σ⁰ · Lee-sigma · 지형보정 10 m · dB"]
    cand["−20 dB 초기 수체 후보"]
    edge["경계 팽창−침식 + 5화소 버퍼"]
    otsu{"버퍼 내 화소만으로 Otsu 임계"}
    slope{"경사 ≥ 5° 는 육지로 강제"}
    chg["사후 ∧ ¬사전 = GAIN / 사전 ∧ ¬사후 = LOSS"]
    perm["영구수체 차분 → 신규 침수"]
    depth["DEM 결합 침수심 추정 · 등급화"]
    area(["침수 면적 km² · 침수심 등급도"])
    val(["KuroSiwo 67타일 P/R/F1/IoU 검증"])
    s1 --> pre
    pre --> cand
    cand --> edge
    edge --> otsu
    dem --> slope
    otsu --> slope
    slope --> chg
    jrc --> perm
    chg --> perm
    perm --> depth
    depth --> area
    perm --> val
    class s1 data
    class dem data
    class jrc data
    class pre proc
    class cand proc
    class edge proc
    class otsu dec
    class slope dec
    class chg proc
    class perm proc
    class depth proc
    class area out
    class val out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`notebooks/`](notebooks/) | 임계값 전략 비교·결과 검토용 노트북. |
| [`satchat/`](satchat/) | 서비스 모듈판 — SNAP 비의존(전처리된 dB GeoTIFF 입력) + KuroSiwo 벤치마크 평가. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `analyse_flood_grd.py` | The actual analysis: what can free Sentinel-1 see of this disaster, measured. | GeoTIFF · JSON | GeoTIFF · JSON · 텍스트/로그 |
| `db_geocode.py` | 날짜별 후방산란(dB)을 간섭도와 같은 레이더 격자로 만들고 ISCE 메타데이터를 붙임. | GeoTIFF | 텍스트/로그 |
| `flood_detect_slc.py` | 홍수 피해구역 탐지 (강임계 + 대조군 + 군집필터) — 2026 네팔 홍수 | GeoTIFF · JSON | — |
| `flood_map.py` | 탐지 결과 지도 + 주요 군집 좌표. usage: flood_map.py <TRACK> | GeoTIFF · JSON | PNG 그림 · JSON |
| `otsu_flood.py` | Otsu 임계 기반 홍수 피해구역 분할 — 2026 네팔 홍수 | GeoTIFF · JSON | — |
| `s1_processor.py` | Sentinel-1 자동 수체 탐지 및 홍수 탐지 통합 파이프라인 파일명: s1_processor7.py (전처리 전에 인셋: 자동 NaN행 기반 트리밍) | GeoTIFF · shp/GeoJSON | GeoTIFF · shp/GeoJSON · 텍스트/로그 |
| `s1_processor_benchmark.py` | 벤치마크 평가판 — 전처리된 GeoTIFF 입력으로 수체 마스크만 산출 (Sen1Flood11/KuroSiwo) | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `waterbody_mask.py` | 수체 마스크만 산출하는 경량 버전 (홍수 차분 없음) | GeoTIFF · shp/GeoJSON · 파일 묶음 | GeoTIFF · 텍스트/로그 |

## 주요 인자

- `s1_processor.py` — `--after_mask` `--aoi_shp` `--before_mask` `--dem_path` `--edge_buffer` `--flood_detection` `--flood_stats` `--initial_db_threshold` `--input_zips` `--output_dir` `--polarization` `--slope_path`
- `s1_processor_benchmark.py` — `--edge_buffer` `--initial_db_threshold` `--input_tifs` `--output_dir` `--polarization`
