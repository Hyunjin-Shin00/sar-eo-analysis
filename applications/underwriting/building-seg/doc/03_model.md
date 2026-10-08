# 3. Model architecture

The goal is a **vector polygon** for every building — not a pixel mask. That is
two different problems, so the system is two stages.

```
            scene image (e.g. 2364 × 3019)
                        │
   STAGE 1  ────────────┴──────────────────────────────
   dinov3_v2 : DINOv3 + Mask2Former, tiled
   "which buildings are there, and roughly where"
                        │
                        │  instance masks + boxes + scores
                        │
   STAGE 2  ────────────┴──────────────────────────────
   dinov3_poly : per-building crop, four heads
   "exactly where are this building's corners"
                        │
                        ▼
              one polygon per building
```

Stage 1 solves **detection**. Stage 2 solves **geometry**. They are trained
separately and communicate through boxes.

---

## 3.1 Stage 1 — instance segmentation

**Job:** find every building in a large scene and return a mask, a box and a
confidence for each.

### Architecture

```
tile 512×512
   │  resized to 1024×1024
   ▼
DINOv3 ViT-L/16                     patch 16 → a 64×64 token grid
   │  features tapped at blocks 6, 12, 18, 24
   ▼
adapter pyramid                     four levels at strides 4 / 8 / 16 / 32
   │                                (the shape a Swin backbone would emit)
   ▼
Mask2Former head                    200 object queries
   │                                warm-started from COCO instance weights
   ├──► class logits per query
   ├──► mask logits per query        at 1/4 input = 256×256
   └──► mask-IoU head                each query scores its own mask
```

**Why a ViT with an adapter.** DINOv3 is a strong self-supervised backbone but
emits a single-scale token grid, while Mask2Former's pixel decoder expects a
four-level convolutional pyramid. The adapter taps four depths of the
transformer and reshapes them into that pyramid, which lets a COCO-pretrained
segmentation head be reused unchanged instead of trained from scratch.

**Parameter budget** (330.01 M total):

| part | params | trained? |
|---|---|---|
| DINOv3 backbone | 300 M | frozen, except the last 2 blocks (25.19 M) |
| adapter pyramid | 6.83 M | yes |
| Mask2Former head | 20.06 M | yes |
| mask-IoU head | 0.20 M | yes |
| **trainable** | **52.08 M** | |

Freezing most of the backbone is what makes this trainable on one GPU. The last
two blocks are unfrozen at a tenth of the base learning rate so the features can
adapt to overhead imagery without losing what DINOv3 learned.

### Loss

Mask2Former's own Hungarian-matched classification + mask + dice loss, plus
four terms added for this dataset:

| term | weight | what it does |
|---|---|---|
| boundary | 5.0 | extra supervision in a 3-px band around each edge — sharpens boundaries, which plain dice ignores |
| collision | 3.0 | penalises two queries claiming the same pixels — buildings here sit a median 1.9 px apart and merge easily |
| crowd | 3.0 | handles tile-clipped buildings so edge instances are not taught as background |
| mask-IoU | 1.0 | trains the head that predicts each mask's own quality, used for ranking at inference |

### Inference on a full scene

A scene is far larger than the 512 tile the model trained on, so it is tiled
with overlap, and three things happen that a naive stitcher would get wrong:

1. **Border rejection.** With overlap ≥ the largest building, every building is
   whole in *some* tile. So a mask touching an **interior** tile edge is a
   truncated duplicate and is dropped. A mask touching the real scene boundary
   is kept — that one is genuinely clipped.
2. **De-duplication** by mask IoU *and* containment. Box-level NMS is not enough
   at 1.9 px spacing; it merges neighbours.
3. **Cleaning** — hole filling, morphological open/close, splitting disconnected
   components, dropping slivers, then a second de-duplication pass.

### Significance

Stage 1's **recall is a hard ceiling** on the entire system: a building it
misses is invisible to stage 2 forever. Its masks also do work that no cheaper
detector would do for free — the de-duplication above needs masks, not boxes.

What stage 1 does **not** provide any more is the polygon's geometry. That is
the subject of the rest of this document.

---

## 3.2 The polygon problem, and three answers

A mask is a set of pixels. A polygon is an ordered list of corners. Turning one
into the other is where the accuracy is won or lost.

### Baseline — SAMPolyBuild (reference implementation)

Published work that adapts the Segment Anything Model for polygonal building
extraction. Three ideas, and this project borrows the shape of all three:

1. A **vertex head** on the mask decoder, so corners come out of the same
   forward pass as the mask.
