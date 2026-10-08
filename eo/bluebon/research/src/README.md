# eo/bluebon/research/src

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `bblike_fr_msi.py` | Created on Mon Jul  7 09:27:31 2025 | 파일 묶음 | — |
| `bluebon_calibration.py` | Created on Thu Jun  5 09:35:35 2025 | GeoTIFF · NumPy | NumPy |
| `bluebon_rayleigh.py` | Created on Sun Jul 13 21:07:32 2025 | — | — |
| `calib.py` | Created on Mon Jul  7 21:23:23 2025 | GeoTIFF · CSV | — |
| `calibration_curve.py` | Created on Mon Jul  7 15:05:36 2025 | CSV | CSV |
| `coreg_FourierMelin.py` | Created on Wed Dec 24 13:38:48 2025 | — | — |
| `coreg_FourierMelin_multitile.py` | Created on Wed Dec 24 17:41:55 2025 | — | — |
| `coreg_FourierMelin_multitile_2d.py` | Created on Wed Dec 24 17:41:55 2025 | — | — |
| `coreg_FourierMelin_twotile.py` | Created on Wed Dec 24 16:23:33 2025 | — | — |
| `coreg_FourierMelin_twotile1.py` | Created on Wed Dec 24 16:23:33 2025 | — | — |
| `coreg_tools.py` | Initial try, Obsolete | — | — |
| `dark_DN_cross-track_graph.py` | Created on Thu Sep  4 15:13:08 2025 | — | — |
| `inpolygon_analysis.py` | Created on Fri Jul  4 16:57:11 2025 | GeoTIFF · 이미지 | — |
| `line_correction.py` | from scipy.ndimage import median_filter | NC | — |
| `nc_to_warpedtiff.py` | NetCDF → 투영 보정 GeoTIFF 변환 | NC · TIF | — |
| `png_to_warpedtiff.py` | Created on Wed Jul  2 18:09:11 2025 | GeoTIFF | — |
| `rayleigh_bluebon.py` | by YP 2025.07.13 copied: rayleigh_viirs.py | — | — |
| `rsr_f0_bluebon.py` | 밴드별 분광응답(RSR) 가중 태양상수 F0 계산 | CSV | — |
| `solarpos.py` | Created on Tue Jul  8 15:55:17 2025 | — | — |
| `test_linecorr.py` | Created on Sat Aug 23 22:54:23 2025 | NC | — |
| `test_unwarped_gcps.py` | Created on Thu Jul 10 15:08:45 2025 | GeoTIFF | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `bluebon_calibration.py`, `bluebon_rayleigh.py`, `calib.py`, `line_correction.py`
