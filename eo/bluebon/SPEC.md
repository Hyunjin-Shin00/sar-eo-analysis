# BlueBON 센서 사양

- 8밴드 push-broom 광학 초소형 위성
- 처리 코드 사용에 필요한 값을 정리한 문서임
- 전체 처리 흐름과 알려진 문제는 [`OVERVIEW.md`](OVERVIEW.md) 참조

> 공칭값은 제원표, 실측값은 분광응답함수(SRF)와 코드에서 가져옴.
> 두 값이 다른 항목은 별도 표기하였으므로 문서 작성 시 혼용 금지.

---

## 1. 밴드 구성

| idx | 이름 | 파일 접미사 | SRF 가중 중심 (nm) | FWHM (nm) | 공칭 중심/대역폭 (nm) | 운영 TDI | F0 (W/m²/µm) |
|---:|---|---|---:|---:|---|---:|---:|
| 0 | PAN | `_0_gray` | 616.0 | 246 | 625 / 250 | 2 | 1653 |
| 1 | Blue | `_1_gray` (MS1) | 483.2 | 63 | 490 / 65 | 4 | 2000 |
| 2 | Green | `_2_gray` (MS2) | 562.4 | 35 | 560 / 35 | 8 | 1819 |
| 3 | Red | `_3_gray` (MS3) | 664.6 | 30 | 665 / 30 | 8 | 1514 |
| 4 | RedEdge1 | `_4_gray` (MS4) | 704.8 | 14 | 705 / 15 | 16 | 1421 |
| 5 | RedEdge2 | `_5_gray` (MS5) | 739.2 | 13 | 740 / 15 | 16 | 1292 |
| 6 | RedEdge3 | `_6_gray` (MS6) | 781.9 | 19 | 783 / 20 | 16 | 1166 |
| 7 | NIR | `_7_gray` (MS7) | 836.6 | 101 | 842 / 115 | 4 | 1032 |

- Blue·NIR은 공칭값과 SRF 가중 중심의 차이가 큼
- 대역이 넓어 가중 중심이 공칭값에서 이동한 결과임
- 정량 계산 시 SRF 가중 중심 사용

### F0 (밴드 평균 태양 복사조도)

- Thuillier(2003) 태양복사 스펙트럼을 밴드별 SRF로 가중평균한 값

```
F0_b = Σ F0(λ)·SRF_b(λ) / Σ SRF_b(λ)
```

- 원본 스펙트럼 단위는 µW/cm²/nm → **×10** 적용 시 W/m²/µm
- SRF 원본은 400–1000 nm를 1 nm 간격으로 수록
- 실제 응답은 "Total optical transmission × QE × fill factor" 블록

---

## 2. 검출기와 촬영

| 항목 | 값 |
|---|---|
| 검출기 폭 | **4096 화소** (across-track) |
| L0 라인 수 | **16000 고정** — 실제 촬영분이 적으면 나머지는 0 |
| 양자화 | **12 bit** (0–4095) |
| Line rate | 운영값 **666** (코드 기본 `lp=666`) |
| 지상 해상도 | 약 **4.8 m** (L1C 기준) |
| 궤도 | 태양동기, 경사각 약 97.4°, 고도 약 495–500 km · NORAD 62688 *(추정)* |

### TDI와 포화 DN

- TDI 단수에 따라 포화점 상이
- 밝은 장면에서 먼저 포화하는 밴드가 여기서 결정됨

| TDI | 포화 DN |
|---:|---:|
| 1 | 1023 |
| 2 | 2026 |
| 4 | 4032 |
| 8 · 16 | 4095 |

- TDI 설정은 미션 시트 `Band [PAN,MS1..7]` 열에 문자열로 기재 — 예: `"2,4,8,8,16,16,16,4"`
- 4밴드 모드는 `[0,4,8,8,0,0,0,4]` 형식이며 **0은 미취득 밴드**

> ⚠ **코드가 TDI와 line rate를 영상 메타데이터에서 읽지 않고 하드코딩함**
> - 미션 시트와 다른 설정으로 촬영한 장면은 gain·dark가 어긋남
> - 다른 설정의 장면 처리 시 코드 쪽 상수 선행 수정 필요

### 초점면 밴드 배치 순서

