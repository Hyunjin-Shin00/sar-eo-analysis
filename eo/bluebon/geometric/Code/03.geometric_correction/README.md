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
