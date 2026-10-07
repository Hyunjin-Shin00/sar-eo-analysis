# insar — 지표 변위 간섭측량

위상차로 밀리미터 단위 지표 변위를 재는 코드들.

> 국산 위성(NEXTSat-2) 전용 처리는 [`../n2-sensor-model/`](../n2-sensor-model/) 과
> [`../taean-sar/`](../taean-sar/) 에 따로 있다.

## 구성

| 디렉터리 | 내용 |
|---|---|
| `csk/` | COSMO-SkyMed(X-band) InSAR 처리 — ISCE2 기반 |
| `n2/` | N2 메타데이터를 CSK 포맷으로 변환해 ISCE2에 투입한 초기 시도 |
| `psinsar/` | ISCE2 `stackSentinel` 래퍼 + PS 추출·시계열 |
| `sbas/` | PyGMTSAR 기반 SBAS 산사태 변위 분석 |
| `utils/` | SLC 메타데이터 점검 |

## csk/ — COSMO-SkyMed InSAR

```
SLC (ref/sec) → 궤도·기하 계산 → 정합 및 오프셋 추정(coreg)
  → 보정된 secondary SLC → interferogram(flattened)
  → coherence 산출 → 필터링 → 언래핑(snaphu) → 지오코딩(.geo)
```

| 파일 | 역할 |
|---|---|
| `csk_main.py` | 처리 전 과정 실행 |
| `csk_viz.py` | 간섭도·coherence·변위 시각화 |
| `doppler_h5.py` / `doppler_xml.py` | 도플러 중심주파수 추출 (HDF5 / XML 메타데이터) |
| `read_h5_meta.py` | CSK HDF5 메타데이터 덤프 |
| `run_csk_unwrap_all.sh` | 여러 쌍 일괄 언래핑 |

## n2/ — N2 → CSK 변환 (초기 접근)

N2는 ISCE2가 직접 읽지 못한다. `n2_to_csk_final.py` 가 N2 메타데이터를
CSK가 기대하는 궤도·기하 파라미터 구조로 매핑해 ISCE2 센서 리더를 재사용한다.

> 이 우회 방식은 이후 **자체 엄밀센서모델**([`../n2-sensor-model/`](../n2-sensor-model/))로 대체되었다.
> 변환 코드 자체는 동작하지만, 산출된 간섭도의 품질은 보증하지 않는다.

## psinsar/ — PS-InSAR

ISCE2 `stackSentinel.py` 로 코레지스트레이션된 SLC 스택을 만든 뒤 PS를 추출한다.
처리 파라미터는 `stackSentinel_README.md` 참고.

| 파일 | 역할 |
|---|---|
| `run_stackSentinel.sh` | stackSentinel 실행 (NESD 코레지스트레이션) |
| `run_all_steps.sh` | 생성된 13개 run 파일 순차 실행 |
| `bbox_picker.html` | 브라우저에서 SNWE 바운딩박스 고르는 도구 |
| `ps_extract.py` | PS 후보 추출 · LOS 속도 · 시계열 산출 |
| `isce2_snaphu.yml` | conda 환경 정의 |

> StaMPS 파이썬 포팅본과 snaphu 바이너리는 제3자 저작물이라 포함하지 않았다.
> [StaMPS](https://github.com/dbekaert/StaMPS) 와 snaphu 는 각 업스트림에서 받을 것.

## sbas/ — SBAS 산사태

`landslide_sbas.py` — PyGMTSAR로 SBAS 시계열을 돌려 사면 변위 속도를 뽑는다.
파키스탄 · 네팔 · 경주 사례에 적용.

## 환경

```bash
conda env create -f psinsar/isce2_snaphu.yml
conda activate isce2_snaphu
```
