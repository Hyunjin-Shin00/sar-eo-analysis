# dinov3_v2 — Stage 1 인스턴스 분할

DINOv3 ViT-L/16(동결) + Mask2Former 헤드로 장면에서 건물 인스턴스를 찾는 단계임.
여기서 나온 박스가 [`../dinov3_poly/`](../dinov3_poly/) Stage 2 의 입력이 됨.

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `train_dinov3_mask2former.py` | 학습 본체. 백본 동결, 마지막 2블록만 학습 | 512 타일 + COCO 형식 라벨 | `runs/<name>/best_*.pth`, `run_config.json` |
| `infer.py` | 추론. mask-IoU 점수로 인스턴스를 순위·임계 처리하고 타일을 이어 붙임 | 장면 PNG, 체크포인트 | `<scene>_masks.npz` (마스크·박스·점수) |
| `heads.py` | mask-IoU 평가 헤드 — 분류점수만으로는 마스크 품질을 못 가려서 넣음 | 디코더 특징 | 인스턴스별 품질 점수 |
| `losses.py` | 보조 손실 3종(경계·충돌·crowd). 전부 매칭 없이 모델 출력만으로 계산 | 예측 마스크 | 스칼라 손실 |
| `augment.py` | 임의각 회전 등 증강 | 타일·라벨 | 증강된 타일·라벨 |
| `polygonize.py` | 마스크 → 폴리곤. 타일 접합·중복 제거 이후에 돎 | 스티칭된 마스크 | 폴리곤 좌표 |
| `pst.py` | HoliTracer 식 2차 폴리곤 정제 (MCR 균일 재샘플 → PST) | 폴리곤 | 정제된 폴리곤 |
| `vertex.py` | 영상 조건부 꼭짓점 보정 — Stage 2 의 전신 | 폴리곤·영상 | 보정된 꼭짓점 |
| `eval.py` | 인스턴스 분할 지표 산출 (COCO 참값 대비) | 예측·GT | AP·recall 표 |
| `runlog.py` | 학습 설정 기록과 체크포인트 이름 규칙 | — | `run_config.json` |
| `selftest.py` | **GPU·데이터·가중치 없이** 몇 초 만에 구조를 검증 | — | 통과/실패 수 |

## 실행

```bash
python selftest.py                                   # 설치 점검, 0 failures 확인
python infer.py --ckpt <stage1.pth> --images scene.png \
                --out stage1_preds --overlap 256 --threshold 0.05 --save-masks
```

## 가중치

- 학습본 `best_ep08.pth`(run7, 1.32 GB)는 용량과 라이선스 때문에 저장소에 없음
- 구조·하이퍼파라미터·결과는 [`../model/stage1_run7_config.json`](../model/stage1_run7_config.json) 에 전량 있음
- 체크포인트에 gated 백본 `facebook/dinov3-vitl16-pretrain-lvd1689m` 이 동결 포함되므로 재배포 시 해당 라이선스를 따름
- 사용 전 `huggingface-cli login` 과 웹에서의 라이선스 동의가 필요함
