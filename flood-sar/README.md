# flood-sar — Sentinel-1 자동 침수 탐지

SAR 후방산란에서 수체를 자동 분리해 침수역을 지도화한다.
잔잔한 수면은 정반사체라 후방산란이 낮다 — 그게 탐지의 물리적 근거다.

## 핵심 아이디어

영상 전체 히스토그램에 Otsu를 걸면, 침수 면적이 작을 때 임계값이 육지 쪽으로 끌려간다.
**Edge-Otsu**는 물/육지 경계 후보 버퍼에서만 화소를 뽑아 Otsu를 적용해 이 편향을 피한다.
덕분에 지역마다 임계값을 손으로 맞출 필요가 없다.

## 파일

| 파일 | 역할 |
|---|---|
| `s1_processor.py` | **메인 파이프라인.** SAFE zip 입력 → 전처리 → 수체/침수 탐지 → 통계 |
| `s1_processor_benchmark.py` | 벤치마크용 변형. 전처리된 GeoTIFF 입력 (Sen1Flood11 / KuroSiwo 평가) |
| `s1_download_preprocess.py` | ASF 검색·다운로드 + SNAP 전처리 자동화 (날짜 범위 지정) |
| `s1_grd_preprocessing.py` | GRD 전처리 단독 실행 |
| `s1_waterbody.py` | 수체 마스크만 산출하는 경량 버전 |
| `notebooks/otsu_thresholding.ipynb` | Bmax / Edge / Fuzzy 임계값 전략 비교 |
| `notebooks/flood_auto.ipynb` | 탐지 결과 검토·시각화 |

## 처리 흐름

```
S1 GRD (SAFE zip)
  → 궤도 보정 · 열잡음 제거 · 방사보정(σ⁰) · 스페클 필터 · 지형보정
  → dB 변환
  → Edge-Otsu 임계값 산출 → 수체 마스크
  → DEM slope 필터 (경사지 레이더 음영 제거)
  → JRC 영구수체 마스크 차분 → 신규 침수역
  → DEM 결합 침수심 추정 → 등급 분류
```

## 실행

```bash
export EARTHDATA_USER=... EARTHDATA_PASS=...

python s1_processor.py preprocess \
  --input_zips "<DATA_ROOT>/sentinel1/S1A_*.SAFE.zip" \
  --output_dir "<DATA_ROOT>/out" \
  --dem_path   "<DATA_ROOT>/dem/dem_WGS84.tif" \
  --slope_path "<DATA_ROOT>/dem/slope_WGS84.tif" \
  --polarization VV \
  --initial_db_threshold -20 \
  --slope_threshold 5 \
  --edge_buffer 5 \
  --flood_detection yes --flood_stats yes
```

`--initial_db_threshold` 는 VV 기준 −20, VH 기준 −30 부근에서 시작한다.
Edge-Otsu가 최종 임계값을 정하므로 이 값은 탐색 시작점일 뿐이다.

## 검증 지역

진주 · 예산(국내), 브라질, 태국, 부탄, 필리핀(루손·아파리·파나이), 인도네시아 발리, 멕시코, 인도.

## 알려진 한계

도시 침수에서는 건물–수면 **이중산란(double-bounce)** 때문에 후방산란이 오히려 높아져
침수역이 과소 탐지된다. 이 문제는 해결하지 못했다. 도시 지역에 적용할 때는
광학 영상이나 건물 레이어와 교차 확인이 필요하다.
