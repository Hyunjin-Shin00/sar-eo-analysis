# BlueBON AOD Retrieval Pipeline

BlueBON 위성 L1C TOA radiance 영상에서 **AOD(550 nm)** 를 산출하고 MODIS MAIAC 로
background 보정하는 end-to-end 파이프라인. 최상위 실행 파일은
`bb_aod_pipeline.py` 이며, 내부적으로 `bb_aod_calval.retrieve_aod` (v8 설정) +
후처리 Gaussian 스무딩 + MAIAC 자동 다운로드를 묶어 한 번에 처리함.

---

## 1. Overview

```
BlueBON L1C .tiff  ──►  TOA reflectance  ──►  DDV + 6S LUT inversion
                                                       │
                                      MAIAC MCD19A2 ◄──┤  (scene mean, auto download)
                                                       ▼
                       AOD(550) GeoTIFF  ◄──  Gaussian fill + smoothing  ◄──  post-smooth σ
```

- **알고리즘 계열:** MODIS Dark Target (DT) + 6S 복사전달 LUT 역산 + MAIAC 레퍼런스 fill
- **대상 밴드:** Blue 490 nm (aerosol path reflectance), Red 665 nm (surface blue via Kaufman 1997 ratio), NIR 842 nm (NDVI)
- **출력 해상도:** 기본 20 m (native 5 m 급에서 다운샘플)
- **최종 산출:** 같은 scene 에 대해 `bb_aod_v8_sm.tif` 를 **비트 단위** 로 재현

---

## 2. Input Requirements

| 항목 | 조건 |
|---|---|
| 파일 포맷 | GeoTIFF (`bb_l1c_YYYYMMDD_HHMMSS_*band.tiff`), uint16 DN |
| 밴드 구성 | 1=PAN, 2=Blue, 3=Green, 4=Red, 5=RE1, 6=RE2, 7=RE3, 8=NIR |
| 파일명 | 센싱 시각 파싱용으로 `bb_l1c_YYYYMMDD_HHMMSS` 패턴 필수 |
| CRS | 지리/투영 모두 가능 (`rasterio` 가 읽을 수 있어야 함) |
| calibration | DN → radiance 계수 `--radiance-scale` (기본 0.3183) |

---

## 3. Algorithm Pipeline

### 3.1. DN → TOA Reflectance
```
L   [W m⁻² sr⁻¹ μm⁻¹] = DN × radiance_scale
ρ   = π · L · d² / (ESUN · cos θ_z)
```
- `d` : Earth–Sun distance (Spencer 1971)
- `θ_z` : solar zenith (scene center, Spencer 1971 + NOAA)
- `ESUN` : Thuillier 2003 at band center (Blue 490 nm, Red 665 nm, NIR 842 nm 등)

### 3.2. Masks
- **Cloud:** `ρ_blue > 0.25`
- **Snow:** `ρ_blue > 0.35 & ρ_NIR > 0.25 & NDVI < 0.15`
- **Water:** `NDVI < 0.05 & ρ_NIR < 0.05`
- **Invalid:** 임의 밴드 NaN
- (옵션) GOCI-II G2AR 스타일 spatial cloud test는 기본 비활성 (v8)

### 3.3. DDV (Dark Dense Vegetation) 선택
SWIR 이 없는 BlueBON 특성상 Kaufman 1997 조건을 적용:
- `NDVI ≥ 0.25`
- `ρ_red ≤ 0.15`
- `ρ_NIR ≥ 0.20` (해조/하수 침전지 배제)
- cloud/snow/water/invalid 아님

### 3.4. Surface Blue Reflectance (NDVI-dependent ratio)
```
if NDVI < 0.60 :  ratio = 0.575 × (0.6 + 0.4 × (NDVI − 0.25) / 0.35)
else           :  ratio = 0.575
ρ_surf_blue   = ratio × ρ_red
```
- 기준: Kaufman et al. (1997) blue-to-red ratio
- 겨울 한반도 조건 보정: NDVI 낮을수록 ratio 를 낮춤 (0.345 → 0.575)

### 3.5. 6S LUT at 490 nm
- 9개 AOT 노드 `(0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0)` 에 대해 Py6S 실행
- 입력: scene solar zenith, view zenith=0, rel az=|SAA−180°|, continental aerosol,
  midlatitude atmosphere (자동 감지)
