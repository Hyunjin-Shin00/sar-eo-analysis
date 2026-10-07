# 위성영상 MTF (Modulation Transfer Function) 정리

## 1. MTF란 무엇인가

**MTF(변조전달함수)** 는 영상 시스템이 **공간 주파수(spatial frequency)별로 대비(contrast)를 얼마나 잘 전달하는가**를 나타내는 함수입니다. 한마디로 "이 광학계/센서가 얼마나 선명한가"를 주파수 영역에서 정량화한 지표입니다.

### 정의의 뿌리

- **PSF (Point Spread Function)**: 점광원 하나가 센서에 맺힐 때 번지는 모양(임펄스 응답).
- **LSF (Line Spread Function)**: 선광원에 대한 응답(PSF를 한 방향으로 적분).
- **OTF (Optical Transfer Function)**: PSF의 푸리에 변환. 복소수이며 `OTF = MTF · e^(i·PTF)`.
  - **MTF = |OTF|** (크기 성분, 대비 전달)
  - **PTF (Phase Transfer Function)** = 위상 성분 (위치 이동/왜곡)

### 물리적 의미 (변조도 기반 정의)

정현파 격자(sinusoidal target)를 입력했을 때:

```
변조도(Modulation) M = (I_max − I_min) / (I_max + I_min)

MTF(f) = M_output(f) / M_input(f)
```

- 값은 **0 ~ 1** (또는 %). 특정 주파수 `f`에서 1이면 대비가 완벽히 보존, 0이면 완전히 뭉개짐.
- 저주파(넓은 물체)에서는 1에 가깝고, 고주파(미세 패턴)로 갈수록 0으로 감소하는 단조 감소에 가까운 곡선.

---

## 2. 왜 위성영상에서 MTF가 핵심인가

- **GSD(지상표본거리)만으로는 화질을 말할 수 없습니다.** GSD가 0.5 m라도 MTF가 낮으면 실제로 0.5 m 물체를 구분 못 합니다. GSD는 "샘플 간격", MTF는 "그 샘플이 얼마나 선명하게 담겼나"입니다.
- 판독 성능, 표적 탐지·인식, 후처리(pan-sharpening, 초해상, 정합), 그리고 **NIIRS(국가영상판독등급)** 산정에 직접 영향을 줍니다. GIQE(General Image Quality Equation)에서 MTF(특히 RER/MTFC 항)가 핵심 입력 변수입니다.
- 발사 후 궤도상에서 **성능 검·교정(Cal/Val)** 의 핵심 항목입니다. 시간이 지나며 초점 흐트러짐, 오염 등으로 MTF가 변하므로 주기적 모니터링이 필요합니다.

---

## 3. 시스템 MTF = 서브시스템 MTF의 곱

전체 시스템 MTF는 각 구성요소 MTF의 **곱(cascade)** 으로 표현됩니다 (선형·이동불변(LSI) 가정하에):

```
MTF_system(f) = MTF_optics · MTF_detector · MTF_motion · MTF_electronics · MTF_atmosphere
```

### 3.1 광학계 (Optics)

