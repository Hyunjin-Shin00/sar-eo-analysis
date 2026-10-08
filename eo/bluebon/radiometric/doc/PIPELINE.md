# BlueBON 복사보정 + 밴드정합 파이프라인 (최종 문서)

작성 기준일: 2026-07-24 · 참조 세트: `correction_ref_260606`

---

## 0. 목표
BlueBON 위성 8밴드 raw 영상(16000×4096, uint16)을 **복사보정(dark/PRNU)** 하고
**밴드 간 공간 정합(registration)** 하여, 밴드순서 0~7로 정렬된 산출물을 생성함.
이후 **FM1 절대 gain**을 적용해 **TOA radiance(기본)** / **TOA reflectance(옵션)** 로 변환함.
(절대복사보정 변환식·gain·RadCalNet 검증 상세는 **`doc/RADIANCE_TOAR.md`**.)

밴드 index → 이름 : `0=PAN, 1=Blue, 2=Green, 3=Red, 4=RE1, 5=RE2, 6=RE3, 7=NIR`
파이프라인 참조 명명 : `PAN` (band0), `MS{n}` (band1~7)
입력 파일 규칙 : `<YYMMDD_HHMMSS>_{0..7}_gray.tiff`

---

## 1. 최종 보정식 (전 영상 공통·고정)

```
corrected = (raw − dark_ref[col]) × flat_prnu[col] − δ_persistent[col]      # 열(검출소자) 단위, raw 열공간
→ 밴드 정합(RGBN anchor + jitter+rotation) → 공통 crop → 좌우 flip
```

- **dark_ref** (가산, 열별): 야간 원양 dark 평균. 오프셋/암전류(DSNU) 제거.
- **flat_prnu** (곱셈, 열별, mean=1): Libya-4 full-width flat. 검출기 PRNU + across-track vignetting 제거.
- **δ_persistent** (가산, 열별, 고주파): flat 후에도 남는 **지속적 미세 세로줄무늬** 제거.
- 이 세 항은 **모든 영상에 동일하게 적용되는 고정 캘리브레이션**임.
- 정합은 장면마다 값이 다르지만 **동일 알고리즘**을 일관 적용함.

---

## 2. 참조 데이터 생성

### 2.1 dark_ref  (`make_correction_ref.py` / `make_pan_ref.py`)
- 소스: 야간 원양(바다) dark 세션 **평균**.
  `DARK_SESSIONS = [260606_190315, 260424_114919]` (Auckland 인근 등, 운영 TDI).
- 방법: 세션별 라인축(16000) **단순 평균** → 세션 평균. (열별 4096 벡터)
- **sigma-clip 미사용**: 야간 원양은 이상치가 거의 없음(3σ 꼬리 0.3%뿐, 효과 <0.01 DN),
  16000라인 평균이 단발 스파이크도 희석 → 단순 평균으로 충분.
- 검증: 두 독립 dark(260606 vs 260424)이 **밴드평균 1% 이내 일치** = 재현성/안정성 확인.
- 산출: `{PAN,MS1..7}_dark_ref.tiff (float32 1×4096)`, `.dat`.

### 2.2 flat_prnu  (`make_flat_prnu.py`)
- 소스: **Libya-4** (lat 28.55, lon 23.39) 사막 PICS `260607_094318` (밝고 균일 → flat 대용).
- 방법: `sig = median(Libya, 라인축) − dark_ref`; **`gain = mean(sig) / sig`** (창 없음=full-width).
- 효과: 미세 검출기 PRNU + **넓은 across-track vignetting(~5.8%) 모두 평탄화**
  (Libya에서 vignetting 5.8%→0.0% 확인).
- 곱셈 계수, mean≈1. std ≈ 1.3~4.6% (밴드별, vignetting 포함).
- 산출: `{...}_prnu_flat_coef.dat`, `.tiff`.
- (참고) `{...}_residul_prnu_coef.dat` = 고주파만(창21) 잔차 PRNU. **flat 채택으로 미사용**(비교용 보존).

