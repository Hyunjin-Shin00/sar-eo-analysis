# sar/sentinel-1/change-detection/coherence

**CCD** — 사건 전후 코히런스 저하로 피해를 가림. 건물 붕괴·침수처럼 산란 구조가 바뀌는 변화에 민감.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `analyze_coh.py` | 八戸線 本八戸~小中野 고가교 — 2025-12-08 青森県東方沖 지진 결맞음 변화 검정. | GeoTIFF · shp/GeoJSON | GeoTIFF · CSV · NumPy · 텍스트/로그 |
| `ccd_analysis_left.py` | Coherence Change Detection (CCD) — 지진 피해 예비분석 [DISCLAIMER] 현장 미검증 예비분석. 확정 피해 판정 아님. | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |
| `ccd_analysis_right.py` | 우측 궤도 코히런스 변화탐지 — 사건 전후 저하 구역 추출 | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |
| `coh_change.py` | 결맞음 변화 탐지 (Coherence Change Detection) — 2026 네팔 홍수 | GeoTIFF | — |
| `null_distribution.py` | 八戸線 결맞음 저하의 유의성을 두 갈래로 굳힘. | shp/GeoJSON | CSV |
| `null_distribution_rail.py` | 결정적 검증 — 장면 안 모든 철도 회랑에 같은 400 m 창 탐색을 돌림. | shp/GeoJSON | CSV |
| `profile_along_track.py` | 八戸線 고가교 결맞음 변화의 '위치'를 봄. | shp/GeoJSON | CSV |
| `run_coh.sh` | 八戸線 本八戸~小中野 고가교 — 2025-12-08 青森県東方沖 지진(Mj7.5, 八戸 진도 6강). 약 20개소 손상, 第2柏崎高架橋 약 400 m 기둥 曲げ破壊, 12/30 전선 재개. | — | — |
| `run_coh_pairs.sh` | 결맞음 페어 일괄 처리(범용). 사용: run_coh_pairs.sh <SAFE루트> <출력접두> <subswath> "<AOI wkt>" <cohAz> <cohRg> <nRg> <pix> <a:b | — | — |
| `s1_ccd.py` | S1 코히런스 변화탐지 + 진폭 변화 (Sentinel-1). N2 CCD와 동일 산출 구성. | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `DATA_ROOT` | 원본·중간 산출물이 놓인 데이터 루트 |
| `N_RAND` | 코드 참조 |
| `RAD` | 코드 참조 |
| `WORK_ROOT` | 작업 디렉터리 루트 |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `ccd_analysis_left.py` | `WORK_DIR` | `<DATA_ROOT>\Venezuela\left` |
|  | `FILE_PRE` | `20260611_20260618_Orb_Stack_Ifg_Deb_Flt_IW1_TC.tif` |
|  | `FILE_CO` | `20260618_20260624_Orb_Stack_Ifg_Deb_Flt_TC.tif` |
|  | `OUTPUT_DIR` | `<DATA_ROOT>\Venezuela\left\output` |
| `ccd_analysis_right.py` | `OUT` | `<DATA_ROOT>\Venezuela\right\output` |
|  | `FILE_PRE` | `20260613_20260618_Orb_Stack_Ifg_Deb_Flt_IW1_TC.tif` |
|  | `FILE_CO` | `20260618_20260625_C8C0_Orb_Stack_Ifg_Deb_Flt_TC.tif` |
| `coh_change.py` | `COH_MIN` | `0.3` |
| `profile_along_track.py` | `WIN` | `400.0` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `analyze_coh.py`, `null_distribution.py`, `null_distribution_rail.py`
