# eo/cubesat/preprocessing

원시 바이너리 → DN → Radiance → TOA 반사도 → RGB.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `make_rgb_png.py` | 방사보정 TIFF를 이용해 contrast/gamma 조절된 RGB PNG를 생성하는 코드 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `merge_bands.py` | 단일밴드 TIFF 파일을 하나의 멀티밴드 TIFF로 합치는 스크립트 | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `read_thuillier.py` | Thuillier 태양 복사조도 스펙트럼 로드 — TOA 반사도 변환용 | — | — |
| `run.sh` | 전처리 배치 진입점 — 장면 폴더를 순회하며 밴드 병합·RGB 생성 | — | — |
| `run_band.sh` | 단일 밴드 전처리 (DN → Radiance → 반사도) | — | — |
