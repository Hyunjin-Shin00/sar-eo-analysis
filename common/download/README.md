# common/download

영상 자동 수집 (Sentinel-1/2, Landsat).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `asf_sentinel1.ipynb` | pip install asf_search shapely requests tqdm | CSV · ZIP | 텍스트/로그 |
| `cdse_search.py` | Query the Copernicus Data Space Ecosystem (CDSE) OData catalogue for REAL | CSV · JSON | — |
| `landsat89_m2m.py` | refer to https://m2m.cr.usgs.gov/api/docs/json/ from https://code.usgs.gov/eros-user-services/machine_to_machi | — | 텍스트/로그 |
| `sentinel2_msi.py` | Sentinel-2 L1C/L2A 자동 검색·다운로드 (AOI·기간·구름량 조건) | ZIP | 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../environment/)

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `cdse_search.py`
