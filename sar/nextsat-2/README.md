# sar/nextsat-2

**차세대소형위성 2호 (국산 X-band).** 어떤 상용·공개 SW도 지원하지 않아 처리기를 직접 만들었음.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`change-detection/`](change-detection/) | N2 진폭변화탐지(ACD) — 세 기법 중 유일하게 구조가 남는 관측. |
| [`insar/`](insar/) | N2 자체 파이썬 간섭처리 (ISCE2 비의존 경로). |
| [`isce2-spoofing/`](isce2-spoofing/) | ISCE2를 고치지 않고 COSMO-SkyMed 리더를 **런타임 패치**해 N2를 처리함. |
| [`offset-tracking/`](offset-tracking/) | NCC 정합 + 부화소 피크 추정. N2·S1 양쪽에 씀. |
| [`sensor-model/`](sensor-model/) | 거리-도플러 **엄밀센서모델**을 처음부터 구현해 지오코딩함. `step01`~`step13` 번호가 처리 순서. |