### 2.3 δ_persistent  (`make_delta_persistent.py`)
- 정의: flat 보정 후에도 **여러 장면에서 반복되는 열 고정 가산 잔차**(미세 세로줄무늬).
- 방법: 2026 바다 장면 5개(Hormuz/GBR/Khark/Sohae/Bushehr)에서
  `(raw−dark)×flat`의 **어두운(바다) 영역 열중앙값**을 **고주파(창=51) 추출** → **장면 평균**.
  다중 장면 평균이라 장면성분은 상쇄되고 검출기 고정패턴만 남음.
- **고주파(창51)만 사용**하는 이유 → §4.6 참조(일관성).
- 산출: `{...}_delta_persistent.dat`, `.tiff`.

---

## 3. 정합 (registration) — `pipeline.py` / `finalize_observation.py`

- **phase correlation**(skimage, high-pass 전처리, upsample=10)로 밴드 shift 추정.
  규약: `phase_cross_correlation(ref, mov)` → `shift(mov, s)` 하면 ref에 정렬.
- **촬영순서** `[Blue,Green,Red,PAN,NIR,RE1,RE2,RE3]` 인접쌍 shift 체인 누적.
- **최적 anchor 자동선택 = RGBN(Blue/Green/Red/NIR) 중 최대변위 최소** → 보통 **Red**.
  (RGBN 우선 정렬 → 자연색+NIR 밴드 sub-pixel 정합)
- **jitter+rotation 보정 (collin)**: 평행이동 후 남는 자세지터 잔차를
  along-track 윈도우 × across-track 블록 격자로 추정 → 컬럼 선형회귀(회전 yaw + keystone)
  → row 따라 강한 스무딩 → **단일 remap**으로 (chain + 필드) 한번에 적용(이중보간 방지).
- 공통 유효영역 crop → 전 밴드 동일 **좌우 flip**.

정합 성능(RGBN 중심, anchor=Red, 잔차 RMS):
Blue 0.55→**0.14**, Green 0.37→**0.09**, NIR 0.85→**0.28**, RE1~3 ≤ **0.33** (jitter+rotation 적용).

---

## 4. 진행 연대기 & 핵심 분석 결과

### 4.1 dark/PRNU 참조 최초 산출
- dark = 밤 원양(준-dark), PRNU = Libya-4. MS1~7 생성 → PAN 포함 전 밴드로 확장.
- 검증: Libya에 적용 시 고주파 잔차 ~0.6%→~0.06%, PRNU mean=1.0, nan=0.

### 4.2 관측 적용 & 정합 개발
- 실관측 적용 시 FPN(세로줄무늬) 3~4배 감소 확인.
- 밴드 정합: 평행이동만으로는 along-track 물결형 잔차(±2.5px) = **자세 지터** 발견 →
  jitter 보정(row-의존) 추가 → 잔차 대폭 감소.

### 4.3 회전(rotation) 발견
- "중앙은 맞고 사이드는 안 맞음" → dy가 컬럼에 선형(회전 yaw). Blue +0.03°, RE3 −0.08° 등,
  촬영시각 거리에 비례. **collin(across-track 선형)** 모델로 확장 → 잔차 0.1~0.3px로 수렴.

### 4.4 flat vs residual PRNU
- 넓은 across-track vignetting은 **full-width flat**만 제거 가능(창을 키워야; 중간창은 무효).
- flat 채택. 단, 넓은 성분 제거는 Libya 균일성 가정 위에 성립.

### 4.5 dark 개선 검토 (옛 데이터 활용)
- FM1 lab dark(설정별 440행), 관측 dark(`test/sub/dark.tiff`) 모두
  장면 dark 패턴과 정합이 **우리 on-orbit night-ocean dark보다 나쁨**
  (corr: night-ocean 0.88 > FM1 0.58~0.70). **lab 패턴 ≠ 궤도 패턴.**
