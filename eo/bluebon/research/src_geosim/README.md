# eo/bluebon/research/src_geosim

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `bbcoords_tool.py` | Created on Sat Aug 30 17:00:34 2025 | GEOJSON | — |
| `compute_coef_rad2DN_coefs.py` | Created on Tue Sep  2 09:20:50 2025 | NumPy | — |
| `myaffine.py` | Created on Sat Aug 30 17:31:49 2025 | — | — |
| `setting_250626_Chesapeake.py` | Created on Sun Sep  7 18:22:40 2025 @author: yp | — | — |
| `setting_2507xx_Jamsil1.py` | Created on Sun Sep  7 18:22:40 2025 @author: yp | — | — |
| `setting_250806_SoffSydney.py` | Created on Sun Sep  7 18:22:40 2025 @author: yp | NC · TIF | — |
| `setting_250821_Busan.py` | Created on Sun Sep  7 18:22:40 2025 @author: yp | — | — |
| `setting_250903_Namhae.py` | Created on Sun Sep  7 18:22:40 2025 @author: yp | NC · TIF | — |
| `simulation_lonlat.py` | Created on Thu Aug 28 18:17:53 2025 | GEOJSON | shp/GeoJSON |
| `simulation_lonlat_old.py` | Created on Thu Aug 28 18:17:53 2025 | GEOJSON | shp/GeoJSON |
| `update_slope_DN2rhot.py` | Created on Mon Sep  8 16:01:30 2025 | NumPy | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `bbcoords_tool.py`, `compute_coef_rad2DN_coefs.py`, `myaffine.py`, `simulation_lonlat.py`, `simulation_lonlat_old.py`, `update_slope_DN2rhot.py`
