# sar/umbra/sigma0

복소 진폭 → σ⁰ 변환.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `calc.py` | 복소 진폭 → σ⁰(후방산란계수) 변환 계산 | — | — |
| `file_io.py` | DESCRIPTION: > @brief > > @param[in] N/A > @param[out] N/A > @return N/A | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |
| `main.py` | Umbra σ⁰ 산출 실행 진입점 | JSON · TIF | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `main.py`
