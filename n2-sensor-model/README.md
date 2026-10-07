# n2-sensor-model — 국산 X-band SAR 엄밀센서모델 기하보정

상용·공개 SAR 소프트웨어가 지원하지 않는 국산 위성을, 파일 안의 궤도·타이밍 정보만으로
거리-도플러 엄밀센서모델을 세워 지오코딩한다.

> 이 문서는 요약이다. 상세 설명은 [`CODE_REFERENCE.md`](CODE_REFERENCE.md)(파일별 코드 해설)과
> [`RD_MODEL_DETAIL.md`](RD_MODEL_DETAIL.md)(모델 수식 유도)에 있다.

## 왜 직접 만들었나

ISCE2 · SNAP · GAMMA 어느 것도 이 위성을 네이티브 지원하지 않는다.
SAR 픽셀은 광학의 공선조건이 아니라 **(시각, 거리)** 두 측정값으로 정의되므로,
궤도 상태벡터와 Zero-Doppler 타이밍부터 직접 구현해야 한다.

```
① 거리    |P − S(t)| = R
② 도플러  (P − S(t)) · V(t) = 0        제로도플러: 시선 ⊥ 속도
```

## 라이브러리 (`lib/`)

| 파일 | 역할 |
|---|---|
| `n2reader.py` | HDF5 헤더를 SI 단위로 정리, SLC 읽기 (SSC·3D SBI 레이아웃) |
| `orbit.py` | 상태벡터 60점 → 다항식 S(t), V(t), A(t) |
| `geometry.py` | 거리-도플러 방정식, `geo2rdr` / `rdr2geo`, 룩사이드, 편향 슬롯 |
| `tropo.py` | 표준대기 대류권 슬랜트 지연 |
| `dem.py` | Copernicus DEM 읽기, EGM2008 지오이드, 면요소 법선·면적 |
| `simulate.py` | DEM → SAR 시뮬레이션, 멀티룩, 마스크 상관 정합 |

## 실행 순서 (번호 = 처리 순서)

```
step01_grid_orbit     격자·궤도·왕복시간·풋프린트 검증
step02_geometry       기하 모델 검증
step03_bias_dem       DEM 시뮬 ↔ 실영상 정합으로 센서 편향 추정
step04_geocode        지도격자 → 영상 샘플링 (지오코딩)
step05_clip_rect      관심영역 클립
step06_s1_reference   Sentinel-1 교차검증
step07_lsq            최소제곱 편향 추정
step08_all_scenes     12씬 결합조정
step09_stack          스택 구성
step10_fine_coreg     미세정합
step11_water_detect   수체 탐지
step12_compare_3col   N2 | S1 | S2 3열 비교
step13_water_panel    수체 증거 패널
```

```bash
conda activate isce2_snaphu   # numpy 1.26, scipy, h5py, pyproj 3.7, rasterio, GDAL, matplotlib
python step01_grid_orbit.py
# ... 번호 순서대로
```

## 알아둘 함정

- **지오이드 기준.** Copernicus DEM은 정표고(EGM2008)인데 지오코딩은 타원체고를 기대한다.
  보정하지 않으면 range 방향으로 약 **24.5 m** 편이가 생긴다. 이 잔차를 지오이드 융기량으로
  정확히 설명할 수 있다는 점이 기하 모델이 정합적이라는 방증이다.
- **원본은 읽기 전용.** `.h5` 원본은 수정·반출 금지. 쓰기가 필요하면 반드시 사본에 적용한다.
- **작업폴더는 ext4.** WSL의 `/mnt/c`(DrvFs)에서 정합 refine을 돌리면 쓰기가 EPERM으로
  조용히 skip되어 위상이 손상된다. ext4에서 실행하고 산출물만 복사할 것.

## 결과

12씬 전량을 UTM 52N **5 m 격자**로 지오코딩. 결합조정 후 씬 쌍 잔여 시프트는 대부분 1 화소 이내.
