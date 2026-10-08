# common/viz

결과 맵 생성.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `build_result_html.py` | Result 폴더 산출물을 하나의 인터랙티브 HTML(result.html)로. Leaflet+ESRI basemap, | GeoTIFF · JSON | 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../environment/)