2. **Mask-guided vertex connection** — the corner heatmap gives an unordered
   point set, and the mask contour supplies the cyclic order.
3. A **region-focused** input: each building is cropped around its box prompt
   and resized, so a small building is not starved of resolution.

It is checked into `SAMPolyBuild/` for reference and is not part of the runtime
pipeline. Where this project deviates from it, the deviation is noted below.

### Version 1 — rule-based polygonization

`dinov3_v2/polygonize.py`. Trace the mask contour, simplify it
(Douglas–Peucker), fit rectilinear edges, snap near-right angles.

*Structural limitation:* **the mask is the polygon.** Every boundary wobble
becomes a vertex, so a blobby mask produces a blobby polygon with far too many
corners — and no amount of tuning fixes that, because the information about
where a corner *really* is was never in the mask.

Still used, in one place only: as a last-resort fallback when the stage-2 result
fails a sanity check.

### Version 2 — vertex head *(current)*

`dinov3_poly/`. A second network that looks at the building's own pixels and
**predicts the corners directly**, using the mask only to put them in order.

The key change is what the mask is responsible for. In v1 the mask decides
*where the corners are*. In v2 it decides *what order they go in* — a far
weaker dependence, and the one thing a corner detector genuinely cannot do for
itself.

---

## 3.3 Stage 2 — the vertex head *(current version)*

**Job:** given one building's box, output its polygon.

### Input: a normalised crop

Each building is cropped from the **original scene** — not from stage 1's
output — with a size-dependent margin:

```
crop_side = m · (1.25 + 1.25 · e^(−m/60))        m = the box's long side
```

26 px → 54, 65 px → 109, 133 px → 185. Small buildings get proportionally more
context, because the surroundings are what separate them from neighbours 3 px
away; large ones get a tight frame so resolution is not wasted. The formula is
smooth, unlike SAMPolyBuild's step-tiered version, where two nearly identical
buildings can land at very different magnifications.

The crop is resized to **256×256**, and the network output is at **stride 2**
(128×128 cells). That normalisation is the point:

| building | cells across it, tile-level head | **cells across it, ROI crop** |
|---|---|---|
| p10, 26 px | 13 | **60** |
| median, 65 px | 33 | **76** |
| p90, 133 px | 67 | **91** |

A cell goes from a flat 2.0 scene px to 0.43–1.45 px, and — more importantly —
every building gets a comparable budget. Small buildings gain 4.6×, and small
buildings are exactly where masks are worst.

**Four input channels: RGB + a filled box rectangle.** The box channel says
*which* building is the subject, since the crop always contains neighbours.
Stage 1's segmentation mask is deliberately **not** an input — feeding it back
would let the network copy the boundary it is supposed to be correcting.

### Network

```
(4, 256, 256)
   │
ResNet-18 encoder (ImageNet weights, stem widened to 4 channels)
   │  strides 2 / 4 / 8 / 16 / 32
   ▼
top-down decoder with lateral 1×1 convolutions, terminating at stride 2
   │
   ├──► mask       1 ch   (128, 128)
   ├──► vertex     1 ch   corner heatmap
   ├──► offset     2 ch   sub-cell position within a cell
   └──► edge       1 ch   the polygon outline
```

A compact convolutional network, not a transformer. The whole point of the crop
is fine spatial resolution, and a patch-16 ViT on a 256 crop would give 16
tokens across — coarser than the tile-level head it replaces. Corner placement
needs stride, and convolutions are where stride is cheap.

### The four heads

| head | loss | role |
|---|---|---|
| mask | BCE + Dice, `pos_weight` 2 | supplies the ordering contour, and is a **refinement** — predicted at 2–5× stage 1's effective resolution |
| vertex heatmap | **BCE + Dice** | where the corners are |
| offset | sigmoid + L1, masked to corner cells | sub-cell placement |
| edge | BCE + Dice, `pos_weight` 2 | sharpens the boundary the ordering walks |

**Dice on the vertex map rather than a focal loss.** Penalty-reduced focal loss
weights the negative term by `(1−t)^β`, which by construction *forgives*
activation near a true peak — precisely where duplicate corners appear. Dice
scores the predicted blob set against the target set as a whole, so a spurious
peak costs overlap and cannot be discounted for being close to a real corner.
Keeping the vertex count honest is what the whole evaluation turns on.

Corner targets are Gaussians with σ = 1 cell over a 3×3 window, combined by
maximum so two nearby corners stay two peaks. The peak cell is written as
exactly 1.0, and the offset stores the remainder after a **floor** — which is
why the offset head uses a sigmoid, since the target genuinely lives in [0, 1).