- 260424 Auckland dark 추가 → 260606과 1% 일치(재현성 검증). 평균 master dark로 채택.
- 결론: **옛 lab dark은 개선 아님**. on-orbit night dark 평균이 최선.

### 4.6 지속 vs 일시 줄무늬, 그리고 일관성 원칙 (핵심)
- 정합 전 raw 열공간에서 6개 장면 줄무늬 패턴 교차상관:
  2026 장면들 서로 **0.86~0.99** = **반복적 고정패턴**(일시적 아님). dark 패턴과 0.78~0.96.
  (HooverDam은 **2025 에폭**이라 상관 0.4 → 별도 에폭 참조 필요.)
- **미세 δ(창51)**: held-out(leave-one-out) 검증에서 **전 밴드 37~48% 감소, 악화 사례 0**
  → **일관 유효** → 채택.
- **넓은 밴딩(200~800px)**: 밴드별로 성격이 다름 —
  Blue/Green 지속적이나 **Green은 장면따라 개선/악화(부호 갈림)**, **Red·NIR은 실제 해양**.
  → 단일 고정 벡터로 **일관 교정 불가** → **채택하지 않음**(강제하면 무의미/유해).
- **원칙 확정: 모든 영상에 일관 적용되는 고정 보정만 캘리브레이션으로 인정.**

---

## 5. 최종 확정 구성 (v5)

| 구성요소 | 종류 | 소스/방법 | 일관성 |
|---|---|---|---|
| dark_ref | 가산 | 야간 원양 dark 평균(260606+260424), 단순평균 | 고정·공통 ✅ |
| flat_prnu | 곱셈 | Libya-4 full-width (PRNU+vignetting) | 고정·공통 ✅ |
| δ_persistent | 가산(고주파 창51) | 5개 바다장면 잔차 평균 | 고정·공통 ✅ (held-out 검증) |
| registration | 기하 | RGBN anchor + jitter+rotation(collin) | 동일 알고리즘 ✅ |

**적용식**: `(raw − dark)·flat − δ` → 정합 → crop → flip.

---

## 6. 스크립트 (모두 `correction_ref_260606/`)

| 스크립트 | 역할 |
|---|---|
| `make_correction_ref.py` | dark(MS1~7, 다중세션 평균) + residual PRNU 생성, 검증/README |
| `make_pan_ref.py` | PAN dark/PRNU 생성 |
| `make_flat_prnu.py` | **flat(full-width) PRNU** 계수 생성(전 밴드) |
| `make_delta_persistent.py` | **δ_persistent(창51, 일관)** 생성 + leave-one-out 검증 |
| `verify_correction_ref.py` | 참조 재로드 검증 |
| `pipeline.py` | **최종 파이프라인** (보정+δ+정합+flip+저장) |
| `merge_bands.py` | 개별밴드 → 8밴드 병합 |
| `rgb_from_8band.py` | 8밴드 TIFF → 원해상도 RGB PNG (pct/gamma 인자) |
| `convert_dtype.py` | f32/uint16 변환 |
| `make_delta_adaptive.py` | (실험, **미채택**) 밴드별 광대역 δ — 비일관으로 폐기 |
| `apply_*_m.py`, `pipeline_20260723.py`, `diag_rotation.py` | 개발/진단용 |

참조 파일(밴드별): `{PAN,MS1..7}_dark_ref.tiff/.dat`, `_prnu_flat_coef.dat/.tiff`,
`_residul_prnu_coef.dat`(미사용), `_delta_persistent.dat/.tiff`.

---

## 7. 실행 방법

