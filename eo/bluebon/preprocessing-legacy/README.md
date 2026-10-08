# eo/bluebon/preprocessing-legacy

로컬 PC 에 있던 구 전처리 스크립트 — 위 `l0-to-l1a/` 로 대체됐지만 배치 쉘 흐름 참고용으로 남겨 둠.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_rgb_png.py` | 방사보정 TIFF를 이용해 contrast/gamma 조절된 RGB PNG를 생성하는 코드 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `merge_bands.py` | 단일밴드 TIFF 파일을 하나의 멀티밴드 TIFF로 합치는 스크립트 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `read_thuillier.py` | [구판] Thuillier 스펙트럼 로드 | — | — |
| `run.sh` | [구판] 전처리 배치 진입점 | — | — |
| `run_band.sh` | [구판] 단일 밴드 전처리 | — | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../environment/)

### 진입점

```bash
python merge_bands.py 
```
단일밴드 TIFF 파일을 하나의 멀티밴드 TIFF로 합치는 스크립트 8밴드 구성 (MS0~MS7 모두 있는 경우): 0: PAN (MS0) 1: Blue (MS1) 2: Green (MS2) 3: Red (MS3) 4: RedEdge1 (MS4) 5: RedEdge2 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `input_dir` |  |  | TIFF 파일이 있는 디렉토리 (경로에 yymmdd_HHMMSS 패턴 포함 필요) |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `make_rgb_png.py`