```
Blue → Green → Red → PAN → NIR → RedEdge1 → RedEdge2 → RedEdge3
```

- 밴드가 초점면에 일렬 배치되어 촬영 시각이 밴드마다 상이
- 밴드 간 변위가 Red에서 멀어질수록 단조 증가 — 밴드정합이 필요한 이유
- 정합 잔차가 이 순서를 따르는지가 정합 성공 여부 판단 기준

---

## 3. 처리 레벨

| 레벨 | 파일 | 내용 | 생성 코드 |
|---|---|---|---|
| raw | `capture-YYMMDD_HHMMSS.bin00…` | 다운링크 원본. 64 MiB 조각, 영상 AES-256-CTR / 텔레메트리 AES-256-CBC 암호화 | 위성 |
| **L0** | `YYMMDD_HHMMSS_<b>_gray.tiff` | 밴드별 12 bit DN, 4096×16000, uint16 | `bin2png` |
| **L1A** | `bb_l1a_YYYYMMDD_HHMMSS_8band.tiff` | 복사보정 + 밴드정합 완료 8밴드 스택. **좌표계 없음** | [`radiometric/`](radiometric/) |
| **L1C** | `bb_l1c_YYYYMMDD_HHMMSS_8band.tiff` (+ `.RPB`) | 정사보정. UTM, 4.8 m 격자 | [`geometric/`](geometric/) |

> 이력: L0를 "level-1A", L1A를 "level-1B"(`bb_l1b_`)로 호칭하던 시기 있음.
> `rename_levels.sh`로 현재 명칭에 정렬 완료.

### 흐름

```
다운링크 → [L0] bin2png
        → [L1A] (raw − dark_ref)·flat_PRNU − δ  → 서브픽셀 정합 · jitter/회전 보정
                → TOA radiance (float32)  [+ 선택: TOA 반사도]
        → [L1C] 3분할 → 기준영상·DEM 수집 → 초기매칭 → 정밀매칭 → GCP
                → RPC 적합 → 정사보정(UTM 4.8 m) → 모자이크
```

---

## 4. 정량 분석 시 주의

| 항목 | 내용 |
|---|---|
| **정규화본 사용 금지** | `*_DN_dark_rc_p.tiff`와 `bb_l1a_*_8band.tiff`(uint16)는 **장면별 min–max 정규화값**. 정량 분석에는 `_float32` / `_f32` 파일 사용 |
| **지구-태양 거리 보정 버그** | 구 코드(`02_L_to_TOAR.py`)와 일부 연구 코드가 `×d_r²`로 처리. 올바른 식은 `÷d_r`이며 **최대 ±10% 오차** 발생 |
| **단위 표기 오류** | 복사휘도 단위를 "W/m²/sr/nm"로 기재한 곳 존재. 실제 값은 **W/m²/sr/µm** |
| **0 라인 혼입** | L0가 항상 16000행이므로 실제 라인이 적으면 0으로 채운 행이 통계·PRNU 계산에 혼입 |
| **절대보정 검증 중** | La Crau 대리검증에서 한 시기는 8밴드 중 6밴드가 ±10% 이내, 다른 시기는 약 +23% 편향. 절대 복사보정은 미확정 단계 |

---

## 5. 관련 문서

| 문서 | 내용 |
|---|---|
| [`OVERVIEW.md`](OVERVIEW.md) | 전체 처리 흐름 · 코드별 상세 · 알려진 문제 12건 |
| [`radiometric/doc/PIPELINE.md`](radiometric/doc/PIPELINE.md) | 복사보정 파이프라인 |
| [`radiometric/doc/RADIANCE_TOAR.md`](radiometric/doc/RADIANCE_TOAR.md) | 복사휘도 → TOA 반사도 변환 |
| [`radiometric/doc/REGISTRATION.md`](radiometric/doc/REGISTRATION.md) | 밴드정합 |
| [`radiometric/doc/REGISTRATION_ACCURACY.md`](radiometric/doc/REGISTRATION_ACCURACY.md) | 정합 정확도 |
| [`deblur-mtf/satellite_MTF.md`](deblur-mtf/satellite_MTF.md) | MTF 측정 |
| [`THIRD_PARTY.md`](THIRD_PARTY.md) | 미포함 제3자 라이브러리 |
