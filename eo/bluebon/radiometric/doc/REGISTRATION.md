# BlueBON 밴드 정합(Registration) 알고리즘 — 상세 문서

대상 코드: `correction_ref_260606/pipeline.py` (함수 `main` §②, `pcc`, `residual_field`, `field_warp`, `valid_bounds`)
정합 방식 이름: **regjit_rgbn_rot** = (RGBN anchor) + (jitter + rotation, collin 모델)

---

## 0. 요약 (한 문단)
BlueBON 영상은 밴드마다 초점면 위치가 달라 **같은 지상점을 다른 시각에** 촬영하므로
밴드 간 공간 어긋남이 생김. 이를 (1) **phase correlation**으로 밴드별 shift를 추정하고,
(2) **촬영순서 인접쌍 체인**으로 누적한 뒤 (3) **RGBN 중심 최적 anchor**를 자동 선택하여 평행이동 정합하고,
(4) 평행이동 후 남는 **자세 지터(along-track) + 회전(yaw)/keystone(across-track)** 잔차를
**row·column 저차 모델(collin)**로 추정해 (5) **단일 remap**으로 한 번에 워프함.
마지막에 공통영역 crop + 좌우 flip.

---

## 1. 문제 정의: 왜 정합이 필요한가

- **밴드 간 초점면 오프셋**: 8밴드는 초점면(FPA)에서 along-track으로 물리적으로 떨어져 배치.
  위성이 진행하며 스캔하므로 밴드 b가 지상점 P를 찍는 시각과 밴드 b'가 P를 찍는 시각이 다름
  → 밴드 간 **주로 along-track(dy) 큰 오프셋 + across-track(dx) 작은 오프셋**.
- **자세 지터(attitude jitter)**: 촬영 중 위성 포인팅이 미세 진동. 밴드마다 촬영시각이 다르므로
  **오프셋이 라인(row)마다 달라짐** → 평행이동만으론 못 잡는 **along-track 물결형 잔차(±2.5px 관측)**.
- **회전(yaw) / keystone**: 밴드 간 미세 회전 → dy가 **컬럼(across-track)에 따라 선형 변화**
  → "중앙은 맞고 좌우 끝은 안 맞음". (관측: Blue +0.03°, RE3 −0.08°, 촬영시각 거리에 비례)

목표: 모든 밴드를 하나의 기준 밴드(anchor) 격자에 sub-pixel로 정렬. **warping은 하되,
밴드별 독립 국소 warp로 공간일치가 깨지지 않도록** 전역·매끄러운 저차 모델만 사용.

---

## 2. 기본 도구: Phase Correlation

함수 `pcc(ref, mov)` (pipeline.py L53–55):
```python
def prep_hp(im, sigma=3.0):           # high-pass 전처리
    x = im.astype(np.float64)
    return x - gaussian_filter(x, sigma=sigma)

def pcc(ref, mov):
    s, _, _ = phase_cross_correlation(prep_hp(ref), prep_hp(mov), upsample_factor=10)
    return np.array(s)                # (dy, dx)
```

- **phase correlation**: 두 영상의 교차전력스펙트럼 위상으로 평행이동량 추정. 밝기 스케일에
  둔감(정규화)해 **이종 스펙트럼 밴드 간에도 견고**.
- **high-pass 전처리(`prep_hp`)**: `image − Gaussian(σ=3)`.
  - DC/저주파(밴드별 밝기·조명 차이) 제거 → 구조(에지)만 남겨 **cross-spectral 상관 강화**.
  - 큰 DN 값에서 오차계산 overflow 방지.
- **upsample_factor=10**: 정수 상관 후 국소 DFT 업샘플로 **0.1px subpixel** 정밀도.
- **규약(중요)**: `phase_cross_correlation(ref, mov)` 이 돌려주는 `s`는
  **`scipy.ndimage.shift(mov, s)` 하면 mov가 ref에 정렬**되는 shift. (기존 파이프라인과 동일)

---

## 3. 촬영순서와 인접쌍 체인 추정

