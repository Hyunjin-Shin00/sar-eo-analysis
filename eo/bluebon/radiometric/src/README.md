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
