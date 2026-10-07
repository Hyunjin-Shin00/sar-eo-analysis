# eo/bluebon/downstream/dehazing/DehazingGUI/pipeline

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `__init__.py` | 연무제거 파이프라인 패키지 초기화 | — | — |
| `basis_catalog.py` | Built-in basis 레지스트리. | — | — |
| `basis_extractor.py` | 폴리라인 정점 → 픽셀 좌표 → basis vectors 추출. | — | — |
| `basis_store.py` | 사용자가 폴리라인으로 저장한 basis를 JSON으로 관리. | JSON | — |
| `cancel.py` | 파이프라인 취소 신호. | — | — |
| `io_helpers.py` | 파일 타입 감지, 출력 경로 계산. | JPG · NC · PNG | — |
| `loader.py` | 영상 로드 + GUI 미리보기 생성. | 이미지 | 텍스트/로그 |
| `mem_utils.py` | 실행 시점의 가용 RAM을 측정하고 안전한 타일 크기를 산정. | — | — |
| `runner.py` | TELEPIX Dehazing 메인 파이프라인. | 이미지 | — |
| `sensor_config.py` | 센서별 basis / band 매핑. | — | — |

## 주요 인자

- `runner.py` — `--fin` `--output-dir` `--sensor`
