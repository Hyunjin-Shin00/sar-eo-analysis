# sar/nextsat-2/isce2-spoofing/verify

주입한 메타데이터를 독립 기하로 재계산해 검증한다.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_figs.py` | Generate bundle figures (PNG in tmp; converted to webp afterwards). Read-only on sources. | GeoTIFF · HDF5 · 파일 묶음 · 이미지 | PNG 그림 |
| `recompute_geometry.py` | Recompute N2 / CSK geometry from HDF5 attributes only (read-only). | HDF5 | — |
| `recompute_raster.py` | Recompute coherence / phase / unwrapped-displacement statistics from ISCE2 binary outputs (read-only). | XML | — |
| `topo_check.py` | Is the CSK unwrapped phase dominated by uncompensated topography? | GeoTIFF | — |
