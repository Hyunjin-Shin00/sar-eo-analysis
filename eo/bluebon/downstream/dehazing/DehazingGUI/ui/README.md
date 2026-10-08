# eo/bluebon/downstream/dehazing/DehazingGUI/ui

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `__init__.py` | GUI 패키지 초기화 | — | — |
| `compare_window.py` | 전후 비교 슬라이드 창. | — | — |
| `control_panel.py` | 우측 컨트롤 패널: 메타데이터 + 입출력 + Basis 그리기 + 로그. | — | — |
| `image_viewer.py` | QGraphicsView 기반 영상 뷰어. 줌/패닝 + 폴리라인 드로잉 + 결과 토글. | — | — |
| `main_window.py` | MainWindow: 좌측 ImageViewer + 우측 ControlPanel + 하단 상태바. | — | 텍스트/로그 |
| `polyline_overlay.py` | QGraphicsScene에 추가되는 폴리라인 시각화/편집 그룹. | — | — |
| `worker.py` | Dehazing 처리용 QThread 워커 (배치 큐 지원). | — | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함
