# 08_unified_map

PS · SBAS · 시추공 결과를 한 장에 올리는 **통합 지도 생성기**임.

| 코드 | 입력 | 출력 |
|---|---|---|
| `make_unified_map.py` | 지역별 PS 점군, SBAS 시계열, 시추공 지반등급 | 지역별 지도 7개 + 허브 1개 (Leaflet 1.9.4 단일 HTML) |

- 3레이어 독립 체크박스(PS / SBAS / 시추공), 등급 팝업, 임계치표 접기, 허브 사이드바
- 점은 circleMarker + RdBu 컬러맵, 클릭 시 시계열 SVG 를 팝업에 인라인으로 그림
- 출력 경로는 환경변수 기반(`<DATA_ROOT>`)으로 일반화돼 있음

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
| `CLAB_ROOT` | 지반침하 과제 트리 루트 |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `make_unified_map.py` | `REGION_TEMPLATE` | `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>__TITLE__…` |
