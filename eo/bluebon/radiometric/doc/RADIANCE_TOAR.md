# BlueBON 절대복사보정 — TOA Radiance / Reflectance + RadCalNet 검증

작성 기준: 2026-07 · 관련 코드 `src/pipeline.py`(기본 산출=radiance), `src/radcal/`

---

## 0. 개요

v5 파이프라인의 **상대 보정 DN**에 **절대 복사 계수(gain)**를 적용해 **TOA 분광복사휘도(radiance)**로,
다시 **TOA 반사율(reflectance)**로 변환함. 절대 계수는 FM1 실험실 특성표에서 얻고, 결과는
RadCalNet La Crau(LCFR01) 자료로 독립 검증함.

변환 사슬:
```
보정 DN (v5)  ──gain_band, ÷band_width──▶  TOA 분광복사휘도 L [W/m²/sr/nm]
L  ──× π /(F0·cosθs)/d_r──▶  TOA 반사율 ρ
```

---

## 1. 변환식

### 1.1 DN → TOA radiance
```
L_b = DN_corr,b · gain_b / band_width_b        # b = 밴드
```
- `DN_corr` : v5 산출물 `(raw−dark)·flat−δ` (정합·flip 완료). flat 평균=1이라 DN 스케일 유지.
- `gain_b`  : **FM1 실험실 밴드평균 gain** (radiance/DN). 검출기 컬럼별 `DN↔복사휘도` 선형회귀
  계수의 밴드 평균. **BAND × Line rate × TDI 로 조회** → gain은 촬영 설정에 종속.
- `band_width_b` [nm] : `{PAN:250, Blue:65, Green:35, Red:30, RE1:15, RE2:15, RE3:20, NIR:115}`.
  나눗셈으로 밴드적분 복사휘도 → **분광복사휘도(per-nm)** 로 정규화.

### 1.2 TOA radiance → TOA reflectance
```
ρ_b = π · L_b / (F0_b · cos θs) / d_r
```
- `F0_b` : **Thuillier(2003) 태양 스펙트럼 × BlueBON SRF** 밴드적분 분광조도.
- `θs`   : 태양 천정각(SZA).
- `d_r = 1 + 0.033·cos(2π·DOY/365)` = 일사 플럭스 인자 `(1AU/d)² = 1/d²`.
  물리식 `ρ = πL·d²/(F0 cosθ)` 이므로 **÷d_r ( = ×d²)** 가 정확.
  ⚠ 구 코드 `02_L_to_TOAR.py`는 `×d_r²`로 적용 — 방향·거듭제곱이 뒤집힘(계절편차 ~±10%).
  본 파이프라인은 **÷d_r**로 수정 적용(0528 검증에서 실증, §4).

### 1.3 La Crau 촬영 설정 (사용자 확인)
- band0..7 TDI = **`2,4,8,8,16,16,16,4`**, line rate **667** (FM1표 최근접 **666** 사용).
- 두 La Crau 장면(20260528, 20260704) 동일.

### FM1 밴드 gain·F0 (lp=666)
| 밴드 | TDI | gain [rad/DN] | band_width | F0_b |
|--|--|--|--|--|
| PAN | 2 | 8.750 | 250 | 1653 |
| Blue | 4 | 5.372 | 65 | 2000 |
| Green | 8 | 2.055 | 35 | 1819 |
| Red | 8 | 1.961 | 30 | 1514 |
| RE1 | 16 | 1.180 | 15 | 1421 |
| RE2 | 16 | 1.375 | 15 | 1292 |
| RE3 | 16 | 2.219 | 20 | 1166 |
| NIR | 4 | 8.882 | 115 | 1032 |

---

## 2. 산출물 형식 (pipeline.py 기본)

`<SITE>/radiometric_v5/` — **기본 산출이 TOA radiance**:

| 파일 | 물리량 | dtype |
|--|--|--|
| `MS{0..7}_DN_dark_rc_p.tiff` | TOA radiance (밴드별, 정규화) | 12bit(uint16) |
| `bb_l1a_20<stem>_8band.tiff` | TOA radiance (8밴드) | 12bit(uint16) |
| `bb_l1a_20<stem>_8band_f32.tiff` | TOA 분광복사휘도 [W/m²/sr/nm] | float32 |
| `bb_l1a-ref_20<stem>_8band_f32.tiff` | TOA reflectance (**옵션** `--to-reflectance --sza`) | float32 |
| `bb_l1a-rgb_20<stem>.png`, `registration_shifts.csv` | RGB / 정합값 | — |

- **12bit**는 밴드별 min–max 정규화(표시용, 01_DN_to_L 방식) — 절대 스케일은 **f32**만 보존.
- band순 0..7 = PAN,Blue,Green,Red,RE1,RE2,RE3,NIR.
- **DN 전용**이 필요하면 백업본 `src/pipeline_dnonly_backup.py` 사용.

---

## 3. 실행

