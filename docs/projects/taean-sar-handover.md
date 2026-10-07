# 태안 해안사구 SAR 분석 - 인수인계 자료

차세대소형위성 2호(N2, X-band) 및 Sentinel-1(S1, C-band) SAR 영상으로 태안해안국립공원 사구 지역의 지표변화를 분석한 코드·산출물 모음임. 각 분석기법(InSAR / Offset Tracking / ACD)별로 **코드 + 결과물 + 중간산출물**을 정리했음.

---

## 1. 폴더 구조

```
<WORK_ROOT>\Result\
  00_README_인수인계.md          ← 이 문서
  결과맵_result.html             ← 인터랙티브 통합 맵 (아래 8-8 참고)
  taean_SAR_protocol.drawio      ← 처리 프로토콜 순서도 (draw.io)
  taean_SAR_방법론_답변자료.md    ← 방법론 요약 (보고회/협력기관 답변용)

  01_InSAR\
    code\            자체 파이썬 InSAR + ISCE2 후처리 코드
    ISCE2_원본\      ISCE2 실행 설정(topsApp.xml)·로그·원본 산출(s1_isce2_*)
    결과_HTML수록\   HTML에 실린 InSAR 결과 (N2 자체 4종 + S1 ISCE2 4종)
    중간산출물\      자체 vs ISCE2 비교, custom 변형, overview 등

  02_OffsetTracking\
    code\            offset_track.py 등
    결과_HTML수록\   HTML에 실린 OT (N2 0515x0614, S1 0519x0613)
    중간산출물\      나머지 OT 페어 전체 + summary(json) + overview

  03_ACD\
    code\            n2_acd_pair.py 등
    SLC_진폭영상\    HTML 배경 SLC 진폭 10종
    결과_HTML수록\   HTML에 실린 로그비 dB (N2 4종 + S1 1종)
    중간산출물\      coherence, GRD, 변화필터, overview 등

  09_공통\
    code\            페어 적합성(compute_baseline.py)·AOI(analyze_shp.py)·HTML빌더
      _work_전체백업\  work/의 모든 .py 원본 백업 (진단/개발 스크립트 포함)
    AOI_shp\         Taean.shp (분석 대상 폴리곤)
    DEM\             cop_dem_N36E126.tif (처리에 쓴 Copernicus DEM)
```

---

## 2. 처리 도구 (자체코드 vs ISCE2) - 중요

| 기법 | N2 (X-band) | S1 (C-band) |
|---|---|---|
| **InSAR (위상)** | **자체 파이썬** (ISCE2가 N2 미지원) | **공식 ISCE2 topsApp v2.6.3** |
| **Offset Tracking** | 자체 파이썬 | 자체 파이썬 |
| **ACD (진폭변화탐지)** | 자체 파이썬 | 자체 파이썬 |

- ISCE2를 쓴 것은 **S1 위상 InSAR 하나뿐**임.
- 나머지는 전부 자체 파이썬임. (N2는 어떤 상용/공개 SW도 미지원 → 궤도 기하부터 직접 구현)

---

## 3. 실행 환경

- conda 환경: **`isce2_snaphu`** (`$CONDA_PREFIX`; isce2·h5py·numpy·rasterio·gdal·scipy·pyproj 포함)
- 언래핑: snaphu 바이너리는 **`.../bin/snaphu.conda_backup`** 사용 (기본 `snaphu` 래퍼는 깨져 있음)
- `conda activate isce2_snaphu` 후 실행

---

## 4. 기법별 재현 방법 (main script)

| 기법 | 실행 | 비고 |
|---|---|---|
| InSAR (자체, N2) | `python improved_run.py n2` | 0515x0614 |
| InSAR (자체, S1) | `python improved_run.py s1ab` | 0519x0531 (교차검증용) |
| InSAR (ISCE2, S1) | `topsApp.py`(topsApp.xml) → `python isce_unw2disp.py` | 최종 언랩→LOS(cm) |
| Offset Tracking | `python offset_track.py <mode>` | mode 예: `n2_0515x0614`, `s1_0519x0613` |
| ACD (N2 A_L) | `python n2_acd_pair.py` | 0515x0614 로그비 |
| ACD (N2 A_R) | `python n2_acd_ar.py` | 0402/0529 x 0613 |
| 페어 적합성 | `python compute_baseline.py` | Bperp·Bcrit·dinc 계산 |
| HTML 재생성 | `python build_result_html.py` | LAYERS 경로는 원본 폴더 기준 |

