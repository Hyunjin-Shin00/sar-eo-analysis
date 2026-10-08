# sar/sentinel-1/soil-moisture/uk_maslanka2022

Maslanka 2022 (TU Wien 변화탐지) — 영국 COSMOS-UK 재현.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `01_fetch_s1.py` | Planetary Computer sentinel-1-rtc (γ0 RTC, 10 m) 에서 COSMOS-UK 3개 지점 주변 2.2 km 창만 읽어 스택 저장. | GeoTIFF | — |
| `02_incidence.py` | 궤도별 지점 입사각: sentinel-1-grd annotation(schema-product-vv) geolocationGrid 보간. | JSON | JSON |
| `03_rssm_validate.py` | Maslanka et al. (2022) TU Wien 변화탐지 재현 (Ann-Dir β) + COSMOS-UK 검증, Table IV 비교. | GeoTIFF · CSV · NumPy · JSON · 파일 묶음 | CSV · PNG 그림 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)
