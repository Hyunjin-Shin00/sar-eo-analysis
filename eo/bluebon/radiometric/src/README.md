# eo/bluebon/radiometric/src

복사보정 파이프라인 구현.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`radcal/`](radcal/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `apply_fullstrip.py` | dark/PRNU 참조를 260616_193632 전체 스트립(16000x4096)에 적용해 보정 TIFF 저장. | TIFF | — |
| `apply_fullstrip_m.py` | dark/PRNU 참조를 260616_193632 전체 스트립(16000x4096)에 적용해 보정 TIFF 저장. | TIFF | — |
| `apply_to_observation.py` | dark/PRNU 참조를 실관측 RAW(260616_193632)에 적용해 열 고정패턴(stripe) 제거 검증. | CSV · PNG · TIFF | PNG 그림 · 텍스트/로그 |
| `apply_to_observation_m.py` | dark/PRNU 참조를 실관측 RAW(260616_193632)에 적용해 열 고정패턴(stripe) 제거 검증. | CSV · PNG · TIFF | PNG 그림 · 텍스트/로그 |
| `convert_dtype.py` | 최종 결과물 2종(회전보정 RGBN 병합 8밴드 T/J)을 float32 / uint16 로 각각 저장. | TIFF | — |
| `diag_rotation.py` | across-track(좌/중/우) 잔차 진단: 회전(yaw)/keystone 성분 확인. (rgbn, anchor=Red, T버전) | TIFF | — |
| `finalize_observation.py` | 관측영상 최종화: dark/PRNU 보정 -> 밴드 정합 -> 공통 crop -> 좌우 flip -> 저장. | CSV · PNG · TIFF | PNG 그림 · 텍스트/로그 |
| `make_correction_ref.py` | BlueBON dark / PRNU 보정 참조 데이터 산출 (MS1~MS7) | CSV · PNG · TIFF | PNG 그림 · 텍스트/로그 |
| `make_delta_adaptive.py` | 밴드별 적응형 δ_persistent 재생성. | TIFF | 텍스트/로그 |
| `make_delta_persistent.py` | 지속 가산 잔차 δ_persistent 생성 (dark 보강용). | TIFF | 텍스트/로그 |
| `make_flat_prnu.py` | flat 모드 PRNU 계수 생성 (넓은 across-track vignetting 까지 제거). | TIFF | — |
| `make_pan_ref.py` | PAN(band 0) dark/PRNU 참조 생성 — make_correction_ref.py 와 동일 방법 재사용. | TIFF | — |
| `merge_bands.py` | RGBN 중심 정합 결과를 밴드 순서 0~7 로 하나의 멀티밴드 TIFF 로 병합. | TIFF | — |
| `pipeline.py` | BlueBON 관측영상 전처리 파이프라인 — 최종 v5 (dark/PRNU 보정 + 밴드 정합). | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 · 이미지 |
| `pipeline_20260723.py` | BlueBON 관측영상 전처리 파이프라인 (dark/PRNU 보정 + 밴드 정합). | 파일 묶음 | 텍스트/로그 · 이미지 |
| `pipeline_dnonly_backup.py` | BlueBON 관측영상 전처리 파이프라인 — 최종 v5 (dark/PRNU 보정 + 밴드 정합). | 파일 묶음 | 텍스트/로그 · 이미지 |
| `pipeline_v5.py` | BlueBON 관측영상 전처리 파이프라인 — 최종 v5 (dark/PRNU 보정 + 밴드 정합). | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 · 이미지 |
| `rgb_from_8band.py` | 8밴드 TIFF -> RGB 합성 PNG (원해상도, 이미지만; 축/타이틀/여백 없음). | PNG · TIFF | 이미지 |
| `test_run.sh` | 복사보정 파이프라인 시험 실행 | — | — |
| `verify_correction_ref.py` | 저장된 dark/PRNU 참조를 재로드해 독립 검증 (MS1~MS7). | TIFF | — |

## 주요 인자

- `finalize_observation.py` — `--anchor-set` `--jitter-mode` `--suffix`
- `merge_bands.py` — `--var`
- `pipeline.py` — `--lp` `--no-delta` `--out-name` `--prnu-mode` `--sza` `--tdi` `--to-reflectance`
- `pipeline_dnonly_backup.py` — `--no-delta` `--out-name` `--prnu-mode`
- `pipeline_v5.py` — `--lp` `--no-delta` `--out-name` `--prnu-mode` `--sza` `--tdi` `--to-reflectance`
- `rgb_from_8band.py` — `--gamma` `--out` `--pct`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

### 진입점

```bash
python finalize_observation.py 
```
관측영상 최종화: dark/PRNU 보정 -> 밴드 정합 -> 공통 crop -> 좌우 flip -> 저장. 두 정합 버전을 모두 생성/저장: (T) 평행이동(translation) : *_obs_reg.tiff (J) jitter 보정(along-track) : *_

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--anchor-set` |  | `all` | anchor/jitter 기준을 최적화할 focus 밴드 집합 (all=8밴드, rgbn=Blue/Green/Red/NIR) |
| `--suffix` |  |  | 출력 파일명 접미사 (예: _rgbn) — 결과 별도 저장 |
| `--jitter-mode` |  | `row` | row=along-track 지터만, collin=across-track 선형(회전 yaw+keystone) 포함 |

```bash
python merge_bands.py 
```
RGBN 중심 정합 결과를 밴드 순서 0~7 로 하나의 멀티밴드 TIFF 로 병합. band 순서: 0=PAN, 1=Blue, 2=Green, 3=Red, 4=RE1, 5=RE2, 6=RE3, 7=NIR T(평행이동) -> obs260616_reg_rgbn_8band.

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--var` |  | `_rgbn` | 변형 접미사 (예: _rgbn, _rgbn_rot) |

```bash
python pipeline.py 
```
BlueBON 관측영상 전처리 파이프라인 — 최종 v5 (dark/PRNU 보정 + 밴드 정합). 입력 : <INPUT_DIR> 하위 8밴드 raw TIFF (YYMMDD_HHMMSS_{0..7}_gray.tiff) 처리 : ① 전 밴드(PAN 포함) 복사보정 = (r

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `input_dir` |  |  | 8밴드 raw TIFF 가 있는 관측 디렉터리 |
| `--prnu-mode` |  | `flat` | flat(기본)=full-width(넓은 vignetting 포함), residual=고주파 검출기 FPN만 |
| `--out-name` |  | `radiometric_v5` | 출력 하위폴더명 |
| `--no-delta` |  |  | 지속 가산 잔차(δ) 제거 끄기 |
| `--to-reflectance` |  |  | TOA reflectance(bb_l1a-ref_..._8band_f32.tiff) 추가 산출 (--sza 필요) |
| `--sza` |  |  | 태양천정각(deg) — --to-reflectance 시 필요 |
| `--tdi` |  |  |  |
| `--lp` |  |  |  |

```bash
python pipeline_20260723.py 
```
BlueBON 관측영상 전처리 파이프라인 (dark/PRNU 보정 + 밴드 정합). 입력 : <INPUT_DIR> 하위 8밴드 raw TIFF (YYMMDD_HHMMSS_{0..7}_gray.tiff) 처리 : ① MS1~7 = (raw - dark_ref[col]) 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `input_dir` |  | `<WORK_ROOT>/prep/data/20260721_Bushehr_Nuclear_Power_plant_Iran` | 8밴드 raw TIFF 가 있는 관측 디렉터리 |

```bash
python pipeline_dnonly_backup.py 
```
BlueBON 관측영상 전처리 파이프라인 — 최종 v5 (dark/PRNU 보정 + 밴드 정합). 입력 : <INPUT_DIR> 하위 8밴드 raw TIFF (YYMMDD_HHMMSS_{0..7}_gray.tiff) 처리 : ① 전 밴드(PAN 포함) 복사보정 = (r

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `input_dir` |  |  | 8밴드 raw TIFF 가 있는 관측 디렉터리 |
| `--prnu-mode` |  | `flat` | flat(기본)=full-width(넓은 vignetting 포함), residual=고주파 검출기 FPN만 |
| `--out-name` |  | `radiometric_v5` | 출력 하위폴더명 |
| `--no-delta` |  |  | 지속 가산 잔차(δ) 제거 끄기 |

```bash
python pipeline_v5.py 
```
BlueBON 관측영상 전처리 파이프라인 — 최종 v5 (dark/PRNU 보정 + 밴드 정합). 입력 : <INPUT_DIR> 하위 8밴드 raw TIFF (YYMMDD_HHMMSS_{0..7}_gray.tiff) 처리 : ① 전 밴드(PAN 포함) 복사보정 = (r

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `input_dir` |  |  | 8밴드 raw TIFF 가 있는 관측 디렉터리 |
| `--prnu-mode` |  | `flat` | flat(기본)=full-width(넓은 vignetting 포함), residual=고주파 검출기 FPN만 |
| `--out-name` |  | `radiometric_v5` | 출력 하위폴더명 |
| `--no-delta` |  |  | 지속 가산 잔차(δ) 제거 끄기 |
| `--to-reflectance` |  |  | TOA reflectance(bb_l1a-ref_..._8band_f32.tiff) 추가 산출 (--sza 필요) |
| `--sza` |  |  | 태양천정각(deg) — --to-reflectance 시 필요 |
| `--tdi` |  |  |  |
| `--lp` |  |  |  |

```bash
python rgb_from_8band.py 
```
8밴드 TIFF -> RGB 합성 PNG (원해상도, 이미지만; 축/타이틀/여백 없음). 밴드 순서 : 0=PAN,1=Blue,2=Green,3=Red,4=RE1,5=RE2,6=RE3,7=NIR RGB 매핑 : R=Red(band3), G=Green(band2), B=

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `tiff` |  |  | 8밴드 TIFF 경로 (u16 또는 f32) |
| `--pct` |  |  | 채널별 스트레치 percentile (기본 1 99) |
| `--gamma` |  | `1.4` | 감마 (기본 1.4) |
| `--out` |  |  | 출력 PNG 경로 (기본: <입력>_rgb.png) |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `apply_fullstrip.py` | `OUT_DIR` | `<WORK_ROOT>/prep/data/correction_ref_260606` |
|  | `OBS_DIR` | `<WORK_ROOT>/prep/data/260616_193632` |
| `apply_fullstrip_m.py` | `REF_DIR` | `<WORK_ROOT>/prep/data/correction_ref_260606` |
|  | `OUT_DIR` | `<WORK_ROOT>/prep/data` |
|  | `OBS_DIR` | `<WORK_ROOT>/prep/data/20260721_Sohae_Satellite_Launching_Station_…` |
| `apply_to_observation.py` | `OUT_DIR` | `<WORK_ROOT>/prep/data/correction_ref_260606` |
|  | `OBS_DIR` | `<WORK_ROOT>/prep/data/260616_193632` |
| `apply_to_observation_m.py` | `REF_DIR` | `<WORK_ROOT>/prep/data/correction_ref_260606` |
|  | `OUT_DIR` | `<WORK_ROOT>/prep/data` |
|  | `OBS_DIR` | `<WORK_ROOT>/prep/data/20260721_Sohae_Satellite_Launching_Station_…` |
| `make_correction_ref.py` | `DATA_ROOT` | `<WORK_ROOT>/prep/data` |
|  | `LIB_DIR` | `<WORK_ROOT>/prep/data/260607_094318` |
|  | `OUT_DIR` | `<WORK_ROOT>/prep/data/correction_ref_260606` |
|  | `PRNU_WINDOW` | `21` |
| `verify_correction_ref.py` | `OUT_DIR` | `<WORK_ROOT>/prep/data/correction_ref_260606` |
|  | `LIB_DIR` | `<WORK_ROOT>/prep/data/260607_094318` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `make_delta_adaptive.py`, `make_delta_persistent.py`
