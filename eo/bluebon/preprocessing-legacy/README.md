# eo/bluebon/preprocessing-legacy

로컬 PC 에 있던 구 전처리 스크립트 — 위 `l0-to-l1a/` 로 대체됐지만 배치 쉘 흐름 참고용으로 남겨 둔다.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_rgb_png.py` | 방사보정 TIFF를 이용해 contrast/gamma 조절된 RGB PNG를 생성하는 코드 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `merge_bands.py` | 단일밴드 TIFF 파일을 하나의 멀티밴드 TIFF로 합치는 스크립트 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `read_thuillier.py` | [구판] Thuillier 스펙트럼 로드 | — | — |
| `run.sh` | [구판] 전처리 배치 진입점 | — | — |
| `run_band.sh` | [구판] 단일 밴드 전처리 | — | — |
