# sar/sentinel-1/water/soil-moisture/viz

지도 합성·위치 정합 확인용 그림 생성.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `georef_check.py` | 분석 격자 ↔ 실제 지도 위치 정합 검사. | GeoTIFF · NumPy · JSON | JSON · NumPy |
| `make_figs_en.py` | 영문 발표용 그림 (TelePIX 템플릿 색상) | CSV · JSON | PNG 그림 |
| `make_satchat.py` | SatCHAT 화면 합성: Esri World Imagery 위성지도(실제 분석 지역) + 토양수분 분석결과 레이어 + 좌측 채팅(질문·답변). | CSV · NumPy · JSON · 이미지 | JSON · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `make_satchat.py`
