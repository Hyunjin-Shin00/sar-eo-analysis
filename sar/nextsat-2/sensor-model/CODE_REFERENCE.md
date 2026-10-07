# NEXTSat-2 (차세대소형위성 2호) SAR 엄밀센서모델 기하보정 — 코드 설명

작성 2026-09-14. 한라산 LV1A SSC 12씬을 대상으로, **파일 안의 궤도·타이밍 정보만으로** 거리-도플러
엄밀센서모델을 세우고, DEM 지형 시뮬레이션으로 센서 편향을 추정·보정하여, 백록담 중심 6 km를 5 m 격자로
지오코딩한 파이프라인임. 기존 `halla_baengnokdam/n2/work` 코드는 참조하지 않고 처음부터 작성함.

이 문서만 읽으면 **무엇을 왜 했는지, 각 파일이 무엇을 어떻게 구현하는지, 어떤 규약과 함정이 있는지**를
알 수 있도록 썼음. 결과 수치와 산출물 설명은 `../Output/README.html` 에 있음.

---

## 0. 한눈에 보기

```
                 ┌──────────── 라이브러리 (모델) ────────────┐
  h5 (SSC) ──▶ n2reader ──▶ orbit ──▶ geometry ◀── tropo, dem
                                        │
     ┌──────────────────────────────────┼──────────────────────────────────┐
     ▼                                  ▼                                  ▼
  step01/02  검증                  step03/07  편향 추정            step04/05/09  지오코딩
  (격자·궤도·왕복·풋프린트)         (DEM 시뮬 ↔ 실영상 정합)         (지도격자 → 영상 샘플링)
                                        │                                  │
                                   step08 12씬 결합조정             step10 미세정합
                                                                  step06 Sentinel-1 교차검증
```

| 역할 | 파일 | 한 줄 |
|---|---|---|
| 읽기 | `n2reader.py` | 헤더를 SI 단위로 정리, 반쪽 규칙으로 SLC 읽기 |
| 궤도 | `orbit.py` | 상태벡터 60점 → 다항식 S(t), V(t), A(t) |
| **모델** | `geometry.py` | 거리-도플러 방정식, geo2rdr / rdr2geo, 룩사이드, 편향 슬롯 |
| 대기 | `tropo.py` | 표준대기 대류권 슬랜트 지연 |
| 지형 | `dem.py` | Copernicus DEM 읽기, EGM2008 지오이드, 면요소 법선·면적 |
| 정합 | `simulate.py` | DEM → SAR 시뮬레이션, 멀티룩, 마스크 상관 정합 |
| 실행 | `step01`~`step10` | 번호 순서가 처리 순서 |

파이썬 환경: `conda activate isce2_snaphu` (numpy 1.26, scipy, h5py, pyproj 3.7, rasterio, GDAL, matplotlib).
base 환경엔 numpy/h5py 만 있어 step02 이후는 돌지 않음.

---

## 1. 배경 — 왜 이 방식인가

### 1-1. SAR 픽셀은 (시각, 거리) 로 정의됨
광학은 "렌즈 중심에서 뻗은 직선"(공선조건)으로 픽셀↔지상을 잇지만 SAR엔 렌즈가 없음. 픽셀 하나는
**위성이 그 지점 정면을 지난 시각 t** (line) 와 **위성↔지점 거리 R** (sample) 두 측정값임. 따라서 모델은

```
① 거리     |P − S(t)| = R
② 도플러   (P − S(t)) · V(t) = 0          제로도플러: 시선 ⊥ 속도
③ 지표     P 가 WGS84 타원체 위 높이 h    (또는 DEM)
```
의 연립이다 (P 지상점, S/V 위성 위치·속도, 모두 ECEF). 자세각·도플러중심은 필요 없다 — 영상은 제로도플러로
재배열되어 있고 안테나가 어디를 향했든 "거리와 시각"은 바뀌지 않음.