### 3.1 촬영순서
```python
CAP_ORDER = [1, 2, 3, 0, 7, 4, 5, 6]   # Blue,Green,Red,PAN,NIR,RE1,RE2,RE3
```
초점면 배치/촬영 시각 순서. **순서가 가까운 밴드끼리 오프셋이 작고 상관 신뢰도가 높다**
(시간차·지터 위상차가 작으므로). 그래서 먼 밴드쌍을 직접 상관하지 않고 **인접쌍만 상관**.

### 3.2 체인 누적 (main §②-a, L163–169)
```python
a = [pcc(img[O[k]], img[O[k+1]]) for k in range(7)]   # 인접쌍 shift (O=CAP_ORDER)
S = {O[0]: [0,0]}; acc = [0,0]
for k in range(7):
    acc += a[k]; S[O[k+1]] = acc.copy()               # O[0] 프레임 기준 누적 위치
anchor = ...                                          # §4
apply_shift = {b: S[b] - S[anchor] for b in O}        # anchor 프레임으로
```
- `a[k]` = O[k+1]을 O[k]에 맞추는 shift.
- 평행이동은 가법적이라 **누적** `S[O[m]] = Σ_{k<m} a[k]` = O[m]을 O[0] 프레임에 맞추는 shift.
- **인접상관만 쓰므로 이종 밴드(예: Blue↔NIR) 직접 상관의 불안정성을 회피**.

---

## 4. 최적 anchor 자동 선택 (RGBN 중심)

```python
RGBN = [1, 2, 3, 7]                                    # Blue,Green,Red,NIR
anchor = min(RGBN, key=lambda anc: max(hypot(S[b]-S[anc]) for b in RGBN))
```
- anchor 후보를 **RGBN(자연색+NIR)** 로 한정하고, **RGBN 내 최대 변위를 최소화**하는 밴드를 선택.
- 효과: RGBN이 서로 가장 잘 맞도록 중심을 잡음 → **자연색 RGB·NIR 산출물의 정합 품질 우선**.
  실측상 **Red**가 자주 선택됨(촬영순서 [B,G,R,PAN,NIR…]에서 RGBN의 시간 중앙).
- 최대 변위 최소화는 (a) 공통 crop 손실 최소, (b) 워프 외삽 최소 효과도 있음.

`apply_shift[b] = S[b] − S[anchor]` : 각 밴드를 anchor 프레임으로 옮기는 평행이동량.

---

## 5. 평행이동 베이스 (잔차 추정용, main §②-b, L173–179)

```python
top,bot,left,right = valid_bounds([apply_shift[b] for b in O], H, W)   # 공통 유효영역
regT[b] = nd_shift(img[b], apply_shift[b], order=1, cval=0)[top:bot+1, left:right+1]
```
- `nd_shift`(scipy, bilinear order=1)로 subpixel 평행이동 → **regT** (translation-정합 세트).
- `valid_bounds`: 각 밴드 shift로 인해 실데이터가 없는 가장자리를 배제한 **공통 사각영역** 계산.
- regT는 **잔차 필드(지터·회전) 추정의 입력**으로만 쓰이고, 최종 출력은 §7의 단일 remap이 만듦.

---

## 6. 잔차 필드: 지터 + 회전 (collin 모델) — 핵심

`residual_field(anchor_img, band_img, H, W)` (L82–112). regT의 anchor와 각 밴드 사이
**남은 오정합을 (row, column)의 저차 함수로 추정**함.

### 6.1 모델
```
dy(r,c) = ay(r) + by(r)·(c − c0)          # c0 = W/2
dx(r,c) = ax(r) + bx(r)·(c − c0)
```
- `ay(r), ax(r)` : **along-track 지터**(row마다 변하는 평행이동) — 물결형 성분.
- `by(r) = ∂dy/∂c` : **회전(yaw)**. dy가 컬럼에 선형 → "중앙 맞고 사이드 어긋남"을 잡음.
- `bx(r) = ∂dx/∂c` : **across-track 스케일/keystone**.
- 이름 **collin** = column-linear(컬럼 1차) + row 스무딩.

