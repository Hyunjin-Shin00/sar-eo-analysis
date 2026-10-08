# sar/sentinel-1/insar/sbas/wide-area

광역 처리를 위한 타일 분할·병합. 메모리 한계를 타일링으로 우회함.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_subtiles.py` | 채택률이 낮은 타일을 NxN으로 재분할한 창 목록 생성. 큰 창(427x740)에서는 snaphu 언랩 오류가 누적돼 tcoh가 무너진다(같은 지역이 100x300 창에서 33% 채택, 427x74 | JSON | — |
| `make_tiles.py` | 광역 SBAS 타일 격자 생성 + 타일별 사고 건수 산출 | GeoTIFF | — |
| `merge_capital_tiles.py` | 광역 SBAS 타일 병합 + 타일간 기준 보정. 각 타일은 자기 타일 내 최대결맞음 픽셀을 기준으로 삼고 타일별로 deramp(평면 제거)를 하므로 인접 타일 사이에 상수 단차가 아니라 '평면' 차 | CSV · JSON · 파일 묶음 | CSV · shp/GeoJSON · 텍스트/로그 |
| `run_region_tiles.sh` | 수도권 광역 SBAS 타일 러너 (v3) - 동시 실행 상한을 '실제 run_sbas_tile.py 프로세스 수'로 제어(MAXPROC). 여유 RAM 기준 게이트는 크롭 중 점진 증가분을 못 막아 | JSON | — |
| `run_sbas_tile.py` | 광역 타일 SBAS — run_sbas.py의 수식을 그대로 쓰되 입력을 lat/lon bbox 대신 멀티룩 픽셀창(R0 R1 C0 C1)으로 받음. 회전된 프레임을 bbox로 자르면 창이 과도하 | GeoTIFF · 파일 묶음 | CSV · NumPy · 텍스트/로그 |

## 주요 인자

- `make_subtiles.py` — `--maxrate` `--min-acc` `--out` `--ov` `--root` `--split` `--tiles`
- `make_tiles.py` — `--bbox` `--merged` `--ncol` `--nrow` `--out` `--ov`
- `merge_capital_tiles.py` — `--maxov` `--minov` `--no-subtiles` `--no-ts` `--out` `--plane` `--rad` `--region` `--root`
- `run_sbas_tile.py` — `--azl` `--cmax` `--coh_min` `--keep-cache` `--lam` `--merged` `--out` `--region` `--rgl` `--tcoh_min` `--tmax` `--win`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)

### 진입점

```bash
python make_subtiles.py --out <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--tiles` |  | `<WORK_ROOT>/CLAB_WIDE/capital_asc/tiles.json` |  |
| `--root` |  | `<WORK_ROOT>/CLAB_WIDE/capital_asc` |  |
| `--split` |  | `2` | 각 타일을 split x split 로 분할 |
| `--ov` |  | `40` | 서브타일 간 중첩(px) |
| `--maxrate` |  | `20.0` | 채택률(%%) 이 값 미만인 타일만 대상 |
| `--min-acc` |  | `1` | 사고가 이 수 이상인 타일만 대상 |
| `--out` | ● |  |  |

```bash
python make_tiles.py --out <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--merged` |  | `<DATA_ROOT>/CLAB/regions/seoul/workspace/stamps_seoul/stack/merged` |  |
| `--bbox` |  |  |  |
| `--nrow` |  | `6` |  |
| `--ncol` |  | `5` |  |
| `--ov` |  | `60` |  |
| `--out` | ● |  |  |

```bash
python merge_capital_tiles.py 
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--root` |  | `<WORK_ROOT>/CLAB_WIDE/capital_asc` |  |
| `--out` |  | `<DATA_ROOT>/CLAB/regions/capital_wide/sbas` |  |
| `--region` |  | `capital_wide` |  |
| `--maxov` |  | `20000` | 타일쌍당 사용할 중첩픽셀 상한 |
| `--minov` |  | `100` | 연결로 인정할 최소 대응점 수 |
| `--rad` |  | `300.0` | 타일간 대응점 최대 거리(m) |
| `--no-subtiles` |  |  | 재처리 서브타일을 무시하고 원본 30타일만 병합 |
| `--plane` |  |  | 상수 오프셋 대신 평면(a+bX+cY) 보정. 기본은 오프셋 전용 — 평면은 얇은 연결에서 계수가 폭주한다 |
| `--no-ts` |  |  | 시계열 열 보정 생략(속도만) |

```bash
python run_sbas_tile.py --merged <값> --win <값> --out <값> --region <값>
```

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--merged` | ● |  |  |
| `--win` | ● |  |  |
| `--out` | ● |  |  |
| `--region` | ● |  |  |
| `--rgl` |  | `9` |  |
| `--azl` |  | `3` |  |
| `--cmax` |  | `4` |  |
| `--tmax` |  | `72` |  |
| `--coh_min` |  | `0.3` |  |
| `--tcoh_min` |  | `0.7` |  |
| `--lam` |  | `0.055465763` |  |
| `--keep-cache` |  |  |  |
