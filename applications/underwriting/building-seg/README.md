# building-seg — 건물 분할 모델 (2단 폴리곤 추출)

## 무엇인가
위성영상에서 건물을 **벡터 폴리곤**으로 뽑는 2단 파이프라인. 픽셀 마스크가 아니라 꼭짓점이 찍힌 폴리곤이 산출물임.

- **Stage 1 (`code/building-seg/dinov3_v2`)** — 인스턴스 분할. DINOv3 ViT-L/16(동결 백본) + Mask2Former 헤드. 타일 단위로 "어디에 어떤 건물이 있는가"를 마스크·박스·점수로 냄.
- **Stage 2 (`code/building-seg/dinov3_poly`)** — 꼭짓점 헤드. 건물 하나를 잘라 256×256 로 정규화한 뒤 ResNet-18 인코더 + 4개 헤드(mask·vertex·offset·edge)로 "이 건물의 모서리가 정확히 어디인가"를 직접 예측. 마스크는 꼭짓점 **순서**만 정함.

두 단계는 박스를 통해 통신하고 따로 학습됨. 상세 구조·손실·연결 알고리즘은 `notes/building-seg/report/03_model.md` 에 전문이 있음.

## 입력
- 학습: 한국 산업·교외 건물 항공/위성영상 0.5 m/px, 10개 장면 수작업 폴리곤 라벨(6,425동·31,097꼭짓점). Stage1 은 512×512 타일(회전증강), Stage2 는 장면 원본을 건물별로 크롭. (`report/02_dataset.md`)
- 추론: 장면 PNG 1장(임의 크기). Stage2 는 Stage1 이 낸 `<scene>_masks.npz`(박스·점수)를 추가로 받음.

## 출력
- Stage1: `<scene>_masks.npz` (인스턴스 마스크·박스·점수).
- Stage2: `<scene>_polys.json` — `{"shape":[H,W], "polygons":[...]}`, 폴리곤마다 `polygon·score·n_vertices·source·from_mask`(꼭짓점별 출처) 기록.

## 모델 가중치 (번들 포함 여부는 MANIFEST 참조)
- **Stage1 `best_ep08.pth` (run7, 1.32 GB)** — 100 MB 초과라 번들 미포함. 파일명·크기·sha256·원본경로는 MANIFEST 에 있음. 이 체크포인트에는 gated 백본(`facebook/dinov3-vitl16-pretrain-lvd1689m`)이 동결된 채 들어 있어 재배포 시 그 라이선스를 따름.
- **Stage2 `best.pth` (run2, 51 MB)** — `model/stage2_dinov3_poly_run2_best.pth` 로 포함. 추가로 torchvision ResNet-18(ImageNet) 가중치가 런타임에 자동 다운로드됨.
- 학습 하이퍼파라미터 전량은 `model/stage1_run7_config.json`(실측 결과·파생값 포함).

## 실행 (요약; 전문은 `report/04_usage.md`)
```
conda create -n bldseg python=3.10 && conda activate bldseg
pip install torch torchvision "transformers>=4.40" opencv-python pycocotools numpy scipy pillow tqdm
huggingface-cli login            # DINOv3 는 gated — 웹에서 라이선스 동의 필요
# 설치 점검( GPU·데이터 불필요 ):
cd code/building-seg/dinov3_poly && python selftest.py   # 0 failures
cd code/building-seg/dinov3_v2   && python selftest.py
# 체크포인트만 있으면 추론은 C→E:
# C) python dinov3_v2/infer.py --ckpt <stage1.pth> --images scene.png --out stage1_preds --overlap 256 --threshold 0.05 --save-masks
# E) python dinov3_poly/infer.py --ckpt <stage2.pth> --images scene.png --stage1 stage1_preds --out preds
```

## 성능 (오염 제거한 scene val band 778 instances, v1 규칙기반 → v2 꼭짓점헤드)
- 코너 F1@2px **26.5% → 42.1%** (+15.6pt) — 핵심 개선.
- 평균 IoU 0.807 → 0.825, C-IoU 0.743 → 0.780, PoLiS 3.09 → 2.75(낮을수록 좋음), 정점수 5.11 → 4.87(GT 4.83).
- recall 동일(0.656 ↔ 0.657) — 같은 탐지기라 당연. 전체 지표표는 `report/05_results.md`.
- 한계(정직 기록): v2 가 이웃 폴리곤과 면적 0.73% 중복(v1 은 0.02%). 크롭별 독립생성 탓이며 위 지표에는 안 잡히는 소규모 회귀임.

## 정리 시 뺀 것 (최종 추론·학습 경로만 남김)
- `runs/`(체크포인트 디렉터리) — 가중치는 위 규칙대로 분리 처리.
- `__pycache__/` — 바이트코드.
- 원본 전달본의 `dataset/`(2.3 GB 학습타일·장면), `SAMPolyBuild/`(2.6 GB 참조구현·런타임 미사용), `output/` 시각화 PNG 5,948장(3.0 GB) — 재학습·재현용이라 공개 번들에서 제외. 원본 알집 7.5 GB 중 추론 핵심은 약 1.4 GB.
- `selftest.py` 는 **남김** — GPU·데이터 없이 설치·모델형상을 검증하는 전달 필수 도구라 `test_*` 제외 규칙에서 예외로 둠.