- 출력: path reflectance 테이블 + Rayleigh offset (AOT→0 보간)

### 3.6. AOD 역산 (2-step Newton)
```
rho0 = blue − rayleigh            # 초기 (surf 기여 무시)
aod0 = interp(rho0, LUT)
T0   = exp(−(τ_ray+τ_aero(aod0)) × (1/μ_s + 1/μ_v))
rho1 = blue − surf × T0
aod1 = interp(rho1, LUT)
aod2 = interp(blue − surf × T(aod1), LUT)  # 한 번 더 반복
```
- `surf > blue − rayleigh` 인 경우 path ρ<0 에 의한 AOD=0 문제 방지
- DDV 픽셀에서만 산출 → 이후 전역 전파

### 3.7. Clip + Downsample + Fill
1. DDV AOD 를 `[p10, p95]` 로 양방향 클립 (분포 꼬리 제거)
2. 5 m native → 20 m 출력 격자 다운샘플 (`rasterio` average)
3. Gaussian fill (DDV → 전 화면): σ = **300 px** (출력 격자 환산)
4. Background fill (clear/cloud/snow 미채움 영역):
   - `--maiac-aod-mean` 값 (우선) 또는 DDV median
5. Main smoothing (NaN-aware weighted): σ = **480 px** (v8 표준)

### 3.8. Post-Smoothing
```
num = gaussian_filter(where(valid, aod, 0), σ=30)
den = gaussian_filter(valid.float,       σ=30)
out = num / max(den, 1e-9)   # NaN-aware
```
- 파이프라인 최종 단계, `--post-sigma-px 30` 기본값
- `smooth_v8.py` 와 동일 로직 (내장)

### 3.9. MAIAC 자동 통합
`--auto-maiac` 지정 시:
1. 입력 tiff 의 `bb_l1c_YYYYMMDD_HHMMSS` 파싱 → 센싱 날짜
2. tiff CRS+bounds → WGS84 bbox 변환 (+0.10° padding)
3. `earthaccess` 로 MCD19A2 v061 검색·다운로드 (`--maiac-cache` 캐시)
4. 동일 날짜 granule 우선, 실패 시 ±`--maiac-date-window` 일 범위
5. bbox 내 유효 픽셀 평균 → `maiac_aod_mean` 자동 주입
6. 실패 시 DDV median 으로 fallback

---

## 4. Installation

### 4.1. Python 패키지
```bash
pip install rasterio numpy scipy pyproj Py6S earthaccess pyhdf matplotlib
```
기존 conda env `enh` 에 이미 설치됨.

### 4.2. NASA Earthdata 계정 (MAIAC 다운로드용)
MCD19A2 다운로드에 필요. 세 가지 방법 중 하나:

**(A) `~/.netrc` (권장)**
```
machine urs.earthdata.nasa.gov
  login     <USER>
  password  <PASSWORD>
```
`chmod 600 ~/.netrc`

**(B) 환경변수**
```bash
export EARTHDATA_USERNAME=<USER>
export EARTHDATA_PASSWORD='<PASSWORD>'
```

**(C) CLI 인수**
```bash
--earthdata-user <USER> --earthdata-pass '<PASSWORD>'
```

### 4.3. Py6S 설치 (6S 복사전달 모델)
Py6S 는 Fortran `6S` 실행파일이 필요. `enh` 환경에 이미 구성됨.

---

## 5. Usage

### 5.1. 기본 (MAIAC 자동 다운로드)
```bash
python3 bb_aod_pipeline.py \
  --input bb_l1c_20260220_025632_8band.tiff \
  --auto-maiac
```
출력 (입력과 같은 폴더):
- `bb_aod_20260220_025632_sm.tif` — 최종 AOD(550) GeoTIFF

### 5.2. MAIAC 수동 지정
```bash
python3 bb_aod_pipeline.py --input bb_l1c_...tiff --maiac-aod-mean 0.3393
```

### 5.3. 배치 처리 (glob)
```bash
python3 bb_aod_pipeline.py \
  --input 'bb_l1c_*_8band.tiff' \
  --auto-maiac \
  --out-dir outputs/ \
  --save-raw --save-qa
```