### 6.2 추정 절차 (격자 상관 → 컬럼 선형회귀 → row 스무딩)
```
along-track 윈도우 (높이 JIT_WIN=1200, 스텝 JIT_STEP=400) 슬라이드:
  각 윈도우를 across-track NX_BLK=7 블록으로 분할:
    블록 텍스처 std ≥ 0.4·전체std 인 블록만 사용 (저텍스처=수역 배제)
    pcc(anchor블록, band블록) -> (dy,dx),  |s|<=8 만 채택
  유효 블록 ≥3 개면:
    dy vs (c-c0) 1차 회귀 -> 절편 ay, 기울기 by
    dx vs (c-c0) 1차 회귀 -> 절편 ax, 기울기 bx
    (윈도우 중심 row 에 저장)
표본(ay,ax,by,bx) -> median_filter(size3) -> 전 row 선형보간 -> gaussian_filter1d(σ=JIT_SMTH=500)
```
- **블록 텍스처/상관 실패 필터**로 바다·구름 등 무의미 구간을 배제.
- **강한 row 스무딩(σ=500 rows)**: 지터·회전은 저주파(파장 ~수천 row)라 매끄럽게. 동시에
  **촬영시각이 비슷한 이웃 밴드는 거의 같은 필드**를 받아 **밴드간 상호 일치가 깨지지 않음**.
- anchor 밴드는 필드 = 0 (기준).

### 6.3 regT 좌표 → 원본 좌표 (`to_full`, L184–188)
필드는 regT(크롭됨) 기준으로 추정되므로, row에 `top` 오프셋을 반영해 전 이미지 row로 확장.
컬럼 중심은 `c0=W/2`(전폭)로 근사(크롭 left~수 px는 무시가능).

---

## 7. 단일 remap 워프 (main §②-d, L196–208; `field_warp` L115–125)

```python
tot_dy(r,c) = apply_shift[b].dy + ay(r) + by(r)·(c-c0)     # 체인 평행이동 + 잔차필드
tot_dx(r,c) = apply_shift[b].dx + ax(r) + bx(r)·(c-c0)
out[r,c] = map_coordinates(img_b, [r - tot_dy, c - tot_dx], order=1, cval=nan)   # 원본에 직접
reg[b] = fliplr( out[mY:H-mY, mX:W-mX] )                    # 공통 crop + 좌우 flip
```
- **핵심: (체인 평행이동 + 잔차 필드)를 합쳐 원본 영상에 "한 번의" remap** 적용.
  regT(1차 보간) 위에 또 워프하면 **이중 보간 블러**가 생기므로, 원본에서 단일 보간.
- `map_coordinates(order=1)` = bilinear. `cval=nan`으로 경계 밖 표시.
- **공통 crop margin** (L198–203): 모든 밴드의 최대 변위(컬럼항 `|by|·W/2` 포함)를 덮도록
  `mY, mX` 계산 → 전 밴드 동일 크기. 이후 **전 밴드 동일 좌우 flip**.
- anchor 밴드는 워프 없이 crop+flip만.

---

## 8. 파라미터 정리

| 파라미터 | 값 | 의미 / 효과 |
|---|---|---|
| `CAP_ORDER` | [1,2,3,0,7,4,5,6] | 촬영순서(인접쌍 체인 근거) |
| `RGBN` | [1,2,3,7] | anchor 후보(정합 우선 밴드) |
| `UPSAMPLE` | 10 | phase corr subpixel 0.1px |
| `prep_hp σ` | 3.0 | high-pass 강도(구조 강조·DC 제거) |
| `SHIFT_ORDER` | 1 | 평행이동 보간 차수(bilinear, overshoot 방지) |
| `JIT_WIN` | 1200 | 잔차 추정 along-track 윈도우 높이 |
| `JIT_STEP` | 400 | 윈도우 스텝(≈3배 오버랩) |
| `NX_BLK` | 7 | across-track 블록 수(회전 회귀용) |
| `JIT_SMTH` | 500 | row 스무딩 σ(밴드간 일치 보존) |
| 블록 텍스처 임계 | 0.4·std | 저텍스처(수역) 배제 |
| 상관 이상치 | \|s\|>8 (필드), >6 (초기) | wraparound 실패 제외 |

---

## 9. 전체 흐름 (의사코드)

