# eo/bluebon/geometric/Code

정합·RPC 적합·스트립 보정·일괄 처리.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`03.geometric_correction/`](03.geometric_correction/) |  |
| [`web_app/`](web_app/) | 처리 상태를 보는 웹 UI (FastAPI + React). |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `Download_BlueBON.py` | 처리 대상 장면을 시트에서 읽어 내려받기 | CSV | CSV |
| `Full_processing_v2.py` | BlueBON 기하보정 통합 파이프라인 v2 | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `Strip_correction_3D.py` | Strip_correction_3D.py | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `Strip_correction_all.py` | Strip_correction_all.py | GeoTIFF · 파일 묶음 | GeoTIFF · 텍스트/로그 |
| `batch_processing.py` | BlueBON 배치 기하보정 처리 스크립트 | GeoTIFF · 파일 묶음 | — |
| `eval_utils.py` | 정합 정확도 평가 유틸 (RMSE·잔차 통계) | GeoTIFF | PNG 그림 |
| `pipeline_config.py` | BlueBON Pipeline Configuration | TIF · TIFF | — |
| `pipeline_gui.py` | BlueBON Geometric Correction Pipeline — GUI Interface (tkinter) | GeoTIFF | — |

## 주요 인자

- `Full_processing_v2.py` — `--center-lat` `--center-lon` `--input` `--intermediate` `--lat` `--lon` `--res` `--save-intermediate` `--segment`
- `Strip_correction_3D.py` — `--base_dir` `--legacy_dem` `--modern_dem` `--target`
- `Strip_correction_all.py` — `--base_dir` `--direction` `--legacy_dem` `--strict-dem-nodata`
- `batch_processing.py` — `--batch-count` `--dry-run` `--match-window-sec` `--no-download` `--only-perform-o` `--output-dir` `--sheet` `--tiff-dir`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `BLUEBON_SHEET_ID` | 미션 시트 ID |
| `PROJ_DATA` | PROJ 자료 경로 |

### 진입점

```bash
python Full_processing_v2.py --help
```
- 이 파일은 하위 명령마다 파서가 따로 있음. 아래 표는 전체 인자를 모은 것임
BlueBON 기하보정 통합 파이프라인 v2 ==================================== GUI 인터페이스를 통한 입력 + 새로운 출력 구조 + 모자이킹 통합 입력: - GUI를 통한 TIFF 파일 선택 - 중심 좌표 (위도, 경도) 입력 - 분할

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--input` |  |  | 처리할 입력 TIFF 경로 (bb_{level}_{yyyymmdd}_{HHMMSS}_{N}band.tiff 권장) |
| `--center-lat` |  |  | 중심 위도 |
| `--center-lon` |  |  | 중심 경도 |
| `--segment` |  | `3` | 영상 분할 개수 |
| `--save-intermediate` |  |  | 중간 결과물(썸네일 등) 저장 |
| `--res` |  | `4.8` | 기하보정 target resolution (기본: 4.8) |
| `--input` |  |  | 처리할 입력 TIFF 경로 (bb_{level}_{yyyymmdd}_{HHMMSS}_{N}band 형식으로 입력) |
| `--lat` |  |  | 중심 위도 |
| `--lon` |  |  | 중심 경도 |
| `--segment` |  | `3` | 영상 분할 개수 |
| `--intermediate` |  |  | 중간 결과물(썸네일 등) 저장 |
| `--res` |  | `4.8` | 기하보정 target resolution (기본: 4.8) |

```bash
python Strip_correction_3D.py --base_dir <값> --target <값>
```
Strip_correction_3D.py Top/Bottom 영상 기하보정 (3D RPC 기반) 이 스크립트는 Strip_correction_v2.py의 확장 버전으로, 단순 2D 다항식 변환 대신 3D RPC(Rational Polynomial Coefficients

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--base_dir` | ● |  | 데이터 디렉토리 |
| `--target` | ● |  | 타겟 세그먼트 |
| `--modern_dem` |  |  | nodata -32768·RPC_DEM_MISSING_VALUE=-32768·안전 출력범위 샘플 (Copernicus 권장) |
| `--legacy_dem` |  |  | 붙여넣기 스크립트와 동일(명시). 직접 실행 시 기본이 legacy라 덜 필요함 |

```bash
python Strip_correction_all.py --base_dir <값>
```
Strip_correction_all.py Bottom 영상이 정상(Orthorectified)일 때, 이를 바탕으로 Center를 보정(외삽)하고, 보정된 Center를 바탕으로 Top을 연쇄적으로 보정(외삽)하는 기하보정 스크립트임. (3D RPC 기반)

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--base_dir` | ● |  | 데이터 디렉토리 |
| `--direction` |  | `upward` | 외삽 방향 (upward: Bottom->Center->Top, downward: Top->Center->Bottom) |
| `--legacy_dem` |  |  | 구버전과 유사: DEM nodata/NaN→0, Geoid=sample_geoid, RPC_DEM_MISSING_VALUE=0 |
| `--strict-dem-nodata` |  |  | DEM/Geoid 메타 nodata를 파일 그대로 사용 (미지정·0을 내부 0.0으로 치환하지 않음). 기본은 빈 픽셀·nod |

```bash
python batch_processing.py 
```
BlueBON 배치 기하보정 처리 스크립트 ===================================== All_data 폴더의 TIFF 영상들을 Excel 좌표와 매칭하여 배치 단위로 기하보정 처리 사용법: python batch_processing.py --b

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--batch-count` |  | `1` | 동시에 처리할 배치 개수 (기본값: 1) |
| `--dry-run` |  |  | 매칭 결과만 출력하고 실제 처리는 하지 않음 |
| `--sheet` |  | `/mnt/hdd/BB/BlueBON_Geometric_Correction.csv` | 좌표/시간 시트 파일 경로 (.csv 또는 .xlsx). 기본: /mnt/hdd/BB/BlueBON_Geometric_Corr |
| `--no-download` |  |  | 시트/영상 자동 다운로드를 건너뜀 (Dataset에 이미 파일이 있을 때) |
| `--only-perform-o` |  |  | 시트의 Perform 컬럼이 'o'인 행만 처리 (기본: CSV는 자동으로 적용, XLSX는 Perform 컬럼이 있을 때만  |
| `--tiff-dir` |  | `/mnt/hdd/BB` | TIFF 파일 폴더 경로 |
| `--match-window-sec` |  | `600` | 시트 시간과 파일명 시간 매칭 허용 오차(초). 기본: 600(±10분) |
| `--output-dir` |  |  | 출력 폴더 경로 (기본값: TIFF 폴더와 동일) |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `Download_BlueBON.py` | `BASE_SUB_PATH` | `LEOP/` |
|  | `TIME_WINDOW` | `600` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `pipeline_gui.py`
