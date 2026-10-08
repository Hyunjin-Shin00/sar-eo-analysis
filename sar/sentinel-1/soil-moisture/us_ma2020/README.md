# sar/sentinel-1/soil-moisture/us_ma2020

Ma 2020 (Oh + WCM) — 미국 SCAN 재현. **재현 실패 기록 포함.**

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `ma2020_scan.py` | Ma, Li & McCabe (2020) Remote Sens. 12:2303 재현 — SCAN 2001 Rogers Farm #1 (Nebraska), Fig. 9 | GeoTIFF · CSV | CSV · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)
