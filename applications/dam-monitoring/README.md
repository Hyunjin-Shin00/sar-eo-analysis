# applications/dam-monitoring

자연댐 변위 모니터링 — 성분 분해와 계절성 분석.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    slc[("Sentinel-1 SLC 365씬 — ASC 140 · DSC 225, 약 1.5 TB")]
    dem[("COP30 DEM → 타원체고 변환 · POEORB 정밀궤도")]
    era[("ERA5 (PyAPS) 223 날짜")]
    stack["topsStack — IW2 단일 서브스와스 · geometry 코레지 · 3×9 룩"]
    disk["디스크 관리 — 병합 직후 버스트 간섭도 삭제 (1.23 GB → 42 MB/페어)"]
    unw["snaphu 언랩 — ASC 550 · DSC 433 페어"]
    ref{"기준점 자동선정 교체 — 유지 간섭도 다수에서 연결성분이 살아 있는 최고결맞음 픽셀"}
    mintpy["MintPy SBAS — 네트워크 ≤ 24일 · 결맞음 ≥ 0.3"]
    tropo["ERA5 보정 → 잔차 고도 detrend (반복 이상치 제거 회귀) → 안정암반 재기준"]
    lake["DEM 평탄도로 호수 마스킹"]
    dec["0.0005° 공통격자 geocode → asc_desc2horz_vert"]
    out(["수직 · 동서 변위속도 · 지점 시계열 웹맵"])
    slc --> stack
    dem --> stack
    stack --> disk
    disk --> unw
    unw --> ref
    ref --> mintpy
    era --> tropo
    mintpy --> tropo
    tropo --> lake
    lake --> dec
    dec --> out
    class slc data
    class dem data
    class era data
    class stack proc
    class disk proc
    class unw proc
    class ref dec
    class mintpy proc
    class tropo proc
    class lake proc
    class dec proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`verify/`](verify/) | 결과 재계산 검증. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `diag_era5.py` | Diagnose whether ERA5 tropo correction removed the topo-correlated velocity residual. | HDF5 | — |
| `export_dsc_corrected.py` | DSC LOS velocity with an EMPIRICAL stratified-tropo correction (remove the strong velocity~elevation trend tha | HDF5 · 파일 묶음 | JSON |
| `make_dsc_corr_map.py` | Standalone HTML: Esri imagery + water-masked, AOI-cropped DSC LOS velocity. The RAW velocity field (float32) i | JSON | 텍스트/로그 |
| `plot_decomp.py` | Render ASC/DSC LOS + vertical/horizontal decomposition velocity maps to a PNG. | HDF5 | PNG 그림 |
| `seasonal_point.py` | Extract the seasonal cycle at the requested point: remove the linear trend, then (a) fit annual+semiannual sin | JSON | PNG 그림 |
