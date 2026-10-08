# sar/sentinel-1/change-detection/amplitude

**ACD** — 진폭 로그비로 변화를 봄. 코히런스가 아예 없을 때의 대안.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `change_detect.py` | 지바 최종 침수 영역 — 변화 기반 판정으로 재생산함. | GeoTIFF · NumPy | GeoTIFF · CSV · 텍스트/로그 |
| `measure_change.py` | 지바 케이스의 모든 면적·거리를 원격자(10 m)에서 잰다 — 보고 수치의 단일 출처. | GeoTIFF · NumPy | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `WORK_ROOT` | 작업 디렉터리 루트 |

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `change_detect.py` | `D_MIN` | `3.0` |
|  | `MIN_PX` | `50` |
| `measure_change.py` | `MIN_PX` | `50` |
