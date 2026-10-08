# 4. How to run it

Every command assumes the environment is active:

```bash
conda activate bldseg
```

---

## 4.1 The pipeline

```
  A. generate tiles          dataset/refined_data/tile_to_coco_multi_rot.py
            │                (only if the labels changed)
            ▼
  B. train stage 1           dinov3_v2/train_dinov3_mask2former.py     ~15 min/epoch
            │
            ▼
  C. run stage 1 on scenes   dinov3_v2/infer.py --save-masks
            │                produces <scene>_masks.npz  ← stage 2's input
            ▼
  D. train stage 2           dinov3_poly/train.py                      ~35 s/epoch
            │
            ▼
  E. run stage 2             dinov3_poly/infer.py
            │                produces <scene>_polys.json
            ▼
  F. score it                dinov3_poly/bench.py
```

**If checkpoints already exist**, the loop you will actually spend time in is
**D → E → F**. Steps A–C only need repeating when the labels or the detector
change.

**If you only want polygons from existing checkpoints**, run **C → E**.

---

## 4.2 Step A — generate the training tiles

Only needed after editing labels. See `02_dataset.md` for the logic.

```bash
cd dataset/refined_data

# scenes live one per sub-folder and the label file is annotations.json rather
# than <stem>.json, so --img-dir cannot pair them -- build --src pairs instead
SRC=()
for d in scenes/*/; do
    n=$(basename "$d")
    SRC+=(--src "$d$n.png" "${d}annotations.json")
done

python tile_to_coco_multi_rot.py "${SRC[@]}" \
    --out data_stride128_rot \
    --tile 512 \
    --stride 128 \
    --rot 0 15 30 45 \
    --rot-val \
    --val-width 725 \
    --max-black 0.02 \
    --min-keep 0.4 \
    --min-area 64
```

> `--img-dir` / `--ann-dir` is the alternative, but it only works on a **flat**
> folder where each image sits beside a JSON of the same stem (`toy.png` +
> `toy.json`). It does not recurse into sub-folders, so it cannot read this
> layout.

### Generating one split at a time

```bash
python tile_to_coco_multi_rot.py "${SRC[@]}" --out data_stride128_rot \
    --tile 512 --stride 128 --rot 0 15 30 45 --rot-val --val-width 725 \
    --only train
```

`--only train` / `--only val` writes just that side. **The split boundary does
not move**: the val band is still computed from `--val-width` exactly as in a
full run, and tiles belonging to the other side are simply not written. Running
`--only train` and then `--only val` into the same `--out` therefore produces
byte-identical tiles and annotations to a single `--only both` run -- verified
against a full run, not assumed.

Nothing is deleted between runs and `dataset_info.json` merges rather than
overwrites, so the record of the split you did not regenerate survives; its
`generated` field lists what is present.

Useful when only one side needs rebuilding -- re-tiling train with different
rotations while leaving a validated val set untouched, for instance.

| argument | meaning |
|---|---|
| `--src IMAGE JSON` | one scene and its labels. Repeatable -- one pair per scene |
| `--img-dir` / `--ann-dir` | alternative for a flat folder paired by filename stem; does not recurse |
| `--out` | output dataset directory; `train/` and `val/` are created inside |
| `--tile` | tile size in pixels |
| `--stride` | step between tiles. 128 with tile 512 gives 384 px overlap |
| `--rot` | rotation angles to generate, in degrees. `0` alone disables rotation |
| `--rot-val` | also rotate the validation band. Without it val is axis-aligned only |
| `--val-width` | width in px of the held-out band on the **right** of each scene. Overrides `--val-frac`. Must be ≥ ~1.5× the tile size or steep angles yield no clean val tiles |
| `--max-black` | drop a rotated tile if more than this fraction is border fill |
| `--min-keep` | a clipped building keeps its label only if this fraction of its original area survives; below it, it is marked `iscrowd` |
| `--min-area` | drop polygons smaller than this many px² after clipping |
| `--only` | `both` (default), `train` or `val` -- generate one split without moving the boundary |

