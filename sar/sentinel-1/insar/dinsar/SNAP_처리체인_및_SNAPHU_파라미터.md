# DInSAR 지진 변위 분석 — 베네수엘라 2026

## 개요

Sentinel-1 SAR 데이터를 이용한 DInSAR(차분 간섭계) 워크플로.  
2026년 6월 23~24일 베네수엘라 지역 지진 이벤트의 지표 변위(LOS) 탐지 및 지반침하/싱크홀 분석.

---

## 입력 데이터

| 위성 | 취득 시각 (UTC) | 파일 크기 | 모드 |
|------|----------------|-----------|------|
| Sentinel-1A | 2026-06-23 T22:50:50 ~ T22:51:20 | 8.2 GB | IW SLC VV+VH |
| Sentinel-1C | 2026-06-24 T22:49:58 ~ T22:50:25 | 7.5 GB | IW SLC VV+VH |

- **수직 기선 (Perpendicular Baseline):** 86.762 m  
- **파장 (Lambda):** 0.0554658 m (C-band, ~5.5 cm)  
- **시간 기선:** 1일 (지진 전·후 긴급 취득)

### 보조 데이터

```
epicenters/epicenters_2026.shp     — 2026 지진 진앙 포인트 (GIS)
fault/gem-global-active-faults/    — GEM 전 지구 활성 단층선
capa-de-venezuela/Venezuela Esequibo — 베네수엘라 행정 경계
```

---

## SNAP 처리 체인

```
S1A .SAFE + S1C .SAFE
  └─ TOPSAR Split (IW 서브스워스 선택)
  └─ Apply Orbit File
  └─ Back Geocoding (코레지스트레이션 / Stack)
  └─ Interferogram Formation          → i_ifg_VV, q_ifg_VV
  └─ TOPSAR Deburst                   (Deb)
  └─ Goldstein Phase Filtering        (Flt)
  └─ Subset (AOI 자르기)
  └─ Terrain Correction               → *_TC.dim
  └─ Snaphu Export                    → Phase_ifg, coh, snaphu.conf
```

### SNAP 출력 파일

| 파일 | 설명 |
|------|------|
| `20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt.dim` | 필터링된 전체 영역 간섭도 |
| `20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt_TC.dim` | 지형 보정 완료본 |
| `subset_0_of_20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt.dim` | AOI subset (23793 × 13106 px) |

---

## SNAPHU 위상 언래핑

### 파라미터 (전체 영역 기준)

| 항목 | 값 |
|------|-----|
| 대상 파일 | `Phase_ifg_VV_23Jun2026_24Jun2026.snaphu.img` |
| 해상도 | **67473 × 13106** pixels (width × height) |
| 통계 비용 모드 | `DEFO` (변위/지반침하 탐지 특화) |
| 초기화 방법 | `MCF` (Minimum Cost Flow) |
| 타일 분할 | 10 × 10 = 100 타일 |
| 타일 오버랩 | 200 px (row/col 공통) |
| 병렬 프로세스 | **24** (시스템 전체 코어 사용) |
| SNAPHU 버전 | 2.0.4 (Windows native, `snaphu-v2.0.4_win64\bin\snaphu.exe`) |

### 실행 명령어

```powershell
cd "<DATA_ROOT>\SNAPHU\unwrapping\20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt"
& "<DATA_ROOT>\snaphu-v2.0.4_win64\bin\snaphu.exe" `
    -f snaphu.conf `
    Phase_ifg_VV_23Jun2026_24Jun2026.snaphu.img `
    67473
```

### 현재 상태 (2026-06-30)

- **실행 중** — 타일 처리 진행 중 (`snaphu_tiles_*` 디렉토리 생성 확인)
- 출력 예정: `UnwPhase_ifg_VV_23Jun2026_24Jun2026.snaphu.img`
- 예상 완료: 실행 시작(PM 1:05)으로부터 30~60분

### 진행상황 확인

```powershell
# 실시간 로그 확인
Get-Content "<DATA_ROOT>\SNAPHU\unwrapping\20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt\snaphu.log" -Tail 20

# 프로세스 확인
Get-Process -Name snaphu | Select-Object Name, CPU, WorkingSet

# 출력 파일 생성 여부 확인
Get-Item "<DATA_ROOT>\SNAPHU\unwrapping\20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt\UnwPhase_ifg_VV_23Jun2026_24Jun2026.snaphu.img" -ErrorAction SilentlyContinue | Select-Object Length
```

---

## 언래핑 이후 단계 (예정)

```
UnwPhase_ifg_VV_23Jun2026_24Jun2026.snaphu.img
  └─ [SNAP] Snaphu Import
       Radar > Interferometric > Unwrapping > Snaphu Import
       Source: subset_0_of_...Flt.dim
       Unwrapped phase: UnwPhase_ifg_VV_23Jun2026_24Jun2026.snaphu.img

  └─ [SNAP] Phase to Displacement
       Radar > Interferometric > Products > Phase to Displacement
       출력 단위: m (LOS 방향 변위)

  └─ [SNAP] Terrain Correction (Range-Doppler)
       최종 출력: GeoTIFF (WGS84, 지표 변위 맵)
```

### 수직 변위 환산

LOS(Line-of-Sight) 변위 → 수직 변위:

```
수직 변위 = LOS 변위 / cos(입사각)
※ Sentinel-1 IW: 입사각 약 29~46°
```

**주의:** coherence < 0.3 구간은 마스킹 후 분석.  
싱크홀·급격한 국소 침하는 위상 불연속 집중 구역에서 탐지.

---

## 폴더 구조

```
earthquake/
├── S1A_IW_SLC__...20260623...SAFE.zip     (8.2 GB, 원시 입력)
├── S1C_IW_SLC__...20260624...SAFE.zip     (7.5 GB, 원시 입력)
├── 20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt.dim/.data/
├── 20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt_TC.dim/.data/
├── subset_0_of_20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt.dim/.data/
├── SNAPHU/unwrapping/
│   └── 20260623_20260624_Orb_Stack_Ifg_Deb_mrg_Flt/
│       ├── snaphu.conf                    (실행 설정)
│       ├── Phase_ifg_VV_*.snaphu.img      (3.5 GB, 입력 위상)
│       ├── coh_VV_*.snaphu.img            (3.5 GB, 입력 간섭도)
│       ├── UnwPhase_ifg_VV_*.snaphu.img   (3.5 GB, 출력 — 생성 중)
│       └── snaphu.log
├── snaphu-v2.0.4_win64/bin/snaphu.exe
├── epicenters/epicenters_2026.shp
├── fault/gem-global-active-faults/
└── capa-de-venezuela/
```