```bash
conda activate prep
cd <WORK_ROOT>/working/radiometric_correction

# 관측 1건 처리 (기본: flat PRNU + δ + 정합, 산출 = TOA radiance)
python3 src/pipeline.py data/<SITE_DIR>

# TOA reflectance까지 (태양천정각 필요)
python3 src/pipeline.py data/<SITE_DIR> --to-reflectance --sza <deg>

# 옵션
#   --prnu-mode flat|residual   (기본 flat)
#   --no-delta                  (δ 미적용)
#   --out-name <dir>            (출력 하위폴더)
#   --tdi 2,4,8,8,16,16,16,4    (radiance용 band0..7 TDI)
#   --lp 666                    (radiance용 line rate)

# 8밴드 TIFF -> RGB PNG
python3 src/rgb_from_8band.py <...>_8band.tiff --pct 1 99 --gamma 1.4
```

**출력** (`<SITE>/radiometric_v5/`) — 기본 **TOA radiance** (band순 0~7):
- `MS{0..7}_DN_dark_rc_p.tiff` (개별밴드 12bit, TOA radiance 정규화)
- `bb_l1a_20<stem>_8band.tiff` (병합 8밴드 12bit, TOA radiance)
- `bb_l1a_20<stem>_8band_f32.tiff` (병합 8밴드 float32, TOA 분광복사휘도)
- `bb_l1a-ref_20<stem>_8band_f32.tiff` (병합 8밴드 float32, TOA reflectance; **옵션 --to-reflectance**)
- `bb_l1a-rgb_20<stem>.png` (원해상도 RGB), `registration_shifts.csv`

> DN 전용 산출은 백업본 `src/pipeline_dnonly_backup.py` 사용. 변환식·검증은 `doc/RADIANCE_TOAR.md`.

**참조 재생성** (참조 세트 갱신 시):
```bash
python3 make_correction_ref.py   # dark(MS)+residual PRNU
python3 make_pan_ref.py          # PAN dark/PRNU
python3 make_flat_prnu.py        # flat PRNU (전 밴드)
python3 make_delta_persistent.py # δ_persistent (창51)
```

---

## 8. 검증 결과 요약

- **미세 세로줄무늬(FPN)**: raw 대비 flat+δ로 **3~5배 감소**, held-out에서 밴드별 37~48% (일관).
- **vignetting**: Libya 기준 5.8%→0.0%.
- **밴드 정합**: RGBN sub-pixel(0.1~0.3px), jitter+rotation 반영.
- **dark 재현성**: 독립 2세션 1% 이내 일치.

---

## 9. 알려진 한계 & 향후

1. **넓은 바다 밴딩(200~800px)**: Blue/Green에서 균일·어두운 바다 위에 잔존.
   일관 캘리브 불가(장면별 부호 갈림 + 실해양 성분) → **미보정**. 육지 장면에선 거의 비가시.
   - 근본 해결은 (a) 한계 수용, 또는 (b) 그것이 안정적 고정패턴임을 입증할 데이터 캠페인
     (다중 궤도 반복성, 바다 밝기대 flat) 필요 — 현재 증거는 대부분 밴드에서 "안정적 고정" 부정.
2. **PAN**: Libya PAN이 포화(~2026)라 flat PRNU가 ≈1(무보정). PAN 열 FPN은 δ(가산)로만 완화.
   근본 해결은 **비포화 균일 타깃에서 PAN flat 재산출**.
3. **에폭 의존성**: 참조는 2026 에폭. **2025 영상(예: HooverDam)은 검출기 상태가 달라 부적합**
   → 에폭별 dark/flat 세트 필요.
4. **dark 설정 매칭**: 운영 TDI/line-rate가 참조와 다르면 dark 재취득 권장.

---

## 10. 산출물 현황
- 전 사이트를 최종 구성으로 `radiometric_v5`에 처리. 밴드순서 0~7.
- **기본 산출 = TOA radiance**: 개별밴드 12bit + 병합 8밴드 12bit/float32 + 원해상도 RGB
  (+ 옵션 TOA reflectance float32). 절대 gain·검증은 `doc/RADIANCE_TOAR.md`.
- La Crau(20260528·20260704)는 RadCalNet LCFR01로 검증(정확일 0528: TOAR 8밴드 ±10% 이내).
