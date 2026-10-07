# applications/dam-monitoring

자연댐 변위 모니터링 — 성분 분해와 계절성 분석.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`verify/`](verify/) | 결과 재계산 검증. |

## 결과 예시

이 폴더 코드로 만든 산출물입니다. 데이터는 저장소에 없고 그림만 참고용으로 둡니다.

![자연댐 변위 속도장](figures/00-key.webp)
*자연댐 변위 속도장*

![시간 결맞음](figures/02-temporal-coherence.webp)
*시간 결맞음*

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `diag_era5.py` | Diagnose whether ERA5 tropo correction removed the topo-correlated velocity residual. | HDF5 | — |
| `export_dsc_corrected.py` | DSC LOS velocity with an EMPIRICAL stratified-tropo correction (remove the strong velocity~elevation trend tha | HDF5 · 파일 묶음 | JSON |
| `make_dsc_corr_map.py` | Standalone HTML: Esri imagery + water-masked, AOI-cropped DSC LOS velocity. The RAW velocity field (float32) i | JSON | 텍스트/로그 |
| `plot_decomp.py` | Render ASC/DSC LOS + vertical/horizontal decomposition velocity maps to a PNG. | HDF5 | PNG 그림 |
| `seasonal_point.py` | Extract the seasonal cycle at the requested point: remove the linear trend, then (a) fit annual+semiannual sin | JSON | PNG 그림 |
