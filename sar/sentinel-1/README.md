# sar/sentinel-1

**Sentinel-1 (C-band).** 가장 많이 쓴 위성. 전처리 → 기법별 분석 순서로 배치했다.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`change-detection/`](change-detection/) | **변화탐지.** 위상이 아니라 코히런스·진폭의 변화를 본다 — 탈상관이 심한 곳에서도 동작한다. |
| [`insar/`](insar/) | 간섭측량. 아래 기법별 폴더로 나뉘며, 입력은 모두 코레지된 SLC 스택이다. |
| [`isce2-patches/`](isce2-patches/) | ISCE2가 지원하지 않는 Sentinel-1D 를 쓰기 위한 패치. |
| [`preprocessing/`](preprocessing/) | SLC·GRD 전처리와 스택 코레지스트레이션. 모든 기법의 공통 입구. |
| [`water/`](water/) | 수체 관련 — 물은 SAR에서 어둡게 보인다는 공통 성질을 쓴다. |
