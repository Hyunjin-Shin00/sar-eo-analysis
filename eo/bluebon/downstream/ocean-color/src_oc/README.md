# eo/bluebon/downstream/ocean-color/src_oc

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `BB2iop_wrapper.py` | Created on Mon Aug  4 00:30:45 2025 | NC · TIF | — |
| `BB_hab.py` | Created on Tue Sep  9 15:27:07 2025 | SHP · TIF | 텍스트/로그 |
| `BBinvfit.py` | double precision | PNG | PNG 그림 |
| `BBinvfit_constants.py` | Created on Sat Aug  2 18:09:09 2025 | — | — |
| `BBrhorc2iop.py` | 대기보정 반사도 → 고유광학특성(IOP) 역산 | NC · TIF | — |
| `flagging_bb.py` | cloud and land flagging Preliminary | — | — |
| `inpolygon_analysis_hab.py` | Created on Fri Jul  4 16:57:11 2025 | GeoTIFF | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `BB2iop_wrapper.py`, `BBinvfit.py`, `BBinvfit_constants.py`, `BBrhorc2iop.py`
