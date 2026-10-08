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

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate bldseg      # PyTorch · transformers
```

- 환경 정의: [`environment/`](../../../../../../environment/)

### 진입점

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
python sitecheck_worker.py --scene <값> --out <값> --ckpt <값>
```
장면(또는 그 일부) → 건물 폴리곤. **`infer.py` 의 함수를 그대로 부름.** 이 파일은 벤더한 코드에 손대지 않기 위해 있음. 원본의 `infer.py main()` 은 「폴더 안 이미지 전부 → 겹친 그림 + npz」를 내고, `polygonize.p

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--scene` | ● |  | assets/scenes/<key> 폴더 |
| `--out` | ● |  | 쓸 json 경로 |
| `--ckpt` | ● |  |  |
| `--region` |  |  | x0,y0,x1,y1 (없으면 전장면) |
| `--crop` |  | `512` |  |
| `--overlap` |  | `256` |  |
| `--input-size` |  | `0` | 0=체크포인트 cfg 값 |
| `--threshold` |  | `0.1` |  |
| `--score-mode` |  | `cls_iou` |  |
| `--mask-threshold` |  | `0.5` |  |
| `--min-area` |  | `100` |  |
| `--iou-thr` |  | `0.5` |  |
| `--ios-thr` |  | `0.8` |  |
| `--tta` |  |  |  |
| `--no-clean` |  |  |  |
| `--min-side` |  | `8.0` |  |
| `--max-aspect` |  | `6.0` |  |
| `--min-frac` |  | `0.15` |  |
| `--max-hole-frac` |  | `0.25` |  |
| `--open-k` |  | `3` |  |
| `--close-k` |  | `5` |  |
| `--clean-ios-thr` |  | `0.6` |  |
| `--poly-min-area` |  | `200` |  |
| `--poly-min-iou` |  | `0.7` |  |
| `--dp-eps` |  | `3.0` |  |
| `--angle-tol` |  | `20.0` |  |
| `--min-edge` |  | `3.0` |  |
| `--free-form` |  |  |  |
| `--no-corner-restore` |  |  |  |
| `--no-fallback` |  |  |  |
| `--quiet` |  |  |  |

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
| `--select-by` |  | `ap` | which val metric picks best_ep*.pth. DEFAULT CHANGED to 'ap' -- runs u |
| `--ckpt-every` |  | `0` | also save snap_ep*.pth every N epochs, keeping ALL of them (~1.6 GB ea |
| `--seed` |  | `0` | seeds python/numpy/torch and the DataLoader workers. SET THE SAME VALU |
| `--fragment-weight` |  | `1.0` | TIER 2b. Mirror of --collision-weight: penalises TWO queries splitting |
| `--collision-active-thr` |  | `0.2` | a query counts as 'active' (and so is charged) once it covers this fra |
| `--crowd-weight` |  | `3.0` | TIER 2. Extra weight the boundary loss puts on the band where two buil |
| `--crowd-gap` |  | `3` | how close (in mask-logit px) two instances must be to count as a crowd |
