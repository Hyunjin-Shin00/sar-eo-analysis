# sar/sentinel-1/change-detection/amplitude

**ACD** — 진폭 로그비로 변화를 봄. 코히런스가 아예 없을 때의 대안.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `change_detect.py` | 지바 최종 침수 영역 — 변화 기반 판정으로 재생산함. | GeoTIFF · NumPy | GeoTIFF · CSV · 텍스트/로그 |
| `measure_change.py` | 지바 케이스의 모든 면적·거리를 원격자(10 m)에서 잰다 — 보고 수치의 단일 출처. | GeoTIFF · NumPy | — |
