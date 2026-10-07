# flood-sar — Sentinel-1 GRD 홍수(수체 변화) 탐지

Sentinel-1 GRD 사전·사후 영상 2장에서 수체 마스크를 각각 만들고, 그 차이로 새로 잠긴 곳(GAIN)과 물이 빠진 곳(LOSS)을 산출한다. 학습 데이터 없이 동작하는 비지도 방식(Edge-Otsu).

## 파일
| 파일 | 용도 |
|---|---|
| `s1_flood_snap.py` | SNAP(esa_snappy) 전처리 체인 포함판. `.SAFE.zip` → 궤도·열잡음·경계잡음 제거 → σ⁰ 보정 → Lee-sigma → 지형보정(10 m) → dB → Edge-Otsu → GAIN/LOSS. `--batch_root` 로 KuroSiwo 타일 폴더 일괄 처리 가능 |
| `s1_flood_nosnap.py` | SNAP 없이 이미 전처리된 dB GeoTIFF 를 입력으로 받는 판(텔레픽스 SatCHAT 홍수 모듈용). Copernicus DEM 30 m 자동 다운로드 → 경사도 계산 → 경사 ≥ 5° 화소를 물에서 제외, 두 영상 공통 영역 정렬, 면적 통계 txt 출력 |
| `eval_kurosiwo.py` | KuroSiwo(공개 벤치마크) 타일 라벨(MLU: 0 비수체·1 영구수체·2 홍수·3 무효)과 수체 마스크를 비교해 P/R/F1/IoU 산출 |

## 알고리즘 (Edge-Otsu)
1. 초기 임계 −20 dB 로 거친 물 후보를 만든다.
2. 후보의 모폴로지 경계(팽창−침식)를 구하고 5화소 버퍼를 준다.
3. 버퍼 안 화소만으로 Otsu 임계를 구한다 → 물/육지가 반반 섞인 표본이라 히스토그램이 이봉형이 된다.
4. 그 임계로 전체 영상을 이진화(`s1_flood_nosnap.py` 는 경사 ≥ 5° 를 육지로 강제).
5. 사후 & ~사전 = GAIN(1), 사전 & ~사후 = LOSS(2). 격자가 다르면 최근린 재투영.

## 사용 예
```bash
# SNAP 체인 (ZIP 입력)
python s1_flood_snap.py --inputs pre.SAFE.zip post.SAFE.zip --output_dir <WORK_ROOT>/run \
  --polarization VV --aoi_shp <DATA_ROOT>/AOI.shp --flood_detection yes --flood_stats yes
# 전처리된 dB GeoTIFF 입력 (DEM/경사 자동)
python s1_flood_nosnap.py water --input_tifs pre_dB.tif post_dB.tif --output_dir <WORK_ROOT>/run \
  --initial_db_threshold -20 --slope_threshold 5 --edge_buffer 5 --flood_detection yes --flood_stats yes
# KuroSiwo 평가
DATA_ROOT=<DATA_ROOT> python eval_kurosiwo.py
```

## 주의
- `s1_flood_snap.py` 의 `run()` 은 before/after 를 **파일 수정시각** 으로 정렬한다. 파일명 날짜가 아니다 — 재처리 순서에 따라 GAIN/LOSS 가 뒤집힐 수 있다(`s1_flood_nosnap.py` 는 파일명 YYYYMMDD 사용).
- `s1_flood_snap.py` 출력이 EPSG:3857 이면 화소 10 m 는 실제 지상 크기가 아니다(위도 35.5° 에서 실제 면적 = 66 m²/화소). 면적은 반드시 등적 투영 또는 위도 보정으로 계산.
- 배치 모드의 `_pick_file` 은 `*VV*` 만 찾는다. VH 평가 때는 패턴 수정 필요.
- `s1_flood_nosnap.py` 의 AOI 분기에서는 nodata(0, −9999) 를 NaN 으로 바꾸는 처리가 빠져 있다(AOI 없는 분기에만 있음).
- 도시 침수: 건물-수면 이중산란으로 후방산란이 오히려 커지므로 이 방법(어두움=물)으로는 원리상 잡히지 않는다.