```bash
conda activate prep
# 기본: TOA radiance (12bit + f32) 산출
python3 src/pipeline.py data/<SITE_DIR>

# TOA reflectance까지 (태양천정각 필요)
python3 src/pipeline.py data/<SITE_DIR> --to-reflectance --sza <deg>

# 촬영설정이 다르면
python3 src/pipeline.py data/<SITE_DIR> --tdi 2,4,8,8,16,16,16,4 --lp 666

# 이미 만든 v5 DN 8밴드에서 변환(정합 재실행 없이)
python3 src/radcal/dn_to_radiance.py --convert <..._8band.tiff> \
    --out-radiance <out_f32.tiff> --out-toar <out_ref_f32.tiff> --sza <deg> --doy <DOY>

# gain/F0 점검
python3 src/radcal/dn_to_radiance.py
```

---

## 4. RadCalNet La Crau 검증

`ref/radcal/LCFR/` = RadCalNet LCFR01 (lat 43.56, lon 4.86, 400–2500nm@10nm, UTC 09:00–15:00
30분격자, nadir TOA `.output`). 파이프라인 TOAR를 사이트 ROI에서 밴드적분한 RadCalNet TOA와 비교.

### 4.1 결과 (ROI = 실제 RadCalNet 계기 위치)
**20260528 (DOY148, 정확일, 11:00 UTC, SZA 23.49°, AOD 0.21 옅은 haze)** — pipeline TOAR / RadCalNet:

| 밴드 | PAN | Blue | Green | Red | RE1 | RE2 | RE3 | NIR | **평균** |
|--|--|--|--|--|--|--|--|--|--|
| ratio | 0.90 | 1.16 | 1.06 | 0.95 | 0.95 | 0.93 | 1.03 | 0.97 | **0.99 (σ0.08)** |

→ FM1 절대보정 + v5 DN + F0 + 거리보정 전 사슬이 **8밴드 모두 ±10% 이내로 RadCalNet 재현**.
거리인자를 구 코드식 `×d_r²`로 하면 평균 ~0.91로 악화 → **÷d_r 채택이 옳음을 실증.**

**20260704 (DOY185)**: RadCalNet 2026이 DOY184까지만 있어 **최근접일(184) 대체** + 더 큰
off-nadir(roll −9.85° vs 0528 −5.28°) → 평균 ratio ~1.23(계통 고편차). 절대보정 오류가 아니라
**참조일 불일치 + 시야기하 차이**에 기인. → 정확일 확보 시 재검증 권장.

### 4.2 결정적 검증 포인트
- **PAN·NIR의 TDI 종속**: 초기 TDI 가정 오류 시 PAN ~7.6×, NIR ~3× 편차 → 올바른 TDI
  (PAN=2, NIR=4)로 정정하니 제자리(gain ∝ ~1/TDI). 절대보정이 **TDI/line-rate에 강하게 종속**함을 확인.
- **haze**: 균일한 옅은 연무는 RadCalNet가 AOD로 모델링 → TOA 비교 성립(0528 통과). 단, 두꺼운/
  패치성 구름·그림자는 부적합.

---

## 5. src/radcal/ 도구

| 파일 | 역할 |
|--|--|
| `dn_to_radiance.py` | FM1 밴드 gain·F0 계산, DN→radiance/TOAR 변환(8밴드 스택). pipeline.py가 이를 사용 |
| `parse_radcalnet.py` | RadCalNet `.output` 파서(UTC열 선택, fill 처리, 기하/대기) |
| `band_integrate.py` | SRF(xlsx) 파싱 + RadCalNet 스펙트럼 밴드적분, 밴드매핑 검증 |
| `extract_roi_dn.py` | 지리참조 없는 L1A에서 퀵룩 + ROI 통계 |
| `vicarious_calib.py` | (참고) DN 기반 대리보정 계수 산출·플롯 |
| `run_lcfr_calib.py` | RadCalNet 검증 오케스트레이션(gains.csv/플롯/report.md) |

참조: `ref/SpectralResponseFunction.xlsx`(BlueBON SRF), `ref/radcal/LCFR/`(RadCalNet),
FM1 표·Thuillier F0는 `/mnt/e/bkchoi/prep/src/03_code/sub/`.

---

## 6. 한계·주의
1. **gain은 촬영설정(TDI·line-rate) 종속** — 장면마다 실제 설정을 `--tdi/--lp`로 지정해야 함.
2. **FM1 dark vs v5 night-ocean dark**: gain은 밴드평균 스칼라(컬럼별 아님)로 적용해 PRNU
   이중보정을 피함. 절편(intercept)은 무시(offset≈0) — 영향 <3%.
3. **거리인자**: `÷d_r` (구 `02_L_to_TOAR.py`의 `×d_r²`는 오류).
4. **reflectance는 태양기하(SZA) 필요** — L1A엔 지오로케이션이 없어 `--sza`로 직접 지정.
5. **검증 정밀화**: RadCalNet 정확일·near-nadir 장면일수록 신뢰↑. PAN은 flat≈1(PRNU 미보정)로
   상대 신뢰도 낮음(PIPELINE.md §9).
