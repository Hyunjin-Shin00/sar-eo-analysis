# eo/bluebon/geometric/Code/03.geometric_correction

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`geometric_correction/`](geometric_correction/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `Weight_.py` | ============================================================================== | JSON · TIF · TIFF | — |
| `build_executable.py` | GUI 앱을 독립 실행 파일로 빌드하는 스크립트 | — | — |
| `calculate_coordinates.py` | 정합점에서 지상좌표 계산 | CSV · GEOJSON · JSON | 텍스트/로그 |
| `cleanup_project.sh` | 프로젝트 정리 스크립트 macOS 리소스 포크 파일, Python 캐시, 오래된 로그 파일 삭제 | — | — |
| `config_example.py` | 설정 예시 — 복사해서 쓰는 템플릿 | TIF | — |
| `geometric_correction.py` | ============================================================================== | GeoTIFF · CSV | PNG 그림 · 텍스트/로그 |
| `install_lightglue.sh` | lightglue 설치 스크립트 | — | — |
| `quick_test.py` | 소규모 입력으로 파이프라인 동작 확인 | TXT | 텍스트/로그 |
| `run_all_sets.sh` | 전체 세트 일괄 실행 | — | — |
| `run_batch.py` | 여러 장면 일괄 기하보정 | JSON · TXT | — |
| `setup_geo_romav2.sh` | geo_romav2 Conda 환경 생성 스크립트 목적: geo_correctionv2 환경과 충돌 없이 RoMaV2를 포함하는 독립 환경 생성 사용법: bash setup_geo_romav2.sh | — | — |
| `setup_geo_romav2_linux.sh` | geo_romav2 Conda 환경 생성 스크립트 (Linux CUDA 버전) 목적: 리눅스 환경에서 NVIDIA GPU(CUDA)를 사용하여 RoMaV2를 구동하도록 독립 환경 생성 | — | — |
| `setup_venv.py` | 가상환경 설정 스크립트 (플랫폼 독립적) | TXT | — |
| `setup_venv.sh` | 가상환경 설정 스크립트 (Linux/macOS) | — | — |
| `verify_env.py` | 필요 패키지·버전 확인 | — | — |

## 주요 인자

- `Weight_.py` — `--set` `--weight`
- `geometric_correction.py` — `--bands` `--dem` `--gcp_chip_res` `--gcp_chips` `--geoid` `--lat` `--lon` `--output` `--output_name` `--ref` `--res` `--target`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate bldseg      # PyTorch · transformers
```

- 환경 정의: [`environment/`](../../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `PROJ_DATA` | PROJ 자료 경로 |

### 진입점

```bash
python Weight_.py 
```
============================================================================== RPC 생성 및 정사보정 파이프라인 (JSON GCP 기반) =====================================

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--weight` |  |  | GCP 가중치 (Real GCP 복제 횟수, 기본값: Setting_Weight 자동 계산) |
| `--set` |  | `t1` | EXPERIMENT_SETS 키 이름 (기본값: t1) |

```bash
python geometric_correction.py 
```
============================================================================== 2단계 정밀 기하보정 파이프라인 (Two-Stage Precision Geometric Correction Pipeline) =

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--dem` |  |  | DEM 파일 경로 |
| `--geoid` |  |  | Geoid 파일 경로 |
| `--ref` |  |  | Reference(Sentinel) 영상 경로 |
| `--target` |  |  | Target(BlueBON) 영상 경로 |
| `--output` |  |  | 출력 디렉토리 경로 |
| `--lat` |  |  | Target 중심 위도 |
| `--lon` |  |  | Target 중심 경도 |
| `--res` |  |  | Target 해상도 (m) |
| `--bands` |  |  | Target 밴드 인덱스 (R G B 순서, 1-based). 예: PlanetScope -> 6 4 2 |
| `--gcp_chips` |  |  | GCP Chips 디렉토리 경로 (재사용 시) |
| `--gcp_chip_res` |  |  | GCP chip 해상도 (m/px, 기본값: 1.2) |
| `--output_name` |  |  | 출력 파일 기본 이름 (확장자 제외, 예: bb_l1b_20260116_021517_8band) |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `build_executable.py`, `quick_test.py`, `run_batch.py`, `setup_venv.py`
