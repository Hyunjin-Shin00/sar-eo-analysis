# eo/bluebon/l0-to-l1a

**L0 → L1A.** 원시 바이너리 패킷을 읽어 영상으로 만든다. FEE/CEM 텔레메트리 점검과 촬영 시험 스크립트 포함.

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`L1C_batch/`](L1C_batch/) | L1C 일괄 전처리 진입점. |
| [`fee_cem/`](fee_cem/) | FEE/CEM 보드 텔레메트리 확인과 촬영 시험 — 지상 검증 장비 쪽. |
| [`src/`](src/) | DN → Radiance → TOA 반사도 변환, RGB 합성, 밴드 처리. |
