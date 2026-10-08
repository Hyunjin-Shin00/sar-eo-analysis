# sar/sentinel-1/water/soil-moisture/verify

원본 산출물에서 핵심 수치를 다시 계산해 문서와 대조함.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `fig_us_scan.py` | Portfolio figure: Ma 2020 SCAN reproduction (retrieved vs in-situ), from case_US_Ma2020/outputs/retrievals.csv | CSV | PNG 그림 |
| `r1_uk.py` | Independent recompute of UK (Maslanka 2022 reproduction) numbers from original npz/csv outputs. | CSV · NumPy · JSON · 파일 묶음 | — |
| `r2_uk_chimn250.py` | Independent end-to-end CHIMN 250 m r2 from s1rtc npz + COSMOS csv (+WorldCover mask, remote COG). | GeoTIFF · CSV · NumPy · JSON · 파일 묶음 | — |
| `r3_us_kr.py` | 미국 SCAN·국내 관측소 검증 지표 재계산 | CSV | — |
| `r4_loso.py` | LOSO (leave-one-site-out) check on Cho 2026 Zenodo table: RF on 4 inputs vs constant baseline vs authors' publ | Excel | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)
