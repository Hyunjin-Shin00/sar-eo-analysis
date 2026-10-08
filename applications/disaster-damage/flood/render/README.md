# applications/disaster-damage/flood/render

지도·카드뉴스 렌더링.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `build_card.py` | 2026 네팔 홍수 SAR 분석 카드뉴스 조립 (가로형). | JSON · 이미지 | — |
| `render_chips.py` | 카드뉴스용 SAR 전/후 영상 칩 + 변화 칩 렌더링. | GeoTIFF | JSON |
| `render_extras.py` | 카드뉴스 보조 그래픽: 구간별 막대차트 + 네팔 위치도. usage: render_extras.py <TRACK> | JSON · 이미지 | PNG 그림 |
| `render_mainmap.py` | 카드뉴스 주 지도: ESRI World Imagery 위성 배경 + 회랑 + 탐지구역 + 지명. | GeoTIFF · JSON · 이미지 | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

- 표준 과학 스택(numpy · pandas · matplotlib)이면 충분함

### 환경변수

| 이름 | 설명 |
|---|---|
| `DATA_ROOT` | 원본·중간 산출물이 놓인 데이터 루트 |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `build_card.py`, `render_chips.py`, `render_extras.py`, `render_mainmap.py`