### 5.4. 진단 산출물 동시 저장
```bash
python3 bb_aod_pipeline.py --input ... --auto-maiac --save-raw --save-qa
```
추가 출력:
- `bb_aod_<date>_<time>_v8.tif` — post-smooth 전 결과
- `bb_aod_<date>_<time>_qa.tif` — QA 레이어 (1=DDV, 2=water, 3=cloud, 4=snow, 255=invalid)

### 5.5. 검증 (별도 실행)
```bash
python3 validate_bb_aod.py \
  --bb-input bb_l1c_20260220_025632_8band.tiff \
  --bb-aod   bb_aod_20260220_025632_sm.tif \
  --out-dir  ./validation \
  --current-scale 0.3183
```
출력: scatter plot, bias/RMSE/R², radiance_scale 재추정 제안값

---

## 6. Output Files

| 접미사 | 내용 | 조건 |
|---|---|---|
| `_sm.tif` | 최종 smoothed AOD(550) | 기본 |
| `_v8.tif` | post-smooth 전 AOD | `--save-raw` |
| `_qa.tif` | QA 레이어 (DDV/water/cloud/snow) | `--save-qa` |

QA 값:
- `0` : 일반 fill 영역
- `1` : DDV 픽셀
- `2` : water
- `3` : cloud
- `4` : snow
- `255` : invalid

---

## 7. Parameters Reference

### 7.1. V8 기본값 (고정, 변경 불필요)
| 파라미터 | 값 | 설명 |
|---|---|---|
| `radiance_scale` | 0.3183 | DN→radiance 계수 (현 BlueBON) |
| `surf_blue_red_ratio` | 0.575 | Kaufman blue/red ratio |
| `ndvi_dependent_ratio` | True | NDVI 에 따라 ratio 스케일링 |
| `forest_ndvi_thresh` | 0.60 | NDVI-dependent ratio 상한 |
| `ndvi_min` | 0.25 | DDV NDVI 하한 |
| `red_dark_max` | 0.15 | DDV red 상한 |
| `ddv_nir_min` | 0.20 | DDV NIR 하한 |
| `fill_sigma_px` | 300 | Gaussian fill σ |
| `smooth_sigma_px` | 480 | Main smoothing σ |
| `post_sigma_px` | 30 | 최종 post-smoothing σ |
| `out_res_m` | 20 | 출력 해상도 (m) |

### 7.2. 주요 CLI 옵션
| 옵션 | 기본 | 의미 |
|---|---|---|
| `--input PATH` | — | BlueBON L1C tiff (반복/glob 가능) |
| `--out PATH` | auto | 단일 입력 최종 출력 경로 |
| `--out-dir DIR` | 입력 폴더 | 배치 출력 디렉토리 |
| `--auto-maiac` | off | MAIAC 자동 다운로드 + mean 주입 |
| `--maiac-aod-mean FLT` | — | 수동 MAIAC 평균 (auto 보다 우선) |
| `--maiac-cache DIR` | `./maiac_cache` | MAIAC HDF 캐시 |
| `--maiac-date-window N` | 0 | ±N 일 granule 검색 |
| `--earthdata-user / --pass` | — | Earthdata 계정 |
| `--save-raw` / `--save-qa` | off | 진단 산출물 저장 |
| `--post-sigma-px FLT` | 30 | 후처리 스무딩 σ |
| `--smooth-sigma-px FLT` | 480 | Main smoothing σ |
| `--fill-sigma-px FLT` | 300 | Fill σ |
| `--radiance-scale FLT` | 0.3183 | DN→radiance 계수 |
| `--surf-blue-red-ratio FLT` | 0.575 | Kaufman ratio |
| `--ndvi-min FLT` | 0.25 | DDV NDVI 하한 |
| `--red-dark-max FLT` | 0.15 | DDV red 상한 |
| `--no-ndvi-dependent-ratio` | — | 고정 ratio 사용 |
| `--aerosol-profile` | continental | 6S aerosol (maritime/urban/desert) |
| `--atmosphere-profile` | auto | 6S 대기 profile |
| `--no-py6s` | — | Py6S 비활성 (fallback linear) |
| `--solar-z-deg FLT` | auto | solar zenith override |
| `--view-z-deg` / `--rel-az-deg` | 0 | view geometry override |

