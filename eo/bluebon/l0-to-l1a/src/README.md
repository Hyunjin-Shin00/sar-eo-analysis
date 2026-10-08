# eo/bluebon/l0-to-l1a/src

DN → Radiance → TOA 반사도 변환, RGB 합성, 밴드 처리.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`03_code/`](03_code/) |  |
| [`sharepoint/`](sharepoint/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `aws_upload.sh` | AWS S3 업로드 | — | — |
| `dir_restruct.sh` | 장면 폴더 구조 재정렬 | TIFF | — |
| `list_unprocessed_files.sh` | 아직 처리되지 않은 장면 목록 산출 | PNG · TIF · TIFF | — |
| `loop.sh` | 미처리 장면을 반복 감시하며 전처리 | — | — |
| `make_rgb_png.py` | 방사보정 TIFF를 이용해 contrast/gamma 조절된 RGB PNG를 생성하는 코드 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `merge_bands.py` | 단일밴드 TIFF 파일을 하나의 멀티밴드 TIFF로 합치는 스크립트 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `merge_bands.sh` | Usage: merge_bands.sh <radiometric_dir> MS1,MS2,MS3_DN_dark_rc_p.tiff 를 3밴드 MS123_DN_dark_rc_p.tiff 로 병합 | — | — |
| `plot_histogram.py` | data 폴더의 tiff 파일들을 타임스탬프별로 그룹화하여 히스토그램 PNG를 생성. | GeoTIFF · 파일 묶음 | PNG 그림 |
| `plot_histogram_leop.py` | GDrive LEOP 폴더의 2026년 1~3월 영상 히스토그램 생성. | GeoTIFF · 파일 묶음 | PNG 그림 |
| `rename_levels.sh` | 처리 레벨(L1A/L1B/L1C) 표기에 맞게 파일명 정리 | — | — |
| `run.sh` | 전처리 배치 진입점 — 장면 폴더를 순회하며 DN→L→TOAR→RGB | — | — |
| `run_band.sh` | 단일 밴드 전처리 실행 | — | — |
| `run_band_dir.sh` | 디렉터리 단위 밴드 전처리 실행 | — | — |
| `run_nightOb.sh` | 야간 관측 영상 전용 전처리 실행 | — | — |
| `tmp.sh` | 임시 작업 스크립트 | — | — |
| `upload.sh` | 산출물 업로드 | — | — |
| `upload4GDrive.sh` | 구글 드라이브 업로드 | — | — |
| `upload4GDrive_old.sh` | 구글 드라이브 업로드 (구판) | — | — |

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
python merge_bands.py 
```
단일밴드 TIFF 파일을 하나의 멀티밴드 TIFF로 합치는 스크립트 8밴드 구성 (MS0~MS7 모두 있는 경우): 0: PAN (MS0) 1: Blue (MS1) 2: Green (MS2) 3: Red (MS3) 4: RedEdge1 (MS4) 5: RedEdge2 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `input_dir` |  |  | TIFF 파일이 있는 디렉토리 (경로에 yymmdd_HHMMSS 패턴 포함 필요) |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `plot_histogram.py` | `DATA_DIR` | `<WORK_ROOT>/prep/data` |
|  | `BINS` | `256` |
| `plot_histogram_leop.py` | `OUT_DIR` | `<WORK_ROOT>/prep/data/cloud/histogram` |
|  | `BINS` | `256` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `make_rgb_png.py`
