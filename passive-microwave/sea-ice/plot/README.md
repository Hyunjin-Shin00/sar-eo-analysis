# passive-microwave/sea-ice/plot

월별 지도·표류 벡터장.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `drift_quiver.py` | OSI-SAF OSI-405-d Sea Ice Drift | GeoTIFF | PNG 그림 |
| `monthly_map.py` | 북극항로 월별 지도 생성 (2012–현재) | GeoTIFF · 파일 묶음 | PNG 그림 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `drift_quiver.py` | `NSR_LON_MIN` | `20.0` |
|  | `NSR_LAT_MIN` | `68.0` |
