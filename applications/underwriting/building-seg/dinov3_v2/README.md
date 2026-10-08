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

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate bldseg      # PyTorch · transformers
```

- 환경 정의: [`environment/`](../../../../environment/)

### 진입점

```bash
python eval.py --gt <값>
```
eval_masks.py -- instance-segmentation metrics for building masks. Compares predictions against COCO ground truth from tile_to_coco_v2.py. Accepts two

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--gt` | ● |  | COCO annotations.json |
| `--npz` |  |  | repeatable: folder of *_masks.npz |
| `--json` |  |  | repeatable: COCO-results json (SAMPolyBuild style) |
| `--name` |  |  | label per prediction source, in the order given (--npz first, then --j |
| `--iou-thr` |  | `0.5` |  |
| `--crowd-ios-thr` |  | `0.5` | TIER 0. An unmatched prediction whose own area is at least this fracti |
| `--dilation-ratio` |  | `0.02` | boundary band width as a fraction of the image diagonal, per Cheng et  |
| `--boundary-px` |  |  | override the band with an absolute pixel width. Diagnostic only -- not |
| `--score-thr` |  | `0.0` | for P/R/F1 only; AP always integrates all scores |
| `--score-key` |  |  | REPEATABLE, paired with the sources in order exactly like --name. Whic |
| `--out` |  |  | write results as json |

```bash
python infer.py --ckpt <값> --images <값> --out <값>
```
Inference for the DINOv3 + Mask2Former building segmenter (v2). v2 ranks and thresholds instances by the mask-IoU head (`--score-mode`), not by `cls x

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--ckpt` | ● |  | checkpoint file, OR a run directory -- then the newest checkpoint with |
| `--ckpt-tag` |  | `best` | which of the two rolling checkpoints to load when --ckpt is a RUN DIRE |
| `--images` | ● |  |  |
| `--out` | ● |  |  |
| `--dinov3` |  | `facebook/dinov3-vitl16-pretrain-lvd1689m` |  |
| `--m2f` |  | `facebook/mask2former-swin-base-coco-instance` |  |
| `--tile-size` |  | `512` |  |
| `--overlap` |  | `128` |  |
| `--threshold` |  | `0.5` |  |
| `--tta` |  |  | average masks over the 8 square symmetries. Refines boundaries; costs  |
| `--min-area` |  | `100` |  |
| `--iou-thr` |  | `0.5` |  |
| `--ios-thr` |  | `0.8` |  |
| `--score-mode` |  | `cls_iou` | ranking / thresholding signal. cls_iou (default) and iou use the v2 ma |
| `--mask-threshold` |  | `0.5` | sigmoid cut for mask binarization. Lower (~0.35) if masks look inset r |
| `--alpha` |  | `0.45` |  |
| `--show-scores` |  |  | also print cls and mask-quality under each score, so a bad prediction  |
| `--side-by-side` |  |  |  |
| `--no-clean` |  |  | skip the cleaning stage (morphology, hole fill, component split, re-de |
| `--min-side` |  | `8.0` | drop instances whose minAreaRect short side is below this many px. At  |
| `--max-aspect` |  | `6.0` | drop instances whose minAreaRect long/short ratio exceeds this. 0 disa |
| `--min-frac` |  | `0.15` | clean: drop blobs below this fraction of the largest |
| `--max-hole-frac` |  | `0.25` |  |
| `--open-k` |  | `3` |  |
| `--close-k` |  | `5` |  |
| `--clean-ios-thr` |  | `0.6` | containment threshold for the SECOND de-dup, the one inside clean_inst |
| `--viz-stages` |  |  | write a stacked raw / dedup / clean comparison |
| `--save-masks` |  |  | also write .npz with instance masks + scores (for MCR/PST) |
| `--save-raw-masks` |  |  | also write <stem>_raw_masks.npz: the instance pool BEFORE de-duplicati |

```bash
python polygonize.py --masks <값>
```
Mask -> polygon, for the DINOv3 + Mask2Former building segmenter. Runs AFTER stitching and de-duplication, on complete scene-level instances. See poly

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--masks` | ● |  | folder of *_masks.npz from infer --save-masks (a single .npz also work |
| `--out` |  |  | output folder for JSON. Default: alongside the npz. |
| `--images` |  |  | folder holding the source tiles, for the raw panel. The *_overlay.png  |
| `--ann` |  |  | COCO annotations.json; adds a ground-truth polygon panel to --viz so p |
| `--viz` |  |  | write raw/mask/polygon panels to <npz folder>/polygon/ |
| `--alpha` |  | `0.45` |  |
| `--dp-eps` |  | `3.0` |  |
| `--angle-tol` |  | `20.0` |  |
| `--min-edge` |  | `3.0` |  |
| `--no-corner-restore` |  |  | keep chamfered corners instead of reconstructing the right angle from  |
| `--no-fallback` |  |  | drop instances whose regularization fails instead of falling back to a |
| `--min-area` |  | `200` |  |
| `--min-iou` |  | `0.7` |  |
| `--free-form` |  |  | skip rectilinear snapping (plain Douglas-Peucker) |

```bash
python pst.py --masks <값> --coco <값> --images <값> --out <값> --data <값> --ckpt <값> --masks <값> --images <값> --out <값>
```
pst.py -- HoliTracer-style second-stage polygon refinement. mask -> MCR (uniform contour resampling) -> PST (learned tracer) -> polygon The point of t

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--masks` | ● |  |  |
| `--coco` | ● |  |  |
| `--images` | ● |  |  |
| `--out` | ● |  |  |
| `--max-pair-dist` |  | `30.0` |  |
| `--data` | ● |  |  |
| `--out` |  | `runs/pst` |  |
| `--dinov3` |  | `facebook/dinov3-convnext-large-pretrain-lvd1689m` |  |
| `--feat-dim` |  | `256` |  |
| `--iters` |  | `3` |  |
| `--offset-scale` |  | `1.0` | multiplier on the predicted offset. Tested: 1.0 reaches 103-108%% of t |
| `--epochs` |  | `40` |  |
| `--lr` |  | `0.0001` |  |
| `--w-vtx` |  | `2.0` | weight on vertex classification; the offset term is ~56%% of the loss  |
| `--pos-weight` |  | `7.6` | BCE positive weight. Only ~11.7%% of points are vertices; without this |
| `--ckpt` | ● |  |  |
| `--masks` | ● |  |  |
| `--images` | ● |  |  |
| `--out` | ● |  |  |
| `--vtx-thr` |  | `0.5` |  |
| `--rectify` |  |  | snap PST's traced points to right angles. PST has no rectilinearity ob |
| `--dp-eps-rect` |  | `2.0` |  |
| `--angle-tol` |  | `25.0` |  |
| `--min-edge` |  | `4.0` |  |
| `--viz` |  |  | write raw|mask|polygon panels to <out>/overlay/ |
| `--alpha` |  | `0.42` |  |
| `--gsd` |  | `0.5` | m/px. Spatial params are given for 0.5 and rescaled from this. |
| `--interp` |  | `4.0` |  |
| `--dp-eps` |  | `1.0` |  |

```bash
python train_dinov3_mask2former.py 
```
DINOv3 (frozen) + Mask2Former instance segmentation, for building extraction. v2. Changes over v1, each sized against a measured v1 failure mode on th

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--data-root` |  | `./data` |  |
| `--dinov3` |  | `facebook/dinov3-vitl16-pretrain-lvd1689m` | ViT: facebook/dinov3-vitl16-pretrain-lvd1689m | ConvNeXt: facebook/din |
| `--num-queries` |  |  | grow the query set (COCO default 100). Mask2Former can match at most t |
| `--backbone` |  | `auto` | auto = infer from --dinov3 (looks for 'convnext') |
| `--p-mosaic` |  | `0.0` |  |
| `--p-rot-any` |  | `0.2` | probability of an arbitrary-angle rotation on top of D4. NOTE D4 alone |
| `--rot-mode` |  | `pad` | how rotate_any avoids border fill. pad (default) rotates in place and  |
| `--p-scale` |  | `0.8` |  |
| `--basa-p` |  | `0.0` | BaSA probability. Only useful with multi-scene data and batch>=4; near |
| `--boundary-weight` |  | `2.0` | weight of the auxiliary boundary loss. 0 = off. In BCE units, comparab |
| `--boundary-width` |  | `3` | half-width in mask-logit pixels of the band around the GT edge that th |
| `--unfreeze-last` |  | `0` | fine-tune the last N transformer blocks of the backbone at --backbone- |
| `--backbone-lr-mult` |  | `0.1` | backbone LR relative to --lr; the head is 1x and the randomly-initiali |
| `--no-stem` |  |  | disable the stride-4 stem (ViT only; for ablation) |
| `--m2f` |  | `facebook/mask2former-swin-base-coco-instance` |  |
| `--image-size` |  | `512` |  |
| `--epochs` |  | `60` |  |
| `--batch-size` |  | `2` |  |
| `--lr` |  | `0.0001` |  |
| `--out` |  | `./runs/dinov3_m2f` |  |
| `--crowd` |  | `instance` | TIER 0. What to do with iscrowd annotations. All of them are tile-edge |
| `--taps` |  | `auto` | TIER 3. Which ViT blocks feed the 4 pyramid levels: 'auto' (evenly spr |
| `--maskiou-weight` |  | `1.0` | TIER 1. Weight of the mask-IoU regression loss. The head is a detached |
| `--maskiou-hidden` |  | `256` |  |
| `--no-maskiou-detach` |  |  | let the IoU head's gradient reach the pixel decoder. OFF by default: d |
| `--collision-weight` |  | `1.0` | TIER 2. Weight of the query-collision loss, which penalises one query  |
| `--scale-range` |  |  | zoom-in jitter range, applied with probability --p-scale. DEFAULT CHAN |
| `--select-by` |  | `ap` | which val metric picks best_ep*.pth. DEFAULT CHANGED to 'ap' -- runs u |
| `--ckpt-every` |  | `0` | also save snap_ep*.pth every N epochs, keeping ALL of them (~1.6 GB ea |
| `--seed` |  | `0` | seeds python/numpy/torch and the DataLoader workers. SET THE SAME VALU |
| `--fragment-weight` |  | `1.0` | TIER 2b. Mirror of --collision-weight: penalises TWO queries splitting |
| `--collision-active-thr` |  | `0.2` | a query counts as 'active' (and so is charged) once it covers this fra |
| `--crowd-weight` |  | `3.0` | TIER 2. Extra weight the boundary loss puts on the band where two buil |
| `--crowd-gap` |  | `3` | how close (in mask-logit px) two instances must be to count as a crowd |

```bash
python vertex.py --data-root <값> --ckpt <값> --masks <값> --images <값> --out <값> --ckpt <값> --data-root <값> --masks <값>
```
Tier 4 -- image-conditioned polygon vertex refinement. WHAT THIS IS FOR, AND WHAT IT IS NOT FOR ---------------------------------------- Measured on t

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--data-root` | ● |  |  |
| `--masks-dir-train` |  |  | folder of *_masks.npz for the TRAIN tiles. Strongly preferred over the |
| `--masks-dir-val` |  |  |  |
| `--size` |  | `128` | crop resolution. This is the model's spatial budget for sub-pixel corn |
| `--k` |  | `64` | contour sample points. GT polygons have <=6 vertices 79%% of the time, |
| `--dim` |  | `128` |  |
| `--layers` |  | `3` |  |
| `--max-shift` |  | `0.12` | offset bound in normalised crop units. 0.12 at size 128 is ~7.7 crop p |
| `--corner-weight` |  | `1.0` |  |
| `--epochs` |  | `40` |  |
| `--batch-size` |  | `32` |  |
| `--workers` |  | `4` |  |
| `--lr` |  | `0.0003` |  |
| `--out` |  | `./runs/vertex` |  |
| `--ckpt` | ● |  | checkpoint file, or a run directory |
| `--ckpt-tag` |  | `best` | which of the two rolling checkpoints to load when --ckpt is a RUN DIRE |
| `--masks` | ● |  | folder of *_masks.npz |
| `--images` | ● |  |  |
| `--out` | ● |  |  |
| `--seeds` |  |  | folder of *_polys.json from polygonize.py, used as the seed polygons.  |
| `--corner-thr` |  | `0.5` |  |
| `--min-gap` |  | `2` | minimum index separation between kept corners |
| `--min-iou` |  | `0.8` | reject the refinement if the resulting polygon agrees with its own mas |
| `--min-area` |  | `200` |  |
| `--ckpt` | ● |  | checkpoint file, or a run directory |
| `--ckpt-tag` |  | `best` | which of the two rolling checkpoints to load when --ckpt is a RUN DIRE |
| `--data-root` | ● |  | a SPLIT dir (…/val), containing images/ and annotations.json |
| `--masks` | ● |  | folder of *_masks.npz |
| `--seeds` |  |  | folder of *_polys.json from polygonize.py; match whatever you pass to  |
| `--corner-thr` |  | `0.5` |  |
| `--min-gap` |  | `2` |  |
| `--min-iou` |  | `0.8` |  |
| `--min-area` |  | `200` |  |

## 가중치

- 학습본 `best_ep08.pth`(run7, 1.32 GB)는 용량과 라이선스 때문에 저장소에 없음
- 구조·하이퍼파라미터·결과는 [`../model/stage1_run7_config.json`](../model/stage1_run7_config.json) 에 전량 있음
- 체크포인트에 gated 백본 `facebook/dinov3-vitl16-pretrain-lvd1689m` 이 동결 포함되므로 재배포 시 해당 라이선스를 따름
- 사용 전 `huggingface-cli login` 과 웹에서의 라이선스 동의가 필요함
