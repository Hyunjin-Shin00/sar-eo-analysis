# passive-microwave/sea-ice/convert

NetCDF → GeoTIFF (극지 투영 처리).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `nsidc_thickness_nc2tif.py` | NSIDC ICESat-2 L4 Monthly Gridded Sea Ice Thickness (IS2SITMOGR4) | GeoTIFF · NetCDF | GeoTIFF · 텍스트/로그 |
| `osisaf_drift_nc2tif.py` | OSI-SAF OSI-405-d Sea Ice Drift | GeoTIFF · NetCDF | GeoTIFF · 텍스트/로그 |
| `osisaf_nc2tif.py` | OSI-SAF OSI-401-d Sea Ice Concentration | GeoTIFF · NetCDF | GeoTIFF · 텍스트/로그 |
| `smos_thickness_nc2tif.py` | SMOS L3C Sea Ice Thickness (v3.6) | GeoTIFF · NetCDF | GeoTIFF · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate netCDF4      # NetCDF 계열
```

- 환경 정의: [`environment/`](../../../environment/)

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `nsidc_thickness_nc2tif.py` | `SRC_PROJ4` | `+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +k=1 +x_0=0 +y_0=0 +a=6…` |
| `smos_thickness_nc2tif.py` | `SRC_PROJ4` | `+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +k=1 +x_0=0 +y_0=0 +dat…` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `osisaf_drift_nc2tif.py`, `osisaf_nc2tif.py`