(코드 상단 경로가 원본 작업폴더 기준이므로, 재실행 시 입력경로만 현지에 맞게 조정)

---

## 5. HTML에 수록된 "대표 결과" 페어

| 기법·센서 | 페어 |
|---|---|
| N2 InSAR / OT / ACD(A_L 32°) | 20260515 x 20260614 |
| S1 InSAR (ISCE2) | 20260519 x 20260531 |
| S1 OT | 20260519 x 20260613 |
| S1 ACD | 20260519 x 20260613 |

나머지 페어(중간산출물)는 검토·비교용임.

---

## 6. 원본 입력 데이터 (여기에 복사 안 함)

원본 N2 `.h5`·S1 `.zip`은 **읽기 전용·반출 금지** 원칙으로 이 폴더에 넣지 않았음. 경로는 `09_공통\데이터경로_안내.md` 참고.

---

## 7. ★ 인수인계 시 반드시 전달할 사항

1. **원본 데이터 취급**: N2 `.h5`는 읽기 전용(수정·반출 금지). 반출 가능한 것은 **처리 산출물뿐**. `fix_sbi_layout.py` 등 쓰기가 필요하면 반드시 **사본에** 적용.

2. **작업폴더는 반드시 Linux ext4**: ISCE2/정합 refine을 `/mnt/c`(DrvFs)에서 돌리면 misregistration 쓰기가 **EPERM으로 조용히 skip**되어 위상이 손상됨. **ext4에서 실행 후 산출물만 `/mnt/c`로 복사**하세요. (파일 복사도 `copy2` 대신 `copyfile` 권장 - drvfs 타임스탬프 오류)

3. **지오코딩 지오이드 오프셋(약 24.5 m)**: Copernicus DEM이 정표고(EGM2008)라 타원체고를 기대하는 지오코딩에서 range 방향으로 약 24.5 m 편이가 생깁니다(A_L은 동편, A_R은 서편). **HTML은 표시 단계에서 보정 시프트를 적용**했지만, **tif 원본은 미보정**입니다 → GIS에서 다른 레이어와 정합할 때 유의(필요 시 DEM에 +지오이드고 반영해 재처리).

4. **부호 규약**: OT의 range(+)는 "위성에서 멀어짐", InSAR LOS(+)는 "위성에 가까워짐"으로 **서로 반대**임. 또 N2 자체 InSAR의 LOS 부호식과 S1 ISCE2 부호식이 코드상 반대라, 절대부호 비교 시 주의(단 N2 InSAR는 탈상관 잡음이라 물리적 의미 없음).

5. **결과의 과학적 한계 (핵심)**: X-band는 사구에서 **수 일 내 위상 탈상관** → 위상 InSAR·OT 모두 **잡음 지배**임. 30~35일 위상 InSAR는 불가. 진폭변화탐지(ACD)만 유일하게 구조가 있는 관측임. **결과는 변위량이 아니라 "국산 위성 처리 방법론 시연"으로 프레이밍**하는 것을 권장(자세한 논리는 방법론_답변자료.md).

6. **페어 적합성이 모든 것을 좌우**: 동일 궤도·룩 방향, 입사각 차(dinc), 수직베이스라인 비(Bperp/Bcrit), 시간차가 맞아야 함. 원본 카탈로그·페어 후보는 `N2\nextsat2_scenes.csv` / `N2\nextsat2_pairs.xlsx`가 소스 오브 트루스이며, **폴리곤을 덮는 유효 InSAR 페어는 0515x0614 하나뿐**임. N2 각 씬 입사각이 16~34°로 제각각이라 다중시점 스택은 성립하지 않음.

7. **result.html**: 데이터는 파일에 내장(atob/Float32)되어 tif 없이도 표출되지만, **Leaflet(unpkg.com)·ESRI 위성 베이스맵(arcgisonline.com)은 인터넷이 필요**함. 오프라인에서는 지도 배경이 뜨지 않음.

8. **폴더 대소문자(WSL)**: 원본 `taean_InSAR`와 `taean_Insar`는 Windows에서 **동일 폴더**입니다(ISCE2 산출은 `isce2\` 하위). WSL에서 캐시가 꼬이면 대소문자를 바꿔 접근.

---

문의가 필요한 세부(코드 내부 파라미터, 특정 페어 재처리 등)는 각 폴더 `code\` 상단 주석과 `09_공통\code\_work_전체백업`의 진단 스크립트를 참고하세요.
