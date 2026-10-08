# applications/subsidence-warning/05_point_grade_demo

지점 등급 판정 데모.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `apply_risk_rule.py` | SBAS 결과 → 위험규칙(T2k) 적용 → 위험구역 산출 — 부산 사상~하단 | GeoTIFF · CSV · JSON | shp/GeoJSON · JSON · 텍스트/로그 · GeoTIFF |
| `grade_point.py` | 지점 등급 판정 — 정상 / 주의 / 위험 — 부산 사상~하단 | CSV · NumPy · JSON | JSON |
| `make_polygons.py` | AOI(분석 영역)·관심 지역 폴리곤을 GeoJSON 으로 뽑음. | GEOJSON | JSON |
| `run_sbas_demo.py` | 데모용 고속 SBAS — 부산 사상~하단 (Sentinel-1 ASC track 54) | CSV · NumPy · JSON · 파일 묶음 | CSV · shp/GeoJSON · NumPy · 텍스트/로그 |
| `zone_danger.py` | 위험 구역을 폴리곤으로 그린 보고서 지도. | NumPy · JSON | PNG 그림 · 텍스트/로그 |

## 주요 인자

- `apply_risk_rule.py` — `--asof` `--grid` `--min_area_ha` `--out` `--sbas` `--smooth`
- `grade_point.py` — `--asof` `--lat` `--lon` `--out` `--quiet` `--sbas`
- `make_polygons.py` — `--addr` `--handover` `--lat` `--lon` `--name` `--out` `--side`
- `run_sbas_demo.py` — `--cache` `--jobs` `--out` `--precomputed` `--shp` `--snaphu` `--verify`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `CLAB_ROOT` | 지반침하 과제 트리 루트 |
| `SNAPHU_BIN` | snaphu 실행 파일 경로 |

### 진입점

```bash
python apply_risk_rule.py 
```
SBAS 결과 → 위험규칙(T2k) 적용 → 위험구역 산출 — 부산 사상~하단 입력 : 02_sbas/out/Busan_Sasang_Hadan_sbas_ps_v.csv (라이브 or 폴백, 어느 쪽이든 동일) 규칙 : rule_t2k_sasang.json (coh0.3

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--sbas` |  |  |  |
| `--grid` |  | `20.0` | 위험 판정 격자 간격(m) |
| `--smooth` |  | `10.0` | 구역 경계 정리 반경(m). 계단형 경계를 닫음. 0=원본 격자 |
| `--min_area_ha` |  | `0.05` | 이 면적 미만의 파편 구역은 제외(제외 개수는 요약에 기록) |
| `--asof` |  |  | 판정 기준 시점(소수연도, 예 2021.0 = 2020년 말까지의 관측만 사용). 미지정=최신. 지정 시 출력 파일명에 _as |
| `--out` |  |  |  |

```bash
python grade_point.py --lat <값> --lon <값>
```
지점 등급 판정 — 정상 / 주의 / 위험 — 부산 사상~하단 입력 : input/Busan_Sasang_Hadan_sbas_ps_v.csv SBAS 시계열 input/rule_grade.json 판정 규칙(임계·연속횟수) input/rule_grade_bg.npz 배

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--lat` | ● |  |  |
| `--lon` | ● |  |  |
| `--asof` |  |  | 판정 기준일 YYYY-MM-DD (기본: 최종 관측) |
| `--sbas` |  |  |  |
| `--out` |  |  | 판정 결과 JSON 경로 |
| `--quiet` |  |  |  |

```bash
python make_polygons.py 
```
AOI(분석 영역)·관심 지역 폴리곤을 GeoJSON 으로 뽑음. 전달본(handover_20260827)이 보고서 지도를 그릴 때 쓰는 것과 같은 정읨. · 분석 영역 = 판정 격자(50 m)의 바깥 테두리 — 보고서 지도의 흰 점선 · 관심 지역 = 중심 좌표 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--handover` |  |  | 전달본 폴더 (demo/_lib 가 들어 있는 곳) |
| `--addr` |  | `부산 사상구 새벽로 87` |  |
| `--name` |  | `사상 새벽로87 신축공사` |  |
| `--lat` |  |  |  |
| `--lon` |  |  |  |
| `--side` |  | `50.0` | 관심 지역 한 변 (m) |
| `--out` |  |  |  |

```bash
python make_report.py 
```
주소 + 기준일 → 지반침하 위험 보고서 PDF (+ 주의·위험 구역 GeoJSON) 세 단계를 한 번에 돌림. ① 주소 → 좌표 지오코딩 → 등급 판정 → 보고서 본문 (report_site) ② 주의 구역(누적)·위험 구역을 지도에 두 겹으로 그리고 GeoJSON

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--addr` |  | `부산 사상구 새벽로 87` |  |
| `--asof` |  | `2024-06-30` |  |
| `--name` |  | `사상 새벽로87 신축공사` |  |
| `--out` |  |  |  |
| `--list` |  |  | 가능한 기준일 목록 |

```bash
python report_site.py --addr <값>
```
지역(사상구) 기준 지반침하 보고서 + 공사장(50 m 폴리곤) 개별 판정. usage: report_site.py --addr "부산광역시 사상구 새벽로 87" [--lat .. --lon ..] [--name "○○ 신축공사"] [--side 50] [--out P

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--addr` | ● |  |  |
| `--lat` |  |  |  |
| `--lon` |  |  |  |
| `--name` |  | `공사현장` |  |
| `--side` |  | `50.0` |  |
| `--asof` |  |  | 판정 기준일 YYYY-MM-DD (기본: 오늘) |
| `--out` |  |  |  |

```bash
python run_sbas_demo.py 
```
데모용 고속 SBAS — 부산 사상~하단 (Sentinel-1 ASC track 54) PROJ 운영 파이프라인(analysis/insar_bin/run_sbas.py)과 **수식·파라미터 동일**. 차이는 입력과 병렬화뿐: · 입력 : 원본 merged 스택(115G

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--precomputed` |  |  | 계산 없이 사전결과 사용(폴백) |
| `--cache` |  |  | unwrap 캐시 재사용 |
| `--verify` |  |  | 운영(PROJ) 결과와 일치 검증 |
| `--jobs` |  |  |  |
| `--shp` |  |  | SHP 도 출력(느림) |
| `--snaphu` |  |  | snaphu 실행파일 경로(기본: $SNAPHU_BIN → PATH → GMTSAR 기본위치) |
| `--out` |  |  |  |