Check `data_stride128_rot/dataset_info.json` afterwards — it records exactly
what was generated and with which settings.

---

## 4.3 Step B — train stage 1

```bash
cd dinov3_v2
python train_dinov3_mask2former.py \
    --data-root ../dataset/refined_data/data_stride128_rot \
    --out ./runs/run7 \
    --image-size 1024 \
    --num-queries 200 \
    --batch-size 4 \
    --epochs 20 \
    --lr 1e-4 \
    --taps auto \
    --crowd instance \
    --unfreeze-last 2 \
    --backbone-lr-mult 0.1 \
    --boundary-weight 5.0 \
    --collision-weight 3.0 \
    --crowd-weight 3.0 \
    --maskiou-weight 1.0 \
    --fragment-weight 0.0 \
    --p-mosaic 0.0 \
    --p-rot-any 0.2 \
    --rot-mode pad \
    --scale-range 1.2 2.8 \
    --seed 0
```

| argument | meaning |
|---|---|
| `--data-root` | the tiled dataset from step A |
| `--out` | run directory; writes `best_ep*.pth`, `last_ep*.pth`, `loss_log.csv`, `run_config.json` |
| `--image-size` | what the 512 tile is resized to before the backbone. 1024 gives a 64×64 token grid |
| `--num-queries` | Mask2Former object queries. Must exceed the instances in any one tile |
| `--batch-size` | 4 needs ~40 GB VRAM. Halve it if you run out |
| `--lr` | base learning rate for the adapter and head |
| `--taps` | which transformer blocks feed the pyramid. `auto` resolves to blocks 6/12/18/24 |
| `--crowd instance` | train tile-clipped buildings as ordinary positives. `background` is the alternative and teaches the model to suppress edge buildings — do not use it |
| `--unfreeze-last N` | unfreeze the last N backbone blocks. 0 freezes the backbone entirely |
| `--backbone-lr-mult` | learning-rate multiplier for those unfrozen blocks |
| `--boundary-weight` | extra supervision in a 3-px band around each edge |
| `--collision-weight` | penalises two queries claiming the same pixels |
| `--crowd-weight` | weight on the clipped-building term |
| `--maskiou-weight` | trains the head that predicts each mask's own quality |
| `--p-rot-any` | probability of an arbitrary-angle rotation at training time |
| `--scale-range LO HI` | zoom-and-crop jitter range |
| `--seed` | set the same value on both sides of any A/B, or a difference cannot be attributed |

Selection is on validation AP (`--select-by ap`), not loss.

**Watch:** `val_ap` should climb for the first ~10 epochs. Mask IoU around 0.83
is the expected level.

---

## 4.4 Step C — run stage 1 over the scenes

This produces stage 2's input. **Required before stage-2 inference.**

```bash
cd dinov3_v2
python infer.py \
    --ckpt ./runs/run6 \
    --ckpt-tag best \
    --images ../dataset/refined_data/scenes/daegu_crop1/daegu_crop1.png \
    --out ../dinov3_poly/stage1_preds \
    --tile-size 512 \
    --overlap 256 \
    --threshold 0.05 \
    --score-mode cls_iou \
    --save-masks
```

| argument | meaning |
|---|---|
| `--ckpt` | a checkpoint file, **or** a run directory (then `--ckpt-tag` picks which) |
| `--ckpt-tag` | `best` / `last` / `snap` when `--ckpt` is a directory |
| `--images` | one image file, or a folder of them |
| `--out` | output directory |
| `--tile-size` | must match what the model trained on |
| `--overlap` | must exceed the largest building, or a big one touches an interior edge in every tile and is dropped. At 128 about 9.6% of buildings are at risk; at 256, 0.1% |
| `--threshold` | score floor. With `--score-mode cls_iou` the score is a *predicted IoU*, not a saturated confidence — keep this low (0.05) or most true positives are discarded |
| `--score-mode` | `cls_iou` (default, uses the mask-IoU head), `cls_mq`, or `iou` |
| `--tta` | average over the 8 square symmetries. Sharpens boundaries, costs 8× inference, recovers no missed buildings |
| **`--save-masks`** | **write `<stem>_masks.npz` — this is what stage 2 reads. Without it, stage 2 has nothing to run on** |
| `--no-clean` | skip hole filling, morphology, component splitting and the second de-dup |
| `--min-side` | drop instances whose short side is below this many px (8 px = 4 m at 0.5 m/px) |
| `--viz-stages` | write a raw / dedup / clean comparison image |