### Training

Stage 2 trains on the **scenes**, not the tiles, using GT boxes jittered to
imitate a detector. The jitter range is measured from real stage-1 boxes: scale
0.88–1.30 and centre shift ±12%, which covers the p90 framing error with margin.
Augmentation is D4 (the eight square symmetries) plus photometric jitter; the
rotation diversity that matters is already baked into the crop framing.

Checkpoints are selected on **corner F1 at 2 scene pixels**, not on validation
loss and not on recall. Recall alone cannot fall as a model emits more vertices,
so it rewards a model that floods the image with corners.

---

## 3.4 From corners to a polygon

The vertex head gives an unordered point set. Six steps turn it into a ring, in
this order:

```
predicted mask ──► prune_thin ──────────────► guide contour
                                                    │
predicted corners ──► order_by_contour ◄────────────┤
                              │                     │
                              ▼                     │
                    refine_against_contour ◄────────┤
                              │                     │
                              ▼                     │
                          fit_edges ◄───────────────┘
                              │
                              ▼
                       simplify_ring
                              │
                              ▼
                     is_simple / make_simple  ──►  polygon
```

**1. `prune_thin` — clean the guide.** A bad mask can grow a thin tentacle or a
narrow bay. These are *thin*, not small, so simplification cannot remove them:
a 15-px tentacle is a large deviation that survives any Douglas–Peucker epsilon
which preserves real notches. What identifies a thin feature is that the contour
**leaves and returns to nearly the same place**, and that is what is detected
and cut.

**2. `order_by_contour` — order the corners.** Each corner is projected onto the
mask contour and they are sorted by projection position. Corners further than a
gate (8% of the building's long side) from the contour are discarded — that gate
is the single most important parameter in the connection stage.

*Not* by walking the contour and taking first appearances: that drops any corner
which is never the nearest neighbour of some contour point, and splices spurious
ones into the middle of the ring.

**3. `refine_against_contour` — recover missed corners.** Douglas–Peucker
*seeded with the detected corners*. Between two detected corners lies a known
arc of the contour; if that arc bows away from the straight edge by more than a
tolerance, the point of maximum deviation is a corner the head missed, so it is
inserted. This is what stops a perfectly-masked L-shaped building coming out as
a quadrilateral. When the head is right, it changes nothing.

**4. `fit_edges` — put the corners in the right place.** Each *wall* is refit to
the mask contour by total least squares, and corners are recomputed as the
intersections of adjacent fitted walls.

This is the division of labour the whole design rests on: **the head knows the
topology** — how many corners, and which stretches of boundary are one wall,
which a mask can never tell you — and **the mask knows where each wall sits**,
far better than a heatmap peak does, because a line through fifty contour points
averages the wobble away while a peak is one guess at one pixel.

**5. `simplify_ring` — remove redundant and folded vertices.** Drops corners on
a straight run (turn < 10°) and corners where the ring folds back (turn 150–210°).
Both thresholds come from the label statistics: 92.3% of real turns are within
5° of a right angle, and only 0.064% exceed 150°.

**6. `is_simple` / `make_simple` — validity.** A self-intersecting ring is
invalid geometry for anything downstream. If one occurs, the fewest vertices
needed to make it valid are dropped, preserving the contour ordering of the
rest. Below a floor of polygon-vs-mask IoU 0.35 the whole thing is discarded and
v1's rule-based polygonizer is used instead — a catastrophe guard, nothing more.

Every polygon carries **per-vertex provenance**: whether each corner came from
the head or was supplied by the mask. An unexpected corner is one or the other,
and they need opposite fixes.

---

## 3.5 Why the two stages are split

| | stage 1 | stage 2 |
|---|---|---|
| sees | a 512 tile of the scene | one building, magnified 1.4–4.7× |
| decides | which buildings exist | where this building's corners are |
| trains on | tiles with rotation augmentation | scenes, cropped per building |
| epoch cost | ~15 min | ~35 s |
| params | 330 M (52 M trained) | 12 M |

The asymmetry in epoch cost is the practical argument. Stage 1 reached its mask
quality over six runs and its epochs are expensive; stage 2's are cheap, so
polygon experiments can iterate in minutes rather than hours. Keeping them
separate also means stage 1's masks are never at risk from a stage-2 change.

The cost of the split is that stage 2 inherits stage 1's framing. Most of the
time that is harmless — the median box is off by 1.6 px with a long-side ratio
of 1.000 — but roughly 15% of boxes carry a structural error (a merge or a
split) that no stage-2 setting repairs.
