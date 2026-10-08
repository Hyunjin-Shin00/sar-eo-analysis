# dinov3_poly

Polygons from a **vertex head**, not from post-processing a mask.

Stage 1 (`dinov3_v2`, unchanged and frozen) finds buildings and returns boxes.
Stage 2 — this project — crops each building at native resolution and predicts
its **own** mask, its **corner heatmap**, and **sub-pixel offsets** together.
The polygon is built from the predicted corners; the mask only supplies the
cyclic order.

That split is the whole point. In the rule-based pipeline the mask *is* the
polygon — every boundary wobble becomes a vertex. Here the mask decides
*which order* corners go in, a far weaker dependence than deciding *where they
are*.

---

## The numbers this design is built on

Measured on `dataset/refined_data/scenes` (10 scenes, 6425 refined polygons):

| | value |
|---|---|
| vertices per polygon | median **4**, p90 6 |
| edge length | median **35.2 px**, p5 9.0, p1 3.8 |
| edges under 2 px | **0.6%** |
| building max side | median **65 px**, p10 26, p90 133 |
| nearest vertex of *another* building | median 23.7 px, p10 3.0, 5.8% under 2 px |
| convex | 73.6% |
| vertex angles within 5° of 90° | **92.3%** |

Two things follow immediately.

**The corners are well separated.** Only 0.6% of edges are under 2 px and
cross-building vertices sit a median 23.7 px apart. A heatmap does not need
heroic resolution to keep them apart — the earlier failure was never a
representation problem.

**The buildings are near-rectilinear quadrilaterals.** 92.3% of turns are
square to within 5°. Four well-placed corners describe most of this dataset.
That is a strong prior and it says the task is learnable; it is deliberately
*not* baked in as a snapping rule (see *Rejected*).

---

## Why region-focused, and not a head on the whole tile

This is the one architectural decision that matters, and it is decided by cell
size, not by preference.

A head bolted onto the tile-level pixel decoder inherits its resolution: at 1/4
of a 1024 input on a 512 tile, **one cell is 2.0 tile px, always**, regardless
of how large the building is. A crop normalises instead — every building is
resized into the same grid, so small buildings stop being starved.

Cells spanned by a building's long side, output stride 2 on a 256 crop:

| building | whole tile (1/4) | **ROI crop** |
|---|---|---|
| p10, 26 px | 13 cells | **60** |
| median, 65 px | 33 cells | **76** |
| p90, 133 px | 67 cells | **91** |

Cell size in scene pixels goes from a flat 2.0 px to **0.43 / 0.85 / 1.45 px**.
Against a 2 px accuracy target that is the difference between "land in the one
correct cell" and "land within three".

The equalisation matters more than the peak: p10 buildings gain 4.6×, and small
buildings are exactly where masks are worst.

### Crop framing

SAMPolyBuild tiers the crop by size (`m*3` / `m*1.8` / `m*1.2`), which is right
in spirit — small buildings need proportionally more context because the
surroundings are what disambiguate them — but the thresholds make it
discontinuous: at their cut a 119 px building gets a 214 px crop and a 120 px
building gets 156. Two near-identical buildings land at very different
magnifications.

Same idea, made smooth and monotone:

```
crop = m * (1.25 + 1.25 * exp(-m / 60))
```

`m` is the box's long side. 26 px → 54, 65 px → 109, 133 px → 185. Magnification
falls from 4.7× to 1.4× with no jump anywhere.

---

## Input: the box, not the mask

The crop carries **RGB (3 ch) + a filled box rectangle (1 ch)**.

The box channel exists only to say *which* building is the subject — at a p10
cross-building vertex distance of 3.0 px the crop always contains neighbours,
and without it the head cannot know whose corners to emit.

**The stage-1 segmentation mask is deliberately not an input.** Feeding it back
would re-import exactly the dependence this project exists to remove: a blobby
mask would bias the corners it is supposed to correct. A box is far more robust
than a boundary — it survives a mask that is locally wrong — and stage 2 then
predicts its own mask from pixels.

This also means the contour used for ordering is **stage 2's refined mask at
0.43–1.45 px per cell**, not stage 1's at 2 px.

---

## Heads

All four share one encoder-decoder and are supervised together, SAMPolyBuild's
arrangement:

| head | ch | loss | why |
|---|---|---|---|
| mask | 1 | BCE + Dice, `pos_weight` 2 | ordering, and a refined boundary |
| vertex heatmap | 1 | **BCE + Dice** | corner location |
| vertex offset | 2 | sigmoid + L1, masked by the heatmap | sub-cell placement |
| edge | 1 | BCE + Dice, `pos_weight` 2 | sharpens the boundary the ordering walks |