To do all ten scenes, point `--images` at a folder of the scene PNGs.

---

## 4.5 Step D — train stage 2

The short form, since every other argument already defaults correctly:

```bash
cd dinov3_poly
python train.py --out ./runs/v1
```

The full form, with everything spelled out:

```bash
cd dinov3_poly
python train.py \
    --data-root ../dataset/refined_data/scenes \
    --out ./runs/v1 \
    --epochs 60 \
    --batch-size 32 \
    --lr 3e-4 \
    --workers 4 \
    --crop 256 \
    --out-size 128 \
    --val-width 725 \
    --encoder resnet18 \
    --dim 128 \
    --w-mask 1.0 --w-vmap 1.0 --w-voff 1.0 --w-edge 1.0 \
    --vertex-thr 0.3 \
    --merge 1.0 \
    --seed 0
```

| argument | default | meaning |
|---|---|---|
| `--data-root` | `../dataset/refined_data/scenes` | the **scenes**, not the tiles. Stage 2 crops whole buildings, and a tile edge cuts them |
| `--out` | required | run directory; writes `best.pth`, `last.pth`, `log.csv`, `config.json` |
| `--epochs` | 60 | ~35 s each, so the whole run is about 35 minutes |
| `--batch-size` | 32 | crops are small; ~6 GB VRAM |
| `--lr` | 3e-4 | OneCycle schedule, 10% warm-up |
| `--crop` | 256 | input size the building crop is resized to |
| `--out-size` | 128 | head output resolution — stride 2 |
| `--val-width` | 725 | **must match the tiler's**, or stage-1 training pixels leak into stage-2 validation |
| `--encoder` | `resnet18` | or `simple` for a from-scratch conv net with no download |
| `--no-pretrained` | off | skip ImageNet weights |
| `--dim` | 128 | decoder width |
| `--no-edge` | off | disable the edge head (it is the least-justified of the four; this A/Bs it) |
| `--w-mask` … `--w-edge` | 1.0 | loss weights per head |
| `--vertex-thr` | 0.3 | peak score floor used when scoring validation |
| `--merge` | 1.0 | collapse decoded peaks closer than this many cells |
| `--seed` | 0 | |

**What to watch each epoch:**

```
[ep 10/60] train 1.3520 (mask 0.099 vmap 0.557 voff 0.195 edge 0.501)
  | val 1.3657 | F1@2px 0.7790 (rec 0.740 prc 0.823) F1@4px 0.8585
  | v/GT 0.90 | maskIoU 0.9266 bias +0.14px | 35s  *
```

- **`F1@2px`** — the selection metric. Corner F1 at 2 scene pixels.
- **`rec` / `prc`** — reported separately on purpose. Recall alone cannot fall
  as the model emits more corners, so it rewards flooding the image.
- **`v/GT`** — vertices emitted per GT vertex. Should sit near 1.0. Well above
  means recall is being bought with spam.
- **`maskIoU`** — stage 2's own mask, measured on the crop grid.
- **`bias`** — signed mask boundary offset in scene px. Decides whether
  `fit_edges` is safe at inference (see below).
- **`*`** — this epoch was the best so far.

Note `F1@2px` here scores **raw corner detection**. None of the connection
logic is in that number — that only shows up in `bench.py`.

### Evaluating an existing checkpoint without retraining

```bash
python train.py --out /tmp/eval --eval-ckpt ./runs/v1/best.pth
```

Loads the checkpoint, runs one validation pass, prints every metric and exits.
The reason to run it is `mask_bias_px`, which decides the `--no-fit-edges`
question below and otherwise only appears during a fresh training run.

