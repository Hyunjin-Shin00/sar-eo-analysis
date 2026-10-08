# applications/rail-hazard/catalog

대상 구간(고가교·노선) 추출.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `build_hachinohe_target.py` | 八戸線 지진 피해구간 / 대조구간을 확정함. | shp/GeoJSON | shp/GeoJSON |
| `fetch_hachinohe_allrail.py` | coherence 장면 전체(약 26x27 km)의 철도 회랑을 받는다 — 대조군을 제대로 만들기 위해. | GEOJSON | shp/GeoJSON |
| `fetch_hachinohe_viaduct.py` | 八戸線 本八戸~小中野 고가교 지오메트리와 柏崎 지명 위치를 받음. | GEOJSON · JSON | shp/GeoJSON |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `WORK_ROOT` | 작업 디렉터리 루트 |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `build_hachinohe_target.py`, `fetch_hachinohe_allrail.py`, `fetch_hachinohe_viaduct.py`