---

## 8. Troubleshooting

### DDV 픽셀이 너무 적음 (`Too few DDV pixels`)
- 겨울 산악·해안 장면에서 흔함
- 완화: `--ndvi-min 0.20 --red-dark-max 0.18`
- 또는 임계 하한: `--min-valid-ddv-fraction 0.0001`

### DDV AOD 가 모두 0 근처 (`WARNING: DDV AOD=XX%가 <0.01`)
- `surf_blue > blue_toa` 상황 → path reflectance 가 음수로 포화
- 원인: `radiance_scale` 과소, `surf_blue_red_ratio` 과대
- 점검: `--radiance-scale` 을 MAIAC 기반으로 재추정 (validate_bb_aod.py 의 `estimate_radiance_scale`)

### MAIAC 다운로드 실패
- 계정 미설정 → `.netrc`/env/CLI 중 하나 필수
- `MAIAC 검색 결과 없음` → `--maiac-date-window 2` 등으로 범위 확장
- 어떤 경우든 파이프라인은 DDV median 으로 fallback 하므로 중단되지 않음

### 공간 분포가 너무 뭉침 / 너무 거침
- `--smooth-sigma-px` (Main) 와 `--post-sigma-px` 를 조정
- 기본 480 + 30 이 v8 표준 (~2.5 km × ~600 m 등가 스무딩)

### 특정 지역 고 AOD 이상
- 과거 사례: 수원 하수처리장 인근 clear 영역에서 abnormal high
- 원인: surf_blue 추정이 local surface 와 불일치 (비옥지/공업지)
- 완화 방법 탐색 중 (v9 실험 계속, v8 에선 유지)

---

## 9. File Inventory

### 실행 스크립트
- **`bb_aod_pipeline.py`** — 메인 파이프라인 (retrieval + post-smooth + auto-MAIAC)
- `bb_aod_calval.py` — retrieval 엔진 (import 대상)
- `smooth_v8.py` — 독립 post-smoothing 도구 (파이프라인에 내장됨)
- `validate_bb_aod.py` — MAIAC 검증 및 radiance_scale 재추정
- `fit_to_maiac.py`, `pansharpen_to_maiac.py`, `blend_ddv_maiac*.py` — MAIAC 기반
  후처리 (파이프라인 외부에서 필요 시 실행)

### 레퍼런스
- `README.md` — Sentinel-2 AOD prototype (별개 알고리즘)
- `GOCI-II_ATBD(19.20.21.Aerosol_Retrieval)_Updates.pdf` — 알고리즘 개선 참고

### 데이터
- `bb_l1c_*_8band.tiff` — BlueBON L1C 입력
- `bb_aod_v1..v9b*.tif` — 개발 이력 산출물
- `validation/`, `validation_v9/` — MAIAC 검증 결과
- `maiac_cache/` — `--auto-maiac` 로 다운로드한 HDF 캐시

---

## 10. Version History

| 버전 | 핵심 변경 |
|---|---|
| v1–v3 | 초기 포팅, NaN 과다 / +0.288 bias |
| v4 | S2 수준 목표, 공간 분포 부자연스러움 |
| v5–v6 | aod_final.tif 분포 목표, 통계 조정 |
| v7 | brovey/pansharp/biascorr/fit 변형, 분포 수용 |
| **v8** | post-smooth (σ=30) 추가 → **최종 채택** |
| v9 / v9b | GOCI-II ATBD 기반 A1/A2/A4 개선 적용 (검증 중) |

현재 권장 설정은 **v8 + post-smoothing**, `bb_aod_pipeline.py` 로 자동화됨.

---

## 11. Quick Reference

```bash
# 한 줄로 신규 scene 처리
python3 bb_aod_pipeline.py --input bb_l1c_<date>_<time>_8band.tiff --auto-maiac

# 검증까지
python3 bb_aod_pipeline.py --input bb_l1c_...tiff --auto-maiac --save-qa && \
python3 validate_bb_aod.py \
  --bb-input bb_l1c_...tiff --bb-aod bb_aod_<date>_<time>_sm.tif \
  --out-dir validation_<date> --current-scale 0.3183
```
