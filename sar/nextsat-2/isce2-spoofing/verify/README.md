# sar/nextsat-2/isce2-spoofing/verify

주입한 메타데이터를 독립 기하로 재계산해 검증함.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_figs.py` | Generate bundle figures (PNG in tmp; converted to webp afterwards). Read-only on sources. | GeoTIFF · HDF5 · 파일 묶음 · 이미지 | PNG 그림 |
| `recompute_geometry.py` | Recompute N2 / CSK geometry from HDF5 attributes only (read-only). | HDF5 | — |
| `recompute_raster.py` | Recompute coherence / phase / unwrapped-displacement statistics from ISCE2 binary outputs (read-only). | XML | — |
| `topo_check.py` | Is the CSK unwrapped phase dominated by uncompensated topography? | GeoTIFF | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `CSK_EXT_DEM` | 코드 참조 |
| `CSK_RUN` | 코드 참조 |
| `N2_H5` | 코드 참조 |
| `NDVI_ROOT` | 코드 참조 |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `make_figs.py`, `recompute_geometry.py`, `recompute_raster.py`