- **회절 한계 (Diffraction)**: 이상적인 원형 조리개의 한계. 차단 주파수(cutoff)
  ```
  f_cutoff = 1 / (λ · F#)      (F# = 초점거리 / 조리개 지름)
  ```
  회절 MTF는 이 주파수에서 0이 되는 알려진 형태를 가집니다. 대구경 망원경일수록(작은 F#) 고주파를 잘 전달합니다.
- **수차(Aberrations)와 초점 오차(defocus)**: 실제 광학은 회절 한계보다 낮음. 파면오차(WFE)로 표현되며 궤도 진입 후 열·구조 변형으로 초점이 흐트러질 수 있음.
- **중심 차폐(central obscuration)**: 카세그레인 등 반사망원경의 부경 차폐가 중간 주파수 MTF를 떨어뜨림.

### 3.2 검출기 (Detector)

- **화소 개구(pixel aperture)**: 유한한 크기의 화소가 빛을 적분 → **sinc 함수** 형태의 MTF.
  ```
  MTF_pixel(f) = |sinc(π · p · f)| = |sin(π·p·f) / (π·p·f)|,   p = 화소 피치
  ```
  나이퀴스트 주파수(`f_N = 1/2p`)에서 sinc 값은 약 **0.637(2/π)**. 즉 검출기만으로도 나이퀴스트에서 이미 상당한 감쇠가 존재.
- **전하 확산(charge diffusion)**, **crosstalk**: 인접 화소로의 전하 유출로 고주파 손실.
- **CTE(전하전송효율)**: TDI(Time Delay Integration) CCD에서 특히 중요.

### 3.3 플랫폼 운동 (Platform Motion) — 위성 특유의 핵심 요소

- **Image motion / smear (드리프트, 선형 이동)**: 적분(노출) 시간 동안 지표상이 이동 → 한 방향 블러. 위성 이동 방향 보정(TDI 동기, 자세 제어)이 어긋나면 발생.
  ```
  MTF_smear(f) = |sinc(π · a · f)|,   a = 적분 중 이동 거리
  ```
- **Jitter (진동성 지터)**: 반작용휠·구동부·냉각기 등에서 오는 고주파 자세 진동. 무작위 특성 → **가우시안 형태**로 근사되며 고주파를 크게 감쇠.
  ```
  MTF_jitter(f) = exp(−2·(π·σ·f)²),   σ = 지터의 RMS 변위
  ```
  σ(지터 RMS)가 화소 피치 대비 클수록 나이퀴스트 부근 MTF가 급감합니다. 소형/큐브위성은 자세 안정성이 낮아 지터 MTF가 병목이 되는 경우가 많습니다.

### 3.4 전자·신호처리 (Electronics)

- 아날로그 대역폭 제한, 샘플링, 온보드 압축(예: JPEG류 손실 압축), MTF 보정 필터(MTFC, 후술)의 영향. MTFC는 MTF를 **1 이상으로 부양**시킬 수도 있음(부스팅).

### 3.5 대기 (Atmosphere)

- **난류(turbulence)**: 고고도 위성은 장노출 아님이라 지상 망원경만큼 심하지 않지만 존재.
- **에어로졸/산란(adjacency effect)**: 인접 화소 간 광 혼합으로 대비 저하. 엄밀히는 시스템(하드웨어) MTF와 구분해서 다루는 경우가 많음(궤도상 MTF 측정 시 오차원인).

> 참고: 여러 연구가 궤도상 MTF 추정 시 **대기·BRDF·표적 비이상성**을 무시해 결과가 왜곡된다고 지적합니다 (아래 "흔한 오류" 참조).

---

## 4. 공간 주파수, 나이퀴스트, GSD의 관계

- **공간 주파수 단위**: cycles/mm(초점면) 또는 cycles/pixel, cycles/m(지상).
- **나이퀴스트 주파수**: `f_N = 1/(2p)` (검출기 피치 `p`). 지상 기준으로는 `1/(2·GSD)`. 이보다 높은 주파수는 **에일리어싱(aliasing)** 으로 위장.
- **핵심 설계 지표 — MTF@Nyquist (MTFN)**:
  - 대략 **0.05~0.15**: 에일리어싱 억제형(부드러운 영상, 아티팩트 적음).
  - 대략 **0.2~0.5**: 선명하지만 에일리어싱 위험 증가.
  - 고해상 상용 위성은 대체로 **나이퀴스트에서 0.1~0.3** 대를 목표로 설계.
- **Q 파라미터 (샘플링 품질)**: `Q = λ·F# / p`. 광학 차단주파수와 나이퀴스트의 비율.
  - `Q ≈ 2`: 광학 차단 = 나이퀴스트 (에일리어싱 없음, 하지만 흐릿).
  - `Q < 1`: 언더샘플링(대부분 고해상 위성, 예 IKONOS/WorldView 계열은 Q<1로 선명함을 택하고 일부 에일리어싱 감수).
- **RER (Relative Edge Response)**: MTF와 밀접한 공간영역 지표로 GIQE에서 사용.

---

## 5. MTF 측정 방법

### 5.1 발사 전 실험실 측정 (Pre-launch)

- 시준기(collimator) + 정밀 타겟(슬릿, 핀홀, 4-bar 격자, 슬랜티드 엣지)로 각 부품 및 통합 시스템 MTF 측정.
- 간섭계로 파면오차(WFE) 측정 → 광학 MTF 산출.
- 진동 시험 데이터로 지터 MTF 예측. 최근 연구는 **측정 기반 pre-launch MTF 예측**으로 궤도 성능을 미리 추정.

### 5.2 궤도상 측정 (On-orbit) — 위성에 직접 접근 불가하므로 간접법

지표의 특정 타겟을 촬영해 역산합니다.

**(a) Slanted-Edge Method (경사 엣지법) — 사실상 표준, ISO 12233 기반**
- 밝고 어두운 영역이 만나는 **직선 경계**를 화소 격자에 대해 약간 기울여(2~10°) 촬영.
- 여러 스캔 라인을 서브픽셀로 재배열(oversampling) → **ESF(Edge Spread Function)** 구성 → 미분 → **LSF** → 푸리에 변환 → **MTF**.
- 타겟 예: 대형 인공 타겟(흑/백 tarp, 에지 패널), 활주로/공항 경계, 큰 건물 옥상 경계, 댐·다리 경계, 눈밭-그림자 경계 등.
- 개선 기법: **Zernike 모멘트 + Otsu 임계값**으로 서브픽셀 엣지 위치를 정밀화(잡음에 강함).

**(b) Pulse / Line Method (펄스·선법)**
- 좁은 밝은 선(다리, 도로 페인트 라인) 또는 인공 tarp 스트립 촬영 → LSF 직접 획득.

**(c) Point / Impulse Method (점광원법)**
- 미러 어레이(거울 반사판), 인공 점광원(convex mirror), 별·달 등으로 PSF 직접 관측.

**(d) 인공 교정장(예: 프랑스 Salon-de-Provence, 미국 Stennis, Baotou(중국) 등)**
- 정밀 제작된 흑백 엣지/펄스 타겟 세트를 정기 촬영해 여러 위성 간 상호 교정.

대표 적용 사례: **IKONOS**(엣지+펄스법), **OrbView-3**, 각종 고해상 위성의 ISO 12233 슬랜티드 엣지 평가.

### 5.3 궤도상 MTF 추정에서 흔한 오류(연구가 지적하는 함정)

- 대기 산란/adjacency 효과 미보정 → MTF 과소평가.
- 엣지가 실제로 완벽한 계단이 아님(그림자, 페인트 열화, BRDF 방향성) → 편향.
- 엣지 각도·정합 부정확, 재배열(binning) 오차, 잡음·압축 아티팩트.
- 한쪽(밝은→어두운) 방향만 사용 시 비대칭 오차.
- 이런 파라미터 추정이 어긋나면 "그럴듯하지만 틀린" 결과가 나오므로 신뢰구간·복수 타겟 검증이 필수.

---

## 6. MTF 보정·영상 복원 (Restoration)

- **MTFC (MTF Compensation / Restoration)**: 알려진 시스템 MTF의 역필터를 적용해 대비 회복. 온보드 또는 지상 처리.
  - 단순 역필터는 **잡음 증폭**이 심함 → **Wiener 필터**, 정규화 역필터, 제약 최소자승법 사용.
  - 과도한 부스팅은 **엣지 오버슈트(ringing)·잡음 증가**를 부름. NIIRS는 적정 부스팅 시 향상되나 과보정 시 역효과.
- **디컨볼루션(deconvolution)**: PSF 추정 후 복원(Richardson-Lucy 등). 최근에는 **딥러닝 기반 복원/초해상**이 MTF 보상과 결합.
- 목적: 판독성 향상, 하지만 "정보를 만들어내지 않음" — 나이퀴스트 이상 정보는 복원 불가.

---

## 7. 대표적인 수치 감각 (예시)

| 구성요소 | 나이퀴스트에서 대략적 MTF 기여 |
|---|---|
| 회절 한계(이상 광학, Q≈1) | ~0.4 이상 |
| 화소 개구(sinc) | ~0.64 |
| 실제 광학(수차·초점) | 0.5~0.8 배 추가 감쇠 |
| 지터·smear | 안정 플랫폼 0.9+, 불안정 소형위성 0.5 이하 가능 |
| **통합 시스템 MTFN(대형 고해상 위성)** | 대략 **0.1 ~ 0.25** |

(정확한 값은 위성별 설계에 따라 크게 다르며, 실제 스펙은 각 운영사 문서를 확인해야 합니다.)

---

## 8. 실무 체크리스트 (위성영상 MTF 다룰 때)

1. **MTF는 방향성이 있다** — along-track(비행방향, smear·TDI 영향)과 cross-track이 다름. 두 방향 모두 측정·보고.
2. **밴드별로 다르다** — PAN vs 다분광, 파장별 회절·초점 차이.
3. **온보드 처리 확인** — 압축·MTFC가 이미 적용됐는지에 따라 "raw MTF"와 "delivered MTF"가 다름.
4. **에일리어싱 판단** — MTFN이 높으면 미세 반복패턴에서 모아레·에일리어싱 검사.
5. **시계열 모니터링** — 궤도 진입 초기 초점 조정(refocus) 후, 그리고 수명 동안 열화 추적.
6. **GSD와 분리해서 보고** — "유효 해상도"는 GSD + MTF의 조합.

---

## 참고 자료 (Sources)

- [Estimation of System MTF of EO Satellite by Slanted Edge Method](https://www.academia.edu/85902883/Estimation_of_System_MTF_of_EO_Satellite_by_Slanted_Edge_Method)
- [MTF Measurement by Slanted-Edge Method Based on Improved Zernike Moments (Sensors, MDPI)](https://www.mdpi.com/1424-8220/23/1/509) · [PMC 버전](https://pmc.ncbi.nlm.nih.gov/articles/PMC9823301/)
- [MTF measurement method and results for the OrbView-3 satellite](https://www.researchgate.net/publication/228880106_Modulation_transfer_function_measurement_method_and_results_for_the_Orbview-3_high_resolution_imaging_satellite)
- [MTF assessment of high resolution satellite images using ISO 12233 slanted-edge method](https://www.researchgate.net/publication/253078659_MTF_assessment_of_high_resolution_satellite_images_using_ISO_12233_slanted-edge_method)
- [IKONOS Satellite on-Orbit MTF Measurement using Edge and Pulse Method](https://www.researchgate.net/publication/266339153_IKONOS_Satellite_on_Orbit_Modulation_Transfer_Function_MTF_Measurement_using_Edge_and_Pulse_Method)
- [Frequent oversights in on-orbit MTF estimation of optical imagers onboard EO satellites](https://www.researchgate.net/publication/382879622_Frequent_oversights_in_on-orbit_modulation_transfer_function_estimation_of_optical_imager_onboard_EO_satellites)
- [Measurement-driven pre-launch MTF prediction for high-resolution spaceborne imaging systems (Applied Optics)](https://opg.optica.org/ao/abstract.cfm?uri=ao-65-22-7297)
- [CubeSat Camera Resolution: Why MTF matters (Simera Sense)](https://simera-sense.com/news/cubesat-camera-resolution-why-mtf-matters/)
- [Integrated Structural–Optical Modeling of CubeSat Line-of-Sight Jitter (Ansys Optics)](https://optics.ansys.com/hc/en-us/articles/49641209578003-Integrated-Structural-Optical-Modeling-of-CubeSat-Line-of-Sight-Jitter-Under-Random-Vibration)
