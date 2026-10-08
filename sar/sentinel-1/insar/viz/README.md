# sar/sentinel-1/insar/viz

변위 결과 시각화.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_clickmap.py` | 일반화 PS/SBAS 클릭맵. OSM/Esri, 빨강=침하 파랑=융기, 클릭→시계열, 기준영역 마커, POI(선택). | shp/GeoJSON · JSON | 텍스트/로그 |

## 주요 인자

- `make_clickmap.py` — `--no_poi` `--out` `--poi` `--poi_label` `--ref` `--shp` `--title`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

### 진입점

```bash
python make_clickmap.py --shp <값> --out <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--shp` | ● |  |  |
| `--ref` |  |  |  |
| `--poi` |  |  |  |
| `--poi_label` |  | `싱크홀 발생지점` |  |
| `--no_poi` |  |  |  |
| `--out` | ● |  |  |
| `--title` |  | `PS-InSAR (LOS 변위)` |  |
