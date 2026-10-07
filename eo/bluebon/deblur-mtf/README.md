# eo/bluebon/deblur-mtf

**MTF 와 디블러링.** 에지법으로 MTF 를 재고, 추정한 커널로 흐림을 되돌린다.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_crop_compare.py` | 원본 vs alpha별 결과를 100% 확대 크롭으로 나란히 비교하는 PNG 생성. | GeoTIFF | — |
| `make_rgb.py` | BlueBON MS3(R)/MS2(G)/MS1(B) 컴포짓 미리보기 PNG 생성. | GeoTIFF | 이미지 |
| `make_zoom_compare.py` | 임의 영역을 원본/alpha별로 2x2 격자에 확대 비교. | GeoTIFF | — |
| `mtf_edge.py` | 경사 에지법(ISO 12233 계열)으로 원본/deblur 영상의 MTF 를 측정한다. | GeoTIFF | — |
| `mtf_kernel.py` | 추정된 blur 커널에서 직접 MTF 를 계산한다. | GeoTIFF | NumPy |
| `mtf_plot.py` | 경사 에지 MTF 곡선 그림 (3밴드 x 2방향 스몰 멀티플). | GeoTIFF | PNG 그림 |
| `mtf_selftest.py` | 경사 에지 MTF 측정 코드의 자체 검증. | — | — |
| `mtf_spectral.py` | 스펙트럼 비율로 deblur 의 주파수별 이득 G(f) 와 시스템 MTF 를 추정한다. | GeoTIFF | NumPy |
| `run_deblur.sh` | BlueBON MS1(Blue)/MS2(Green)/MS3(Red) L0 blind deblurring ./run_deblur.sh kernel     커널 추정 (3밴드 동시, 약 5분) | TIF · TIFF | — |
| `tile_deconv.py` | deconv 를 타일 분할 + 프로세스 병렬로 실행해 전체 해상도 결과를 만든다. | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `validate_tiling.sh` | 실행 중인 단일프로세스 deconv 가 끝나기를 기다린 뒤, 타일 방식으로 MS1 alpha=1000 을 다시 계산해 전체이미지 결과와 비교한다. | GeoTIFF | — |
