# applications/disaster-damage/earthquake/aux

단층 등 보조 레이어 추출.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `extract_venezuela_faults.py` | geopandas 없으면 설치 | shp/GeoJSON | shp/GeoJSON · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)
