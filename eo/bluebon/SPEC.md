# BlueBON 센서 사양

8밴드 push-broom 광학 초소형 위성. 이 문서는 **처리 코드를 쓰려면 알아야 하는 값**을 모은 것이다.
전체 처리 흐름과 알려진 문제는 [`OVERVIEW.md`](OVERVIEW.md) 에 있다.

> 공칭값은 제원표에서, 실측값은 분광응답함수(SRF)와 코드에서 왔다.
> 둘이 다른 항목은 따로 표기했다 — 문서를 쓸 때 섞지 말 것.

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

**Blue 와 NIR 은 공칭값과 SRF 가중 중심이 눈에 띄게 다르다.** 대역이 넓어 가중 중심이 공칭값에서 밀린다.
정량 계산에는 SRF 가중 중심을 쓴다.

### F0 (밴드 평균 태양 복사조도)

Thuillier(2003) 태양복사 스펙트럼을 밴드별 SRF 로 가중평균한 값이다.

```
F0_b = Σ F0(λ)·SRF_b(λ) / Σ SRF_b(λ)
```

원본 스펙트럼은 µW/cm²/nm 단위라 **×10** 을 해야 W/m²/µm 가 된다.
SRF 원본은 400–1000 nm 를 1 nm 간격으로 담고 있고, 실제 응답은
"Total optical transmission × QE × fill factor" 블록이다.

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

### TDI 와 포화 DN

TDI 단수가 다르면 포화점이 다르다. 밝은 장면에서 어느 밴드가 먼저 포화하는지가 여기서 갈린다.

| TDI | 포화 DN |
|---:|---:|
| 1 | 1023 |
| 2 | 2026 |
| 4 | 4032 |
| 8 · 16 | 4095 |

TDI 설정은 미션 시트 `Band [PAN,MS1..7]` 열에 문자열로 적힌다 — 예: `"2,4,8,8,16,16,16,4"`.
4밴드 모드는 `[0,4,8,8,0,0,0,4]` 처럼 쓰고 **0 은 미취득 밴드**다.

> ⚠ **코드는 TDI 와 line rate 를 영상 메타데이터에서 읽지 않고 하드코딩한다.**
> 미션 시트와 다른 설정으로 찍은 장면은 gain 과 dark 가 틀어진다.
> 다른 설정의 장면을 처리하려면 코드 쪽 상수를 먼저 맞춰야 한다.

### 초점면 밴드 배치 순서

```
Blue → Green → Red → PAN → NIR → RedEdge1 → RedEdge2 → RedEdge3
```

밴드가 초점면에 일렬로 놓여 있어 **촬영 시각이 밴드마다 다르다.**
그래서 밴드 간 변위가 Red 에서 멀어질수록 단조롭게 커진다 — 밴드정합이 필요한 이유이고,
정합 잔차가 이 순서를 따르는지가 정합이 제대로 됐는지 보는 기준이 된다.

---

## 3. 처리 레벨

| 레벨 | 파일 | 내용 | 생성 코드 |
|---|---|---|---|
| raw | `capture-YYMMDD_HHMMSS.bin00…` | 다운링크 원본. 64 MiB 조각, 영상 AES-256-CTR / 텔레메트리 AES-256-CBC 암호화 | 위성 |
| **L0** | `YYMMDD_HHMMSS_<b>_gray.tiff` | 밴드별 12 bit DN, 4096×16000, uint16 | `bin2png` |
| **L1A** | `bb_l1a_YYYYMMDD_HHMMSS_8band.tiff` | 복사보정 + 밴드정합을 거친 8밴드 스택. **좌표계 없음** | [`radiometric/`](radiometric/) |
| **L1C** | `bb_l1c_YYYYMMDD_HHMMSS_8band.tiff` (+ `.RPB`) | 정사보정. UTM, 4.8 m 격자 | [`geometric/`](geometric/) |

> 이력: 예전에는 L0 를 "level-1A", L1A 를 "level-1B"(`bb_l1b_`)로 불렀다.
> `rename_levels.sh` 로 현재 명칭에 맞췄다.

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
| **정규화본을 쓰지 말 것** | `*_DN_dark_rc_p.tiff` 와 `bb_l1a_*_8band.tiff`(uint16)는 **장면별 min–max 정규화값**이다. 정량 분석에는 `_float32` / `_f32` 파일을 써야 한다 |
| **지구-태양 거리 보정 버그** | 구 코드(`02_L_to_TOAR.py`)와 일부 연구 코드가 `×d_r²` 로 처리한다. 올바른 식은 `÷d_r` 이고 **최대 ±10% 오차**가 난다 |
| **단위 표기 오류** | 복사휘도 단위를 "W/m²/sr/nm" 로 적은 곳이 있는데 실제 값은 **W/m²/sr/µm** 이다 |
| **0 라인 혼입** | L0 가 항상 16000행이라, 실제 라인이 적으면 0 으로 채워진 행이 통계와 PRNU 계산에 섞인다 |
| **절대보정 검증 중** | La Crau 대리검증에서 한 시기는 8밴드 중 6밴드가 ±10% 이내, 다른 시기는 약 +23% 편향이었다. 절대 복사보정은 아직 확정된 단계가 아니다 |

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
| [`THIRD_PARTY.md`](THIRD_PARTY.md) | 포함하지 않은 제3자 라이브러리 |
