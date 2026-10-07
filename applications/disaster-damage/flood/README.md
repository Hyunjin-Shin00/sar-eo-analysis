# applications/disaster-damage/flood

돌발홍수 피해 — 탐지 결과를 노출·경로 분석으로 확장.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`render/`](render/) | 지도·카드뉴스 렌더링. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `corridor_matched2.py` | 고도+기준결맞음 2차원 매칭 검정 — 2026 네팔 홍수 | GeoTIFF · JSON | — |
| `exposure.py` | 노출 분석 (인구 / 건물 / 도로 / 시설) — 2026 네팔 홍수 | GeoTIFF · JSON | JSON |
| `make_map.py` | 결맞음 변화 지도 생성 — 2026 네팔 홍수 | GeoTIFF · JSON | PNG 그림 |
| `nrsc_check.py` | NRSC/ISRO(Charter Call 1209 AOI-02)가 지목한 인프라 피해가 우리 SAR에서 보이는지 검증. | GeoTIFF | PNG 그림 · JSON |
| `source_scar.py` | 빙하 붕괴 원점의 붕괴 흔적(scar) 탐지 — 2026 네팔 홍수 | GeoTIFF | — |
