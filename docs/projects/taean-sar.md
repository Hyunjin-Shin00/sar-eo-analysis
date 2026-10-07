# taean-sar — 해안사구 다중기법 SAR 분석

국산 X-band와 Sentinel-1 C-band에 **InSAR · Offset Tracking · ACD** 세 기법을
동일 절차로 교차 적용함.

> 전체 맥락은 [`HANDOVER.md`](taean-sar-handover.md)(인수인계),
> 방법론 논증은 [`METHODOLOGY.md`](taean-sar-methodology.md)에 있음.

## 처리 도구 — 무엇이 자체 코드인가

| 기법 | X-band (국산) | C-band (Sentinel-1) |
|---|---|---|
| **InSAR (위상)** | 두 경로: ISCE2 **위장** + **자체 파이썬** | **ISCE2 topsApp 2.6.3** |
| **Offset Tracking** | 자체 파이썬 | 자체 파이썬 |
| **ACD (진폭변화탐지)** | 자체 파이썬 | 자체 파이썬 |

X-band 위상 InSAR은 **서로 독립적인 두 경로**로 시도했고 같은 결론에 도달함.

1. **ISCE2 위장** ([`isce2-disguise/`](../../sar/nextsat-2/isce2-spoofing/)) — `stripmapApp`에 `sensor=COSMO_SKYMED_SLC`로
   N2 메타데이터를 주입. 매핑 전수 검증 완료(9.65 GHz, λ=3.107 cm, PRF 6380.8 Hz, None 필드 없음).
2. **자체 파이썬** (`insar/`) — 궤도 상태벡터와 Zero-Doppler 타이밍부터 직접 구현.

Offset Tracking과 ACD는 두 센서 모두 자체 파이썬임.

## 구성

```
common/compute_baseline.py    페어 적합성 — Bperp·Bcrit·입사각차·시간차
common/analyze_shp.py         AOI 폴리곤 분석
common/build_result_html.py   인터랙티브 결과 맵 생성

insar/improved_run.py         자체 InSAR 실행 (n2 | s1ab)
insar/n2insar.py              X-band InSAR 코어
insar/s1insar.py              S1 InSAR 코어
insar/run_s1_insar.py         S1 실행 래퍼
insar/step3_coreg_ifg.py      정합·간섭도 생성
insar/isce_unw2disp.py        ISCE2 언랩 → LOS 변위(cm)

offset-tracking/offset_track.py       NCC 정합 + 부화소 피크 추정
offset-tracking/build_ncc_vs_time.py  시간 베이스라인별 상관 품질

acd/n2_acd_pair.py            X-band 로그비
acd/n2_acd_ar.py              우측 룩 페어
acd/s1_ccd.py                 S1 변화탐지
acd/coh_amp_change.py         coherence·진폭 변화 결합

tidal/README.md               갯벌 조수 관측 (조위별 침수·노출)
```

## 실행

```bash
conda activate isce2_snaphu
python common/compute_baseline.py          # 먼저 페어 적합성 확인
python insar/improved_run.py n2            # 자체 InSAR
python offset-tracking/offset_track.py n2_0515x0614
python acd/n2_acd_pair.py
```

코드 상단 경로가 원본 작업폴더 기준이므로, 재실행 시 입력경로를 현지에 맞게 조정함.

## 부호 규약 — 반드시 확인할 것

- Offset Tracking의 **range(+) = 위성에서 멀어짐**
- InSAR의 **LOS(+) = 위성에 가까워짐**

둘은 **서로 반대**다. 합성신호(알고 있는 이동 주입)로 검증함.

## 결과의 과학적 한계 (핵심)

### 페어 심사 — 55개 중 1개

NP04 후보 **55개 중 InSAR 판정을 받은 페어는 단 1개**(20260515 × 20260614)다.
나머지 54개는 궤도방향·룩사이드 불일치로 탈락함.

| 항목 | 값 |
|---|---|
| 수직베이스라인 | Bperp −1419 m / Bcrit 3606 m = **0.39** (기하 우수) |
| 입사각차 | 0.09° |
| 오버랩 | 91% |
| 시간차 | 30일 |

### 그 페어마저 완전 탈상관

| 지표 | topophase.cor | phsig.cor |
|---|---|---|
| 평균 코히런스 | **0.281** | 0.290 |
| 중앙값 | 0.281 | 0.286 |
| 0.3 초과 | 27.6% | 37.6% |
| **0.5 초과** | **0.0%** | 0.1% |

평균 0.28은 사실상 추정기의 **노이즈 바닥**이고, 0.5를 넘는 픽셀이 하나도 없음.
필터링 후에도 코히런트 프린지가 없어 **언래핑은 수행하지 않았다**(의미가 없다).

### 대조실험 — 정합 오차가 아님을 입증

코히런스가 낮으면 코레지스트레이션을 의심하게 됨. 추측 대신 대조군을 만들었음.

| 실행 환경 | refinement | 코히런스 |
|---|---|---|
| WSL DrvFs (`/mnt/c`) | EPERM으로 **조용히 skip** | 0.281 |
| 리눅스 네이티브 FS | **실제 수행** (391개 오프셋 적용) | **0.281** |

**동일함.** 저코히런스는 정합 오차가 아니라 **시간적 탈상관**임.

> ⚠️ 이 DrvFs 함정은 재현 시 반드시 피해야 함. `/mnt/c`에서 돌리면 `misreg/misreg.dat` 쓰기가
> EPERM으로 실패하고, 위장 패치가 이를 "유효 오프셋 없음"으로 오인해 refine을 조용히 건너뜀.
> **ext4에서 실행하고 산출물만 복사할 것.**

---

**X-band는 사구에서 수 일 내 위상 탈상관함.** 30~35일 간격 위상 InSAR는 성립하지 않고,
위상 InSAR와 Offset Tracking 모두 잡음 지배임. 세 기법 중 **진폭변화탐지(ACD)만**
구조가 있는 관측을 제공함.

이것은 코드의 문제가 아니라 물리적 한계다 — 같은 데이터를 ISCE2에 넣어도 동일함.
따라서 결과는 **변위량이 아니라 "국산 위성 처리 방법론 시연"으로 프레이밍**하는 것이 정직함.

### 갯벌 조수 관측에서 추가로 확인된 것

- 보유 처리레벨(1A/1B/1C)에는 **후방산란계수(sigma0)가 없음.** 설계상 Level 1D에서만 제공됨.
  → 시점 간 절대 dB 비교 불가.
- X-band 개방수면은 **−20 dB 이하**인데 이 센서의 잡음등가 산란계수는 **−16~−17 dB**.
  즉 **물이 설계상 잡음바닥 아래**에 있음. 실측 물−육상 대비는 중앙 **−2.5 dB**로
  물리 기대치(−13~−20 dB)에 **10~17 dB 못 미침.** 어떤 보정으로도 이 대비는 늘지 않음.

## 페어 적합성이 모든 것을 좌우함

동일 궤도·룩 방향, 입사각 차, 수직베이스라인 비(Bperp/Bcrit), 시간차가 맞아야 함.
이 지역에서 **폴리곤을 덮는 유효 InSAR 페어는 단 하나**였음.
각 씬 입사각이 16~34°로 제각각이라 다중시점 스택은 성립하지 않음.