---

## 4.6 Step E — run stage 2

```bash
cd dinov3_poly
python infer.py \
    --ckpt ./runs/v1/best.pth \
    --images ../dataset/refined_data/scenes/daegu_crop1/daegu_crop1.png \
    --stage1 ./stage1_preds \
    --out ./preds/v1 \
    --batch 64 \
    --vertex-thr 0.3 \
    --merge 1.0 \
    --mask-thr 0.5 \
    --max-dist-frac 0.08 \
    --prune-width 0.06 \
    --refine-tol 0.06 \
    --max-add 4 \
    --min-turn 10.0 \
    --guard-min-iou 0.35 \
    --min-area 64 \
    --viz --viz-scale 0.5 --debug-crops 24
```

### Required

| argument | meaning |
|---|---|
| `--ckpt` | stage-2 checkpoint (`.pth`) |
| `--images` | scene image, or a folder |
| `--stage1` | folder holding `<stem>_masks.npz` from step C. Only boxes and scores are read from it |
| `--out` | output directory |

### Vertex decoding

| argument | default | meaning |
|---|---|---|
| `--batch` | 64 | crops per forward pass |
| `--vertex-thr` | 0.3 | peak score floor. Raise it if `v/GT` is above ~1.3 |
| `--merge` | 1.0 | collapse decoded peaks closer than this many cells. Prevents a corner sitting exactly between two cells from emitting twice |
| `--mask-thr` | 0.5 | sigmoid cut for stage 2's mask |
| `--min-area` | 64 | drop instances smaller than this in scene px² |

### Connection

| argument | default | meaning |
|---|---|---|
| `--max-dist-frac` | 0.08 | **the dominant knob.** Corners further than this fraction of the building's long side from the mask contour are discarded. Loosening it to 0.25 measured 0.765 polygon IoU and 8.7% self-intersecting rings, against 0.918 / 2.0% here |
| `--prune-width` | 0.06 | cut tentacles and bays out of the guide contour first. Without it, a 15-px tentacle reads as a missed corner and gets vertices inserted along it |
| `--refine-tol` | 0.06 | let the mask insert a corner where the polygon departs from it by more than this fraction of the long side. Fixes a well-masked L-shape reported as a quadrilateral. `0` disables |
| `--max-add` | 4 | cap on mask-inserted corners per polygon; bounds the damage when a mask is worse than typical |
| `--min-turn` | 10.0 | drop corners on a straight run (turn < this) or where the ring folds back (150–210°). Costs 0.50% of real GT corners |
| `--no-fit-edges` | off | disable wall refitting. **On by default** — worth +0.05 polygon IoU and 9× lower corner error, but it loses to the raw corners once the mask carries more than ~2 px of systematic bias. Check `bias` from step D |
| `--angle-tol` | 0 (off) | drop vertices whose direction disagrees with the contour by more than this many degrees |
| `--guard-min-iou` | 0.35 | below this polygon-vs-mask IoU, fall back to the v1 rule-based polygonizer. A catastrophe floor, not a quality comparison |

### Visualisation

| argument | meaning |
|---|---|
| `--viz` | write `<stem>_overlay.png`: raw image \| polygons, coloured by source — **green** = vertex path, **yellow** = angular fallback, **red** = rule-based guard fired |
| `--viz-scale` | downscale the panels *after* drawing, so thin outlines survive. 0.5 is comfortable for a 3000-px scene |
| `--viz-alpha` | fill opacity |
| `--viz-dot` | vertex marker radius; 0 hides them |
| `--debug-crops N` | write `<stem>_debug.png` for the first N instances: **crop \| mask + guide contour \| heatmap + candidates \| final polygon**. In the last column, **cyan** corners came from the head and **magenta** from the mask |

### Output

```
<stem>_polys.json     {"shape": [H, W], "polygons": [...]}
<stem>_overlay.png    with --viz
<stem>_debug.png      with --debug-crops
```

