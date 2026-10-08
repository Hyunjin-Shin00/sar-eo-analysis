# dinov3seg — 건물 탐지기 (vendor 사본, run4 세대)

`report-gen` 이 실제로 쓰는 탐지기임.
[`../../../../building-seg/dinov3_v2/`](../../../../building-seg/dinov3_v2/) 의 **그 전 세대(run4)** 이고,
개선본(run7 + 꼭짓점 헤드)으로의 교체는 `building-seg` 쪽 지침을 따름.

벤더한 코드에 손대지 않는 것이 원칙이라, 호출 방식만 `sitecheck_worker.py` 로 감쌈.

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `sitecheck_worker.py` | 장면(또는 일부) → 건물 폴리곤. `infer.py` 함수를 그대로 부름 | 장면 창 | 폴리곤 |
| `infer.py` | 추론 본체. mask-IoU 점수로 순위·임계 처리 | 영상, 체크포인트 | 마스크·박스·점수 |
| `build_offline.py` | `build_model` 의 **오프라인 쌍둥이** — 허깅페이스에 나가지 않고 같은 구조를 세움 | `hf/` 설정 | 모델 객체 |
| `train_dinov3_mask2former.py` | 학습 본체 (참조용) | 타일·라벨 | 체크포인트 |
| `heads.py` · `losses.py` · `augment.py` · `polygonize.py` · `runlog.py` | `building-seg/dinov3_v2` 와 같은 구성 | — | — |

## 가중치

- `models/building/dinov3_v2_run4_best_ep11.pth`(1.32 GB) — 원본 저장소에서 Git-LFS 로 관리되며 **저장소에 없음**
- sha256 과 원본 경로는 번들 MANIFEST 에 기록돼 있음
- 이 체크포인트에도 gated 백본이 동결 포함되므로 재배포 시 해당 라이선스를 따름

## 오프라인 구성

`hf/` 아래 두 모델의 `config.json` · `preprocessor_config.json` 만 둠 — **가중치는 없음**.
망 없이 같은 구조를 세우기 위한 설정 사본임.

| 폴더 | 용도 |
|---|---|
| `hf/dinov3-vitl16-pretrain-lvd1689m/` | 백본 구조 (gated) |
| `hf/mask2former-swin-base-coco-instance/` | 헤드 warm-start 구조 |
