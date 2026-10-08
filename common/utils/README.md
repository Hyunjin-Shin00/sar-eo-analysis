# common/utils

공통 유틸.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `analyze_shp.py` | Taean.shp 폴리곤 내부에서 N2/S1 각 변화 산출물이 값을 낼 수 있는지 분석. | GeoTIFF | PNG 그림 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../environment/)
