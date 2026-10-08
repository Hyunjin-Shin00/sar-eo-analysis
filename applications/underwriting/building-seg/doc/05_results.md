# v1 polygonize vs v2 vertex head — temporary

Same detector (run7) for both, so every difference below is polygonisation.
Reproduce: `python evaluate_all.py` (tiles) and `python eval_scenes.py` (scenes).

---

## Metrics

| metric | what it means | better |
|---|---|---|
| **AP** | COCO instance-segmentation average precision, polygons rasterised to masks, averaged over IoU 0.50:0.95 | higher |
| **AP50** | the same at a single loose IoU of 0.50 — effectively "was the building found", not "is the shape right" | higher |
| **AP75** | at a strict IoU of 0.75 — sensitive to shape quality | higher |
| **recall** | share of GT buildings matched by some prediction at IoU 0.5 | higher |
| **IoU** | mean polygon-vs-GT intersection over union, on matched pairs | higher |
| **C-IoU** | *Complexity-aware IoU* (PolyWorld, CVPR 2022): `IoU × (1 − \|N_pred − N_gt\| / (N_pred + N_gt))`. Penalises getting the vertex count wrong, which plain IoU and AP ignore | higher |
| **verts** | mean vertices per predicted polygon (GT is 4.83) | closer to GT |
| **v/GT** | predicted vertices per GT vertex, per instance | closer to 1.0 |
| **F1@2px** | corner F1 at 2 pixels: harmonic mean of *recall* (GT corner has a prediction within 2 px) and *precision* (predicted corner has a GT within 2 px). Precision matters — recall alone cannot fall as a model emits more corners | higher |
| **F1@4px** | the same at 4 px | higher |
| **PoLiS** | symmetric mean distance from each polygon's vertices to the other's boundary, in px (Avbelj et al. 2015) | **lower** |

All geometry metrics are computed on matched pairs only and are independent of
detection score.

---

## 1. Val tiles — the held-out benchmark

83 non-overlapping 512×512 tiles, 2609 instances.

| | AP | AP50 | AP75 | recall | IoU | C-IoU | verts | v/GT | F1@2px | F1@4px | PoLiS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v1 polygonize | 0.364 | 0.615 | 0.384 | 0.698 | 0.8153 | 0.7548 | 5.08 | 1.02 | 26.9% | 60.3% | 3.044 |
| **v2 vertex head** | **0.378** | **0.622** | **0.400** | **0.703** | **0.8263** | **0.7805** | **4.83** | **0.97** | **40.6%** | **69.8%** | **2.863** |

---

## 2. Full scenes — whole image

4 scenes (changwon_crop2, daegu_crop2, gumi_crop2, namdong_crop2), 2308 instances.

| | AP | AP50 | recall | IoU | C-IoU | verts | v/GT | F1@2px | PoLiS |
|---|---|---|---|---|---|---|---|---|---|
| v1 polygonize | 0.383 | **0.643** | 0.694 | 0.8153 | 0.7558 | 5.10 | 1.02 | 29.2% | 2.85 |
| **v2 vertex head** | **0.406** | 0.637 | **0.696** | **0.8351** | **0.7980** | **4.84** | **0.97** | **46.3%** | **2.46** |

> **These scenes include the training band** — stage 1 and stage 2 both saw most
> of these pixels. 

---

## 3. Full scenes — val band only

The rightmost 725 px of the same 4 scenes, which neither stage trained on. 778
instances.

| | AP | AP50 | recall | IoU | C-IoU | verts | v/GT | F1@2px | PoLiS |
|---|---|---|---|---|---|---|---|---|---|
| v1 polygonize | 0.337 | **0.586** | 0.656 | 0.8067 | 0.7428 | 5.11 | 1.02 | 26.5% | 3.09 |
| **v2 vertex head** | **0.357** | 0.579 | **0.657** | **0.8253** | **0.7803** | **4.87** | 0.98 | **42.1%** | **2.75** |

---

## Observations

**v2 wins in all three settings, and by a consistent margin.** Corner F1@2px
improves by +13.7 pts on tiles, +17.1 on whole scenes, +15.6 on the scene val
band. Nothing about the result depends on whether the input is a tile or a
whole scene.

**AP50 is a tie or slightly against v2** (0.637 vs 0.643 whole scene, 0.579 vs
0.586 val band) while AP and AP75 favour v2. Both share a detector, so AP50 —
which is close to a detection measure — should be equal, and it is. v2's gain
appears at strict IoU, which is where shape quality lives.

**The tile and scene numbers agree once contamination is removed.** Val tiles
give v2 AP 0.378; the scene val band gives 0.357. The whole-scene 0.406 is
inflated by training pixels and should not be quoted.

**Every geometry metric moves the same way**: higher IoU, higher C-IoU, fewer
and more faithful vertices, better corners, lower PoLiS. Corner accuracy
improved while vertex count went *down* — those normally trade against each
other.

**Recall is identical** (0.696 vs 0.694, 0.657 vs 0.656), confirming the shared
detector and that nothing in stage 2 is dropping instances.

### One caveat

On val tiles v2 double-claims 0.73% of its painted area against v1's 0.02% — v1
de-duplicates before polygonising, while v2 builds each polygon in its own crop
with nothing reconciling neighbours. Small in absolute terms, but it is a
regression, and it is not visible in any metric above.