**Dice on the vertex map, not CornerNet focal.** Penalty-reduced focal
multiplies the negative term by `(1-t)^β`, which *by construction* forgives
activation near a true peak — precisely where spurious duplicate corners
appear. Dice scores the predicted blob set against the target blob set, so a
false peak costs overlap directly. SAMPolyBuild uses `BCEDiceLoss` here and
this is the most likely reason its vertex sets stay sparse.

Gaussian targets use `sigma = 1` cell over a 3×3 window (SAMPolyBuild's value).
At stride 2 that is a blob 2–4 scene px wide depending on building size — tight
enough that two real corners never merge, given a median 35 px edge.

---

## Connection

1. Threshold + 3×3 max-pool NMS on the vertex map, add offsets → candidate points
2. Walk the **stage-2 mask** contour, snapping to nearby candidates → cyclic order
3. Fall back to angular sort about the centroid when the contour walk fails —
   safe here because 73.6% of these polygons are convex
4. Fall back to `dinov3_v2/polygonize.regularize` only on catastrophe

The gate distance scales with the building, since a fixed pixel budget means
something different for a 26 px shed and a 133 px shed.

---

## Rejected, and why

**A vertex head on the tile-level decoder.** It reads the same tensor the mask
head reads, so it cannot see a boundary the mask features do not already
encode, and it gets 13 cells across a p10 building. Measured on the previous
attempt: corner precision 12.9%, F1 *below* the rule-based baseline.

**Snapping corners to 90°.** 92.3% of angles are already square, so a snap
would look excellent and teach nothing — and it is the same class of rule-based
post-processing that motivated this rewrite. The prior is available as an
*auxiliary orientation head* (predict the instance's dominant angle, supervise
it, let the encoder use it) if the free-form corners turn out biased. Not built
until measured.

**Sequence models** (PolyFormer-style autoregressive vertices, PolyWorld's GNN
permutation). Strictly more expressive, and unnecessary at a median of 4
vertices per polygon with 35 px edges. Revisit only if ordering, not placement,
turns out to be the error source.

**Stage 1 as a mere box detector — is DINOv3 wasted here?** Partly, and it is
worth being honest about. Detection in this fabric is the genuinely hard part:
stage 1's recall is a hard ceiling on everything downstream, and its AP is
0.38, so detection is nowhere near solved. Its *masks* also earn their keep
outside this project — tiled de-duplication uses mask IoU and containment
between buildings a median 1.9 px apart, where box NMS would merge them. What
this project discards is only the mask's role as the polygon's *geometry*.
A cheaper detector would still have to solve detection, de-duplication and
border rejection first.

**End-to-end joint training with stage 1.** Stage 1 is at mask IoU 0.825 after
six runs and its epochs cost about 15 minutes. Stage 2 is small and its crops
are cached, so its epochs cost minutes — that iteration speed is worth more
right now than the coupling. Joint fine-tuning stays available later.

---

## Evaluation, fixed before any training

Reported from the first run, both directions, at 2 px **and** 4 px:

- **recall** — GT vertex → nearest predicted
- **precision** — predicted vertex → nearest GT
- **F1**, the headline
- **v/GT** — vertices emitted per GT vertex
- polygon-vs-GT IoU, and mask IoU against stage 1

Recall alone is not a metric here: it cannot fall as vertex count rises, so a
head that emits twice as many corners scores better while being worse. The
baseline to beat is `polygonize.regularize()` on stage 1's own masks — the
current pipeline, scored identically.

---

## Split

Stage 2 reuses stage 1's split exactly: the val band is the rightmost
`val_width` (725 px) of each scene, so a building with box centre
`x >= W - 725` is val. Anything else leaks stage-1 training pixels into stage-2
validation.

---

## Layout

```
targets.py    crop framing, heatmap/offset/edge rendering, decode, D4 on points
data.py        scenes -> per-instance crops, jitter, D4 + photometric augment
model.py       encoder-decoder + the four heads
losses.py      BCE+Dice, masked sigmoid-L1
connect.py     candidates + mask -> ordered polygon
train.py       selection on corner F1 at 2 scene px
infer.py       stage-1 boxes (cached *_masks.npz) -> crops -> polygons
bench.py       the metric above, against the rule-based baseline
selftest.py    26 checks, no data and no GPU

There is no prepare step: crops come straight from the scenes at load time, so
crop jitter stays live rather than being frozen into a cache.

    python selftest.py
    python train.py --out ./runs/v1
    python infer.py --ckpt ./runs/v1/best.pth         --images ../dataset/refined_data/scenes/daegu_crop1/daegu_crop1.png         --stage1 <folder with daegu_crop1_masks.npz> --out ./preds/v1
    python bench.py --pred ./preds/v1 --stage1 <same folder>
```

---

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
python bench.py --pred <값> --stage1 <값>
```
End-to-end scoring against the rule-based pipeline this replaces. Three rows, identically scored: baseline polygonize.regularize() on stage 1's masks 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--scenes` |  | `../dataset/refined_data/scenes` |  |
| `--pred` | ● |  | folder of *_polys.json |
| `--stage1` | ● |  | folder of *_masks.npz |
| `--val-width` |  | `725` |  |
| `--whole-scene` |  |  | score everything, not just the val band. Mixes in stage-1 training pix |
| `--match-iou` |  | `0.5` |  |

```bash
python infer.py --ckpt <값> --images <값> --stage1 <값> --out <값>
```
Stage 1 boxes -> stage 2 crops -> polygons. TAKES STAGE 1's `_masks.npz` BY DEFAULT rather than re-running it. Detection is unchanged by this project,

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--ckpt` | ● |  | stage-2 checkpoint (.pth) |
| `--images` | ● |  | scene image, or a folder |
| `--stage1` | ● |  | folder of dinov3_v2 <stem>_masks.npz |
| `--out` | ● |  |  |
| `--batch` |  | `64` |  |
| `--vertex-thr` |  | `0.3` |  |
| `--merge` |  | `1.0` |  |
| `--mask-thr` |  | `0.5` |  |
| `--max-dist-frac` |  | `0.08` | candidate-to-contour gate, as a fraction of the mask's long side. THE  |
| `--no-fit-edges` |  |  | disable wall refitting. ON by default: the head picks how many corners |
| `--prune-width` |  | `0.06` | cut tentacles and bays out of the mask contour before using it as a gu |
| `--refine-tol` |  | `0.06` | let the mask contour insert a corner wherever the vertex polygon depar |
| `--max-add` |  | `4` | cap on inserted corners per polygon; bounds the damage when a mask is  |
| `--min-turn` |  | `10.0` | drop vertices whose turn is below this many degrees (a straight wall)  |
| `--angle-tol` |  | `0` | drop vertices whose direction disagrees with the contour by more than  |
| `--guard-min-iou` |  | `0.35` |  |
| `--min-area` |  | `64` |  |
| `--viz` |  |  | write <stem>_overlay.png: raw image | polygons, coloured by source (gr |
| `--viz-scale` |  | `1.0` | downscale the panels AFTER drawing, so thin outlines survive instead o |
| `--viz-alpha` |  | `0.35` |  |
| `--debug-crops` |  | `0` | dump <stem>_debug.png: for the first N instances, crop | mask + guide  |
| `--viz-dot` |  | `2` | vertex marker radius; 0 hides them |

```bash
python train.py --out <값>
```
Train the stage-2 polygon network. SELECTION IS ON CORNER F1 AT 2 SCENE PX, not on val loss and not on recall. Not loss: it is a weighted sum of four 

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--data-root` |  | `../dataset/refined_data/scenes` |  |
| `--out` | ● |  |  |
| `--epochs` |  | `60` |  |
| `--batch-size` |  | `32` |  |
| `--lr` |  | `0.0003` |  |
| `--workers` |  | `4` |  |
| `--crop` |  | `256` |  |
| `--out-size` |  | `128` |  |
| `--val-width` |  | `725` | MUST match the tiler's, or stage-1 training pixels leak into stage-2 v |
| `--encoder` |  | `resnet18` |  |
| `--no-pretrained` |  |  |  |
| `--dim` |  | `128` |  |
| `--no-edge` |  |  |  |
| `--w-mask` |  | `1.0` |  |
| `--w-vmap` |  | `1.0` |  |
| `--w-voff` |  | `1.0` |  |
| `--w-edge` |  | `1.0` |  |
| `--vertex-thr` |  | `0.3` |  |
| `--merge` |  | `1.0` | collapse decoded peaks closer than this many cells |
| `--eval-ckpt` |  |  | load this checkpoint, run validation once, print the metrics and exit. |
| `--seed` |  | `0` |  |