### 1-2. 제품에 RPC·GCP 가 없음
LV1A h5 에는 지오코딩 정보가 `Projection ID = SLANT RANGE/AZIMUTH` 한 줄뿐이고, 코너·중심 좌표조차 없음.
대신 궤도 상태벡터 60점, 자세 60점, 제로도플러 시각, 픽셀 간격이 있음. 이것이 원재료이며, 이걸로 세우는
엄밀모델이 RPC 보다 정확하다 (RPC 는 엄밀모델의 근사 포장이다).

### 1-3. 편향은 남는다 — 그래서 추정함
헤더의 t0, R0 가 완벽하다고 믿을 수 없음. 처리기 내부 지연·시각 태깅 오프셋이 수십 m 급으로 남고
(소형 SAR 위성에서 일반적), 대류권 전파지연 2~3 m 가 있음. 대류권은 모델로 빼고(`tropo.py`), 나머지는
**DEM 으로 만든 시뮬레이션 영상과 실영상을 정합**해 잼. 산악지형에서 GCP 없이 쓸 수 있는 가장 강한 방법임.

---

## 2. 데이터 규약 — 반드시 알아야 할 것

### 2-1. LV1A SSC 의 SBI 레이아웃 결함 (가장 중요)
`S01/SBI` 가 `(2·L, C) int16` 로 **잘못 선언**되어 있음. 실제 레이아웃은