Each polygon record carries `polygon`, `score`, `n_vertices`, `source`,
`n_detected`, `n_added`, `from_mask` (per-vertex provenance) and
`stage1_index`.

The run line reports the split:

```
daegu_crop1.png: 713 boxes -> 698 polygons   [vertex 655 angle 12 baseline 31]
   vertices 2840 (2610 detected, 230 added by mask = 8%), 655 wall-fitted
```

- a high **baseline** count means the guard is firing and v1 is doing the work
- a high **angle** count means rings are self-intersecting
- **added by mask** around 5–10% is healthy; 30%+ means `--refine-tol` is too
  tight for your mask quality

---

## 4.7 Step F — score it

```bash
cd dinov3_poly
python bench.py \
    --scenes ../dataset/refined_data/scenes \
    --pred ./preds/v1 \
    --stage1 ./stage1_preds \
    --val-width 725 \
    --match-iou 0.5
```

| argument | default | meaning |
|---|---|---|
| `--scenes` | `../dataset/refined_data/scenes` | ground-truth scenes |
| `--pred` | required | folder of `<stem>_polys.json` from step E |
| `--stage1` | required | folder of `<stem>_masks.npz`; used to build the v1 baseline row |
| `--val-width` | 725 | score only the val band. Must match the tiler's |
| `--whole-scene` | off | score everything. Mixes in stage-1 training pixels — inspection only |
| `--match-iou` | 0.5 | prediction-to-GT matching threshold |

Output: three rows scored identically — the **v1 rule-based baseline**, the
**v2 model**, and **GT itself** as a sanity check — with corner recall,
precision and F1 at 2 px and 4 px, vertices per polygon, `v/GT`, and polygon IoU.

---

## 4.8 Useful extras

**Verify the install** — no GPU, no data, no checkpoint:

```bash
cd dinov3_poly && python selftest.py
```

**Check the labels** — writes `gt_overlay.png` in every scene folder:

```bash
cd dataset/refined_data && python visualize_gt.py --max-size 1500
```

**Price mask quality** — bins matched instances by their own mask IoU and
reports corner F1 per bin, so "improve the masks" becomes a number:

```bash
cd dinov3_poly && python curve.py --pred ./preds/v1 --gt <annotations.json>
```

**The labelling tool** — open `labeler/labeler.html` in a browser. No server.

---

## 4.9 A complete run from scratch

```bash
conda activate bldseg
cd /path/to/building_seg

# A. tiles
cd dataset/refined_data
python tile_to_coco_multi_rot.py --img-dir scenes --ann-dir scenes \
    --out data_stride128_rot --tile 512 --stride 128 --rot 0 15 30 45 \
    --rot-val --val-width 725

# B. stage 1                                       (~5 hours, 20 epochs)
cd ../../dinov3_v2
python train_dinov3_mask2former.py --data-root ../dataset/refined_data/data_stride128_rot \
    --out ./runs/run7 --image-size 1024 --num-queries 200 --batch-size 4 \
    --epochs 20 --lr 1e-4 --taps auto --crowd instance --unfreeze-last 2 \
    --backbone-lr-mult 0.1 --boundary-weight 5.0 --collision-weight 3.0 \
    --crowd-weight 3.0 --maskiou-weight 1.0 --seed 0

# C. stage-1 predictions on the scenes             (~1 min per scene)
python infer.py --ckpt ./runs/run7 --ckpt-tag best \
    --images ../dataset/refined_data/scenes/daegu_crop1/daegu_crop1.png \
    --out ../dinov3_poly/stage1_preds --overlap 256 --threshold 0.05 --save-masks

# D. stage 2                                       (~35 min, 60 epochs)
cd ../dinov3_poly
python train.py --out ./runs/v1

# E. polygons
python infer.py --ckpt ./runs/v1/best.pth \
    --images ../dataset/refined_data/scenes/daegu_crop1/daegu_crop1.png \
    --stage1 ./stage1_preds --out ./preds/v1 --viz --viz-scale 0.5

# F. score
python bench.py --pred ./preds/v1 --stage1 ./stage1_preds
```
