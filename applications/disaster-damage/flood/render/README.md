# applications/disaster-damage/flood/render

지도·카드뉴스 렌더링.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `build_card.py` | 2026 네팔 홍수 SAR 분석 카드뉴스 조립 (가로형). | JSON · 이미지 | — |
| `render_chips.py` | 카드뉴스용 SAR 전/후 영상 칩 + 변화 칩 렌더링. | GeoTIFF | JSON |
| `render_extras.py` | 카드뉴스 보조 그래픽: 구간별 막대차트 + 네팔 위치도. usage: render_extras.py <TRACK> | JSON · 이미지 | PNG 그림 |
| `render_mainmap.py` | 카드뉴스 주 지도: ESRI World Imagery 위성 배경 + 회랑 + 탐지구역 + 지명. | GeoTIFF · JSON · 이미지 | — |
