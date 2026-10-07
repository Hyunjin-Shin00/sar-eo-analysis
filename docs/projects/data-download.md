# data-download — 위성영상 자동 수집

## 파일

| 파일 | 대상 | API |
|---|---|---|
| `sentinel2_msi.py` | Sentinel-2 L1C/L2A | Copernicus Data Space Ecosystem |
| `landsat89_m2m.py` | Landsat 8/9 | USGS M2M API |
| `notebooks/asf_sentinel1.ipynb` | Sentinel-1 GRD/SLC | ASF (NASA Earthdata) |

## 자격증명

```bash
export CDSE_USER=... CDSE_PASS=...
export USGS_USER=... USGS_TOKEN=...
export EARTHDATA_USER=... EARTHDATA_PASS=...
```

계정 발급:
- [Copernicus Data Space](https://dataspace.copernicus.eu/)
- [USGS EROS](https://ers.cr.usgs.gov/) — M2M 접근은 별도 신청 필요
- [NASA Earthdata](https://urs.earthdata.nasa.gov/)

## 공통 인자

대부분 AOI(bbox 또는 shapefile), 날짜 범위, 구름량 상한을 받음.
Sentinel-1 다운로드는 `flood-sar/s1_download_preprocess.py` 가 검색·수집·전처리를 한 번에 처리함.