```
참 라인 m 의 복소표본 전체 = 선언행 2m, 2m+1 을 이어붙인 평탄버퍼, I/Q 가 int16 단위로 교대
    flat = SBI[2m : 2m+2].reshape(-1)          # 길이 2C
    z[k] = flat[2k] + 1j·flat[2k+1],  k = 0..C-1
→   z = SBI[2*l0 : 2*l1].reshape(l1-l0, C, 2)   # (라인, 샘플, [I,Q])
```
그리고 파일은 촬영 스트립의 **방위 앞 절반만** 담는다 (참 라인 0 .. 2L//2−1). 헤더의 `Line Samples` 와
`Zero Doppler Azimuth First/Last Time` 은 전체 스트립 기준임. 따라서
- 격자 (t0, dt) 는 헤더대로 세우고,
- "데이터가 존재하는 라인" = `n_avail = shape[0] // 2` 를 따로 관리함.

지리산 중복 7씬을 LV1B(정상 3D) 와 비교해 비트단위로 검증된 규칙임. 선언대로 읽으면 I/Q 가 섞인
잡음이 나오고, 짝수행=I/홀수행=Q 로 읽어도 틀림. `N2Scene.read_slc()` 가 이 규칙을 구현하며,
정상 3D 파일(`Taean_recent`, `LV1B`)은 `layout == "iq3d"` 분기로 자동 처리됨.

### 2-2. 단위와 시각
| 항목 | 값 | 비고 |
|---|---|---|
| 시각 (`State Vectors Times`, `Zero Doppler Azimuth *`) | **UNIX epoch 초** | 파일명 시각은 KST. 변환 불필요, 같은 기준 |
| 거리 시각 (`Zero Doppler Range First Time`, `Column Time Interval`) | **왕복** 초 | R = c·τ/2. ÷2 를 빼먹으면 590 km 가 1180 km |
| 위치·속도 | m, m/s, **ECEF** | dP/dt vs V 잔차 0.8 m/s 로 확인 (ECI 였다면 ~500) |
| 상태벡터 값 | float64 로 저장됐지만 **float32 양자화**(0.25~0.5 m) | 궤도 적합 잔차 0.3 m 가 바닥. 이 밑으로 쫓지 말 것 |
| `Look Angle` (S01) | 도, **부호 = 룩사이드** (음수 우측, 양수 좌측) | |
| `Columns Order` / `Lines Order` | NEAR-FAR / EARLY-LATE | sample 0 = 근거리, line 0 = 최초 시각 |
| 헤더 `Line Spacing` 1.158 m | 모델 지상 방위간격 1.112 m 와 4 % 다름 | **방위 px→m 환산은 모델값** (`AZ_M_PER_LINE`) |

### 2-3. 부호 규약 (코드 전체 공통)
- `side_sign`: **+1 우측룩, −1 좌측룩**. 위성 좌표계에서 "오른쪽" 벡터 `ĉ_right = n̂ × v̂` (n̂ 아래, v̂ 진행).
- 편향 슬롯: `t_eff(line) = t0 + dt_bias + line·dt`, `R_eff(sample) = r0 + dr_bias + sample·dr`.
- 정합 오프셋 규약: `real(l, s) ≈ sim(l − dl, s − ds)` — 모델이 (l, s) 에 예측한 지형이 실제로는 (l+dl, s+ds) 에 있음.
  `RangeDoppler.add_image_offset(dl, ds)` 가 `dt_bias −= dl·dt`, `dr_bias −= ds·dr` 로 반영함.
- 결과 해석: `dr_bias > 0` = 헤더 R0 가 실제보다 짧게 적혀 있음 (지형이 예측보다 근거리에 나타남).
  `dt_bias < 0` = 헤더 t0 가 실제보다 늦게 적혀 있음.
- 씬 쌍 정합 (`step09.coreg_pair(a, b)`): `a(r,c) ≈ b(r−dr, c−dc)`, `dE = dc·res`, `dN = −dr·res`.
  a 를 b 에 맞추려면 `ndimage.shift(a, (dN/res, −dE/res))`.

### 2-4. 높이
DEM (Copernicus GLO-30) 은 EGM2008 **정표고**. 모델에는 **타원체고 = 정표고 + N** 이 들어가야 함.
N ≈ +26.0 m @백록담 (pyproj `EPSG:9518 → 4979`, 네트워크 켜야 격자 다운로드됨; 실패 시 상수 26.0).
이걸 빼먹으면 거리 방향으로 그대로 26 m 밀림.

---

## 3. 라이브러리 모듈

### 3-1. `n2reader.py` — `N2Scene(path)`
h5 를 열어 필요한 값만 SI 단위로 속성에 담음.

| 속성 | 내용 |
|---|---|
| `t0, t_last, dt, t_mid` | line 0 시각, 마지막 시각(헤더 전체), 라인 간격 = 1/PRF, 중앙 |
| `r0, dr` | c·τ0/2, c·dτ/2 (m). dr ≈ 0.9993 m (96.8 MHz) 또는 2.0 m (48.4 MHz 모드 13씬) |
| `nlines_hdr, ncols, n_avail` | 헤더 라인수(전체), 샘플수, **실제 존재 라인수(절반)** |
| `sv_t, sv_pos, sv_vel` | 상태벡터 (N,), (N,3), (N,3) |
| `orbit_dir, look_side, side_sign, look_angle` | ASCENDING/DESCENDING, LEFT/RIGHT, ±1, 도 |
| `layout` | `"flat2d"` (LV1A 결함) / `"iq3d"` (정상) |

메서드: `t_of_line / line_of_t / r_of_sample / sample_of_r` (편향 없는 헤더 격자),
`read_slc(l0, l1, c0, c1) → (complex64 배열, 실제 범위)` — n_avail 로 자동 절단, `read_qlk()`, `summary()`.

### 3-2. `orbit.py` — `Orbit(t, pos, vel, t_ref, deg=7, window_s=None)`
- 시간을 `t − t_ref` 로 옮긴 뒤 (17억 초를 그대로 넣으면 수치 붕괴) `numpy.polynomial.Polynomial.fit` 로
  위치 xyz 각 성분 적합. 속도·가속도는 도함수.
- `position(t) / velocity(t) / acceleration(t)` — 배열 입력 지원, `(…,3)` 반환.
- 검증: `loo_error()` (한 점 빼고 적합 → 예측오차 max/rms), `fit_residual()`, `vel_residual()`.
- **차수 4 채택**. 4~9차 모두 잔차 0.3~0.4 m 로 같았고(양자화 바닥), 고차는 LOO 가 나빠졌음.

### 3-3. `geometry.py` — 모델 본체
좌표 유틸: `geodetic_to_ecef(lat, lon, h)`, `ecef_to_geodetic(P)` (반복법 1e-12 rad), `ellipsoid_normal(P)`.

`RangeDoppler(scene, orbit, dt_bias=0, dr_bias=0, tropo=False)`

- `_frame(t)`: 시각 t 의 위성 좌표계. `v̂ = V/|V|`, `n̂ = unit(−S − (−S·v̂)v̂)` (아래, ⊥v), `ĉ_right = n̂ × v̂`.
- **`geo2rdr(P)` (지상 → 영상)**: `g(t) = (P − S(t))·V(t) = 0` 을 뉴턴법으로 (`g′ ≈ −|V|² + (P−S)·A`).
  초기값 씬 중앙시각, 3~4회에 1 ns 수렴. 그 t 에서 `R = |P − S(t)| (+ 대류권 지연)`. 반환 `(t, R, line, sample)`.
  룩사이드가 필요 없다 — 정면을 지나는 순간은 좌우 무관하게 하나. 배열 입력에 벡터화되어 있어 수백만 점도 수 초.
- **`rdr2geo(line, sample, h)` (영상 → 지상)**: 3D 미지수를 룩각 θ 하나로 줄임.
  시선 `û(θ) = cosθ·n̂ + s·sinθ·ĉ_right` 는 ② 를 자동 만족, `P(θ) = S + R·û(θ)` 는 ① 을 자동 만족,
  남는 ③ `f(θ) = (Px²+Py²)/(a+h)² + Pz²/(b+h)² − 1 = 0` 을 뉴턴법 (`_solve_theta`). 초기 θ = |Look Angle|.
  `tropo=True` 면 먼저 h 로 한 번 풀어 P 를 얻고 지연을 R 에서 뺀 뒤 다시 풂.
- `rdr2geo_dem(line, sample, dem_h_func)`: h 를 DEM 으로 반복 갱신 (한라산 1950 m 에서 h=0 이면 3 km 오차).
- `side_of(P, t)`: `sign((P − S)·ĉ_right)` — 헤더 룩사이드와 일치해야 함.
- `incidence_deg(P, t)` (타원체 법선 기준), `look_deg(P, t)`.
- `add_image_offset(dl_px, ds_px)`: 정합 오프셋을 편향 슬롯에 반영 (규약 2-3).

검증 결과: 왕복 rdr2geo→geo2rdr 잔차 5.4e-4 px (h = 0/1000/2000 m).

### 3-4. `tropo.py`
Saastamoinen 건조항 (표준대기 기압 프로파일) + 습윤항 근사 (해면 0.15 m, 스케일고 2 km).
`slant_delay(h, lat, inc) = zenith(h, lat) / cos(inc)`. 해면 2.9 m, 정상부 2.2 m (@32.6°).
정확도 ±0.2 m — 궤도 양자화 0.5 m 가 바닥인 데이터에 충분. ERA5 로 바꾸려면 `zenith_delay()` 만 교체.
주의: SaTReC 처리기가 이미 대류권을 뺐는지는 불명 → 추정된 계기편향은 30~32 m 범위로 해석.

### 3-5. `dem.py` — `DEM(path)`
- 타일 전체를 메모리에 (3600², 52 MB). Point 등록이라 화소중심 기준 bilinear (`height_ortho`).
- `prepare_geoid(lat0, lat1, lon0, lon1)`: AOI 위 0.02° 격자로 EGM2008 N 계산 후 보간 (`geoid_N`, `height_ellip`).
- `block(lat0, lat1, lon0, lon1, oversample=2)`: 시뮬레이션용 격자. 15 m 로 오버샘플, 각 면요소의
  타원체고 `h_ell`, ECEF 단위법선 `n_ecef` (ENU 기울기 → ECEF), 경사면 실제 면적 `area`, `slope_deg`.

### 3-6. `simulate.py`
- **`simulate(rd, blk, bin_l, bin_s, n_lines, n_samples)`**: DEM 면요소를 `geo2rdr` 로 영상 좌표에 떨어뜨리고
  레이더가 보는 투영면적 `w = area · max(cos θ_loc, 0)` 을 `(bin_l × bin_s)` 빈에 누적 (`np.bincount`).
  위성을 향한 급경사 → 밝음, 등돌린 면 → 0, 여러 면요소가 한 빈에 겹치면(레이오버) 자연히 밝아짐.
  차폐(그림자)는 계산하지 않음 (32° 입사에서 58° 이상 경사 필요, 드묾). 반환: `sim, cnt, hmean`(빈 평균높이).
- `multilook_intensity(sc, bin_l, bin_s)`: 존재 라인 전체를 청크로 읽어 `|z|²` 를 빈 평균. 캐시 `Output/ml_<date>_<bl>x<bs>.npy`.
- `match(real_db, sim, mask, search, sigma)`: 둘 다 dB → 가우시안 고역통과(σ) → 시프트 격자에서 **마스크된 피어슨 상관**
  브루트포스 → 피크 주변 5×5 에 2차곡면 최소제곱 (`_peak2d`) 으로 서브빈 위치. 반환 `(dl, ds, r_peak, cc, dls, dss)`.

---

## 4. 실행 스크립트 (처리 순서)

### step01_grid_orbit.py — Step 1~2 체크포인트
격자·궤도 sanity: |S|−6371 ≈ 510 km, |V| 7.69 km/s, dP/dt vs V, 차수별 LOO, R0 vs H/cos(look),
SLC 읽기 검증(진폭 CV 0.534 ≈ 레일리 0.523; I/Q 가 섞였으면 0.76).

### step02_geometry.py — Step 3~6 검증
왕복정합(63점 × h 3종), 백록담 → (line, sample) 과 룩사이드 판별, 반대 룩사이드 해(592 km 서쪽 바다 → 오류 감지 가능),
입사각·인접샘플 지상거리(dR/sin inc 와 일치)·스와스 폭, 풋프린트(h=0, 보유구간/전체) → `Output/step02_footprint_<date>.geojson`.

### step03_bias_dem.py — Step 7 (피크 1개 간이판)
```
footprint_box → DEM.block → real_ml_db(27x16), real_ml_db(9x5)
coarse 27x16 (30 m) 정합 2회 → fine 9x5 (10 m) 2회 → 잔차 → 4분면 검사
```
핵심 파라미터: `H_LAND_MIN = 30 m` (바다·저지 제외), **`HP_SCALE_M = 120 m`** (고역통과 σ 를 물리 크기로 고정).
σ 를 bins 로 고정했을 때 fine 에서 방위가 ±10 px 진동했다 — 30 m DEM 이 표현하는 지형 스케일을 필터가 지워버린 것.
물리 스케일로 바꾸자 fine r_peak 0.15 → 0.28, 진동 소멸. 출력 `Output/step03_bias_<date>.json`, `step03_match_<date>.png`.

### step07_lsq.py — Step 7-LS (**정식 편향 추정**)
step03 의 시뮬·정합 규칙을 그대로 쓰되, 씬 전체 피크 1개 대신 **창 단위 다중관측 + 강건 최소제곱**.
```
1) coarse 전역 정합 → 초기 편향 적용
2) 30 m 격자(27x16 bins)를 60 bins(1.8 km) 창, 30 bins 간격(50 % 중첩)으로 나눠 창마다 (lc, sc, dl, ds, r)
   - window_offsets(): 창별 마스크 상관, 탐색 ±5 bins, 경계에 걸린 피크 폐기, min_fill 50 %
3) fit_scene(): Huber IRLS (robust_ls), 가중 r²
   - 상수모델 dl = a0, ds = b0            → 편향 + 표준오차
   - 선형모델 + a1·ℓ + a2·ŝ (정규화 좌표) → t 통계로 위치의존 검정
4) 최종 편향 = 초기 + a0/b0, JSON 에 결합조정용 geom (az_dir_EN, rg_dir_EN, inc, m/line, m/sample) 저장
```
스케일 실험 (20250611): 10 m bins → 창 30개, SE 5 px (무용) / 20 m → SE 0.9 px / **30 m → 191 창, SE 방위 0.75 px·거리 0.26 px (채택)**.
DEM 30 m 보다 촘촘히 비교해도 정보가 늘지 않고 잡음만 음. 함수 기본값이 이 구성이다 (`main(path, win=60, step=30, search=5, bins=(27,16), rmin=0.20)`).
출력 `Output/step07_lsq_<date>_27x16.{json,png}`.

### step08_all_scenes.py — Step 8 결합조정
12씬에 `step07.main()` 을 돌린 뒤 4모수 가중 LS:
```
dt_i = Δt_s + (D · â_i) / v_i              â_i 지상 방위 단위벡터(E,N), v_i 지상 방위 속도
dR_i = ΔR_s + (D · r̂_i) · sin(inc_i)       r̂_i 지상 거리 단위벡터(근→원), D = (dE, dN) DEM 수평오프셋
```
센서 편향은 위성에 붙어 있어 상승/하강에서 â 가, 좌/우룩에서 r̂ 가 부호를 바꾸고, DEM 오프셋은 땅에 붙어 있어 부호가
안 바뀐다 → 두 성분이 분리됨. 단위분산 s0 가 씬별 추가 오차(궤도)의 크기를 알려줌.
결과 (11씬; 20250110 은 보유 반쪽에 육지가 없어 창 0개): ΔR_s +31.15 ± 0.38 m, Δt_s −0.612 ± 0.239 ms,
DEM 동 +1.5 / 북 +4.8 m (χ² 651 → 383), **s0 = 4.6 → 씬별 궤도오차 방위 ≈ 2.9 m, 거리 ≈ 1.3 m**.
→ 시계열용으로는 **씬별 편향** 사용 결정 (공통상수는 ~3 m 산포를 남김). 출력 `Output/step08_joint.{json,png}`.

### step04_geocode.py — Step 9 지오코딩
```
python step04_geocode.py [h5] --res 5 --center 126.5292 33.3617 --size 6 [--bias step07|step03|none] [--nobias]
```
**역방향(backward) 지오코딩**: 지도 격자 화소마다 `(E,N) → (lat,lon) → DEM 타원체고 → ECEF → geo2rdr → (line, sample)`
→ 멀티룩 강도에서 bilinear. 영상을 지도로 "밀어 넣지" 않고 지도에서 "당겨 오므로" 구멍이 없고 리샘플링이 한 번.
- 멀티룩은 출력 해상도에 맞춰 **씬별 자동**: `ML_BL = round(res / az_m)`, `ML_BS = round(res·sin(inc) / dr)`.
  48.4 MHz 씬(dr = 2 m)은 거리 1 샘플이 이미 ~5 m 라 `4x1` 처럼 나온다 — 정상.
- 같은 루프에서 **국지입사각**(DEM 법선·시선) 과 **마스크** 생성: 레이오버 = 지상 거리방향으로 갈 때 sample 이 줄어드는 곳
  (거리 순서 역전), 등돌린면 = cos θ_loc ≤ 0.
- `--center/--size` 로 북향 정사각 AOI 타일 (반듯한 산출물), 없으면 보유구간 경계상자.
- `--bias`: step07 → step03 → 0 순 탐색. `--nobias` 안 주면 편향 미적용 비교본(`_nobias`)도 생성.
출력 `<date>_<tag>_{dB,locinc,mask}_utm<res>m[_aoi<size>km].tif` + preview PNG. GeoTIFF 태그에 편향·멀티룩·입사각 기록.

### step05_clip_rect.py — Step 9b 스트립 정렬 직사각형 클립
유효영역 외곽은 지형 높이 h/tan(inc) 만큼 원거리 쪽으로 휜다 (경계 이동량 vs DEM 높이 r = 1.000; DEM **해상도**와는 무관).
광학 정사영상처럼 반듯한 산출물이 필요할 때, 유효영역 안에 완전히 들어가는 가장 큰 스트립 정렬 직사각형으로 클립함
(근거리 경계를 최대 이동량만큼 안쪽으로). 20250611: 9.69 → 7.49 km 폭, 유효화소 21.7 % 손실. 출력 `*_clip.tif`, `_cliprect.geojson`.

### step06_s1_reference.py — Sentinel-1 교차검증
Microsoft Planetary Computer `sentinel-1-rtc` (익명 SAS 토큰) 를 STAC 검색 → COG 를 N2 격자로 `rasterio.warp.reproject`
→ 30 m 로 낮춰 고역통과 후 마스크 상관 → N2 가 S1 대비 (dE, dN). 옵션 `--pass ascending|descending|any --days N --s1date YYYYMMDD --n2suffix _nobias`.
**반드시 같은 룩방향 씬으로**: 하강(서쪽 봄) vs N2 A/R(동쪽 봄) 은 음영이 거울상이라 −46 m 가짜 오프셋이 남.
결과: ASC 20250413 동 +3 / 북 −5 m, ASC 20250811 동 +14 / 북 −4 m (S1 RTC 정확도 ~10 m 안), 편향 미적용 N2 는 −54 m.

### step09_stack.py — 백록담 5 m 타일 + 스택 + 상대정합 검증
```
python step09_stack.py --res 5 --size 6 --outdir ../Output/baengnokdam
```
12씬을 `step04.main(..., center=백록담, size=6, bias_src="step07")` 로 → AOI 에 자료 있는 10씬 →
그룹(AR / ALDR) 내 모든 씬 쌍을 `coreg_pair()` 로 상호상관 (모델만의 상대정확도 측정) → 그룹별 다중밴드 스택
(`dB`, 공통 유효화소 중앙값 0 dB 정규화 `dBn`, `validmask`), `scenes.csv`, `coreg_check.{csv,png}`, `thumbnails.png`.
결과: 20쌍 |시프트| 중앙 2.8 m, RMS 5.2 m, 최대 11.1 m. 전체커버 씬끼리 ≤ 0.6 px; 큰 잔차는 부분커버·적설 3씬.

### step10_fine_coreg.py — 미세정합 (데이터 기반 마무리)
`coreg_check.csv` 의 쌍 시프트를 **네트워크 최소제곱**(`s_a − s_b = d_ab`, 가중 r, 기준씬 고정) 으로 풀어
씬별 보정량 → `scipy.ndimage.shift` (dB/locinc bilinear + 유효가중 정규화, mask 최근접) → 개별 `*_coreg.tif` + `coreg_shifts.csv`
→ 20쌍 재검증. 결과 중앙 0.6 m, RMS 0.7 m, 최대 1.1 m (0.22 px). 원본(모델만) 타일은 상위 폴더에 보존.
이 단계는 센서모델 오차를 데이터로 덮는 것이므로 절대위치 논의에는 원본을, 시계열에는 `_coreg` 를 씀.

---

## 5. 편향 추정 방법의 설계 근거

| 선택 | 이유 |
|---|---|
| DEM 시뮬레이션 정합 (GCP/CR 아님) | 한라산엔 CR·고해상 정사영상이 없음. 산악에서 지형 신호가 가장 강하고 전 씬 자동 |
| 30 m 정합 격자 | DEM 해상도와 같아야 신호/잡음이 최적 (스케일 실험으로 확인) |
| 고역통과 σ = 120 m (물리) | DEM 이 표현하는 지형 스케일(≥ 60 m) 을 보존하면서 방사 저주파 제거 |
| 2모수 상수 (Δt_az, ΔR) | 처리기 시각/거리 태깅 오차의 자연스러운 표현. 선형항 t 검정 결과 대부분 |t| < 2 |
| 창 단위 + Huber LS | 표준오차와 위치의존 검정을 얻고, 이상치(레이오버 창 등) 자동 감쇠 |
| A/D·L/R 결합조정 | 센서편향 ↔ DEM 수평오차 분리에 유일한 GCP-free 수단. 기하가 다양한 12씬이라 가능 |
| 씬별 편향으로 지오코딩 | s0 = 4.6 → 씬별 궤도오차 ~3 m 실재. 공통상수는 그걸 못 흡수 |
| 대류권 표준대기 | 궤도 양자화 0.5 m 바닥에서 ERA5(±수 cm) 는 과잉 |

---

## 6. 알려진 함정 (겪은 순서)

1. **SBI shape** — 선언대로 읽으면 잡음. 2-1 규칙 필수.
2. **거리 시각 왕복** — c·τ/2.
3. **정표고 ≠ 타원체고** — geoid 26 m 를 빼먹으면 거리로 그대로 밀림.
4. **다항식 시간 원점** — 1.7e9 를 그대로 넣으면 5차에서 조건수 폭발.
5. **룩사이드 부호** — A/L 4씬이 있음. 틀리면 풋프린트가 592 km 서쪽 바다.
6. **h=0 rdr2geo** — 1950 m 산에서 3 km 오차. DEM 반복 필수.
7. **고역통과 σ 를 bins 로 고정** — fine 스케일에서 방위 ±10 px 진동. 물리 스케일로.
8. **정합 격자를 DEM 보다 촘촘히** — 창당 잡음만 증가 (SE 5 px). 30 m.
9. **함수 기본값 ≠ CLI 기본값** — `step08` 이 `step07.main()` 을 옛 기본값(9x5)으로 돌려 1차 실패. 지금은 함수 기본값도 30 m 구성이고 step08 은 명시 인자로 호출.
10. **교차검증에 반대 룩방향 S1** — 음영 거울상으로 −46 m 가짜 오프셋.
11. **유효영역 외곽이 휘는 것** — 오류가 아니라 h/tan(inc) 의 필연. 반듯한 산출물은 클립(step05) 또는 AOI 타일.
12. **WSL 절전** — 배치가 멈추고 로그 시각이 튐. 긴 배치는 `python -u` 로 로그를 실시간 기록.

---

## 7. 결과 요약 (상세는 `../Output/README.html`)

| 항목 | 값 |
|---|---|
| 모델 자기일관성 | 5.4e-4 px |
| 센서 편향 (11씬 결합) | ΔR_s +31.15 ± 0.38 m, Δt_s −0.612 ± 0.239 ms (지상 −4.3 m) |
| DEM 지상오프셋 | 동 +1.5 ± 0.9, 북 +4.8 ± 1.7 m |
| 씬별 궤도오차 (잔차 RMS) | 방위 ≈ 2.9 m, 거리 ≈ 1.3 m |
| 절대 위치 | ~5 m (S1 교차검증 3~14 m) |
| 씬 간 상대 (모델만 / 미세정합 후) | 중앙 2.8 m → **0.6 m**, 최대 11.1 → 1.1 m |
| 최종 산출물 | `Output/baengnokdam/output/` 10씬 × {amp, int, dB, locinc, mask} `_coreg.tif`, 5 m, UTM 52N |

---

## 8. 재현 순서

```bash
conda activate isce2_snaphu
cd C:\N2_InSAR\N2_Gemetric_Correction\Code

python step01_grid_orbit.py  [h5]                 # 격자·궤도 체크포인트
python step02_geometry.py    [h5]                 # 왕복정합·룩사이드·풋프린트
python step03_bias_dem.py    [h5]                 # (선택) 피크 1개 간이 편향
python step07_lsq.py         [h5]                 # 편향 (창 LS) — 씬별 json
python step08_all_scenes.py                       # 12씬 일괄 + 4모수 결합조정
python step09_stack.py  --res 5 --size 6 --outdir ..\Output\baengnokdam
python step10_fine_coreg.py --outdir ..\Output\baengnokdam\output
python step04_geocode.py [h5] --res 5 --center 126.5292 33.3617 --size 6   # 단일 씬 AOI
python step05_clip_rect.py   [h5]                 # 전체 스트립 클립 (10 m 결과 필요)
python step06_s1_reference.py --pass ascending --days 90 --s1date 20250413  # S1 교차검증
```
`[h5]` 생략 시 20250611. 멀티룩 캐시(`Output/ml_*.npy`)는 자동 생성·재사용.

## 9. 다른 지역·자료에 적용할 때
- `DEM_PATH` (step03/04) 와 `CENTER` (step09) 를 바꿈. DEM 은 EPSG:4326 1" 타일 가정 (`dem.py`).
- 정상 3D SSC(Taean_recent, LV1B) 는 `layout == "iq3d"` 로 자동 처리되며 `n_avail = 전체 라인`.
- `HP_SCALE_M`, 정합 bins 는 DEM 해상도에 맞춰 조정 (5 m DEM 이면 10 m bins 가 가능해진다).
- 평지(태안 갯벌 등)에서는 DEM 시뮬레이션 신호가 없다 → 해안선·인공구조물 GCP 등 다른 편향추정 수단이 필요.