```
img[b] = (raw_b - dark_b)*flat_b - δ_b            # 복사보정 (raw 열공간, 정합 이전)
a[k]   = pcc(img[O[k]], img[O[k+1]])              # 인접쌍 shift
S[b]   = cumulative(a)                            # O[0] 프레임 누적
anchor = argmin_{RGBN} max_{RGBN} |S[b]-S[anc]|   # RGBN 중심
apply_shift[b] = S[b]-S[anchor]
regT[b] = crop( nd_shift(img[b], apply_shift[b]) )# 평행이동 베이스
for b: ay,ax,by,bx = residual_field(regT[anchor], regT[b])   # 지터+회전 필드
for b: reg[b] = fliplr( crop( field_warp(img[b], apply_shift[b], ay,ax,by,bx) ) )  # 단일 remap
저장: 개별밴드 + 병합 8밴드 + RGB + shifts.csv
```

---

## 10. 왜 "일관적"인가 (사용자 원칙 부합)

- 정합은 **장면마다 shift 값이 다르지만**, 그 값을 **장면 자신의 데이터에서 동일 알고리즘**으로
  추정함. 고정 상수를 억지로 강요하지 않음 → 밴드 오프셋/지터가 장면마다 달라도 각각 올바르게 정렬.
- warping은 **단일 anchor 격자 + 전역 저차(row 함수 + 컬럼 1차) + 강한 스무딩**만 사용 →
  국소 elastic warp로 인한 밴드간 공간일치 저하가 원천적으로 없음.

---

## 11. 검증 결과

정합 잔차 RMS (anchor=Red, RGBN 중심):

| 밴드 | 평행이동(T) | +jitter | +jitter+회전(최종) |
|---|---|---|---|
| Blue | 0.74 | 0.55 | **0.14** |
| Green | 0.49 | 0.37 | **0.09** |
| Red | 0(anchor) | — | — |
| NIR | 1.31 | 0.85 | **0.28** |
| RE1 | 1.73 | 1.02 | **~0.14** |
| RE2 | 2.01 | 1.28 | **~0.18** |
| RE3 | 2.38 | 1.60 | **~0.33** |

- 진단으로 확인한 물리: along-track 물결형 잔차(±2.5px) = 자세 지터,
  dy의 컬럼 선형(±0.03~0.08°) = 회전(yaw). collin 모델로 둘 다 흡수 → sub-pixel 수렴.

---

## 12. 한계 / 주의

1. **regT 좌표 근사**: 잔차 필드는 크롭된 regT에서 추정 후 `top` 오프셋으로 전 이미지에 매핑.
   컬럼 중심 c0는 전폭 기준(크롭 left 무시). 실측 영향 미미(수 px).
2. **저텍스처 장면**: 바다·구름·사막 등 텍스처 없는 구간이 많으면 블록/윈도우 상관이 부족.
   유효 블록<3이면 해당 윈도우 스킵, 표본 부족 시 필드=0(정합=평행이동만).
3. **큰 오프셋 장면**: 오프셋이 매우 크면 crop 손실 증가(출력 크기 축소).
4. **모델 차수**: 컬럼 방향 1차(회전+keystone)까지만. 2차 이상 광학 왜곡은 미반영.
5. **에폭/센서 상태 무관**: 정합은 참조데이터에 의존하지 않으므로 에폭 영향 없음
   (복사보정 참조와 달리 정합은 장면 자기추정).

---

## 13. 관련 함수 색인 (pipeline.py)

| 함수 | 줄 | 역할 |
|---|---|---|
| `prep_hp` | 48 | high-pass 전처리 |
| `pcc` | 53 | high-pass phase correlation (subpixel) |
| `residual_field` | 82 | 지터+회전(collin) 필드 추정 |
| `field_warp` | 115 | 단일 remap 워프 |
| `valid_bounds` | 133 | 평행이동 공통 유효영역 |
| `main` §②-a | 161 | 인접쌍 체인 + anchor |
| `main` §②-b | 172 | 평행이동 베이스(regT) |
| `main` §②-c | 181 | 잔차 필드 추정 |
| `main` §②-d | 196 | 단일 remap + crop + flip |
| `write_csv` | 233 | shift/anchor 기록 |
