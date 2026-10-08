# sar/sentinel-1/water

수체 관련 — 물은 SAR에서 어둡게 보인다는 공통 성질을 씀.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`flood/`](flood/) | **홍수 탐지.** Edge-Otsu 자동 임계값으로 수체를 분리하고 전후 차분으로 침수역을 냄. |
| [`oil-spill/`](oil-spill/) | 기름막은 모세관파를 감쇠시켜 어둡게 보인다 — dark spot 탐지. |
