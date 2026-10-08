# dinov3_v2 — building instance segmentation → polygons

DINOv3 (frozen) + Mask2Former + a polygon vertex refiner. Fork of `../dinov3`
with five changes, each sized against a **measured** v1 failure mode.

- **[Pipeline](#pipeline)** — every command, in order, with all arguments
- **[Why each change exists](#why-each-change-exists)** — the measurements
- **[Tuning order](#tuning-order)** / **[Memory](#memory)** / **[Reproducing v1](#reproducing-v1)**

### Legend for the argument tables

| mark | meaning |
|---|---|
| **SET** | you must pass this, or the run is wrong |
| **check** | has a default, but the default is probably not what you want |
| default | leave it alone |
| *ablation* | only to answer a specific question; ignore for normal runs |

### Environment

Needs a `transformers` new enough to expose the `dinov3_vit` architecture.
Note that no conda env on this machine currently has one — the `huy` env is at
4.37.2, which loads Mask2Former but **not** DINOv3. `vertex.py`, `eval.py` and
`polygonize.py` run fine there; `train_dinov3_mask2former.py` and `infer.py`
need the newer env.

---

# Pipeline

```
 0  tile scenes -> COCO tiles                tile_to_coco_multi.py
 1  self-tests (no GPU, no weights)          selftest.py / vertex.py selftest
 2  train the segmenter                      train_dinov3_mask2former.py
 3  predict masks on val                     infer.py
 4  score masks                              eval.py
 5  predict masks on train                   infer.py        (for stage 7)
 6  masks -> seed polygons                   polygonize.py
 7  train the vertex refiner                 vertex.py train
 8  score corner accuracy                    vertex.py bench
 9  refine polygons                          vertex.py apply
10  production run on full scenes            3 -> 6 -> 9
```

Stages 5–9 are only needed if your deliverable is **vector polygons**. If you
ship raster masks, stop after stage 4.

---

## Stage 0 — tile the scenes

Already done for `../dataset/new_data/data_stride256`. Only re-run if you change
the tiling or add scenes.

```bash
python ../dataset/new_data/tile_to_coco_multi.py --img-dir ../dataset/scenes --ann-dir ../dataset/labels --out ../dataset/new_data/data_stride256 --tile 512 --stride 256 --val-frac 0.2 --min-keep 0.4
```

| arg | default | recommended | notes |
|---|---|---|---|
| `--img-dir` | — | **SET** | folder of scene images, paired to `--ann-dir` by filename stem |
| `--ann-dir` | `None` → falls back to `--img-dir` | **SET** | folder of polygon JSONs |
| `--src IMG JSON` | — | *alt* | repeatable, instead of the two above, when names don't pair |
| `--out` | — | **SET** | writes `train/`, `val/`, `dataset_info.json` |
| `--tile` | `512` | `512` | must match `--image-size` intent downstream |
| `--stride` | `384` | **`256`** | 256 gives 50% overlap and ~300 tiles from 7 scenes |
| `--val-frac` | `0.2` | `0.2` | fraction of each scene's **width** held out. Column-band split, so train/val never share pixels — this is why the val numbers here are trustworthy |
| `--min-keep` | `0.4` | `0.4` | drop a tile-clipped building if less than this survives |
| `--min-area` | `64` | default | drop polygons smaller than this after clipping |
| `--drop-empty` | off | **leave off** | empty tiles are useful negatives |
| `--ext` | `.png` | default | |

The existing split is 248 train / 52 val tiles, 6546 / 1515 non-crowd instances.

---

## Stage 1 — self-tests

Run these **before** spending GPU time. Both are CPU-only, take seconds, and
need no weights — `selftest.py` stubs the DINOv3 backbone entirely. They exist
to catch what is expensive to discover eight hours into a run: a loss that is
silently always zero, an off-by-one tap index, a head whose output leaves
[0, 1], the empty-tile path.

```bash
python selftest.py
```
```bash
python vertex.py selftest
```

No arguments. Both must print `all checks passed`. Between them they caught
five real bugs during development, listed in [Why each change exists](#why-each-change-exists).

---

## Stage 2 — train the segmenter

```bash
python train_dinov3_mask2former.py --data-root ../dataset/new_data/data_stride256 --image-size 1024 --num-queries 200 --batch-size 4 --epochs 60 --lr 1e-4 --taps auto --crowd instance --maskiou-weight 1.0 --collision-weight 1.0 --boundary-weight 2.0 --crowd-weight 3.0 --p-mosaic 0.3 --out ./runs/v2
```

### Data and schedule

| arg | default | recommended | notes |
|---|---|---|---|
| `--data-root` | `./data` | **SET** | the dir containing `train/` and `val/` |
| `--image-size` | `512` | **`1024`** | tiles are 512; upsampling 2× before a patch-16 ViT gives a 64×64 token grid = **effective stride 8** on the tile instead of 16. This is what v1 used and it matters for small buildings |
| `--num-queries` | `None` → keeps the checkpoint's 100 | **`200`** | Mask2Former matches at most this many GT instances per tile and **silently drops the surplus**. Mosaic reaches 80–110 instances. Use ~2× your max |
| `--batch-size` | `2` | `4` | at 1024 input with a ViT-L this is about what fits |
| `--epochs` | `60` | `60` | v1's best was epoch 52 |
| `--lr` | `1e-4` | `1e-4` | head 1×, adapter and IoU head 10×, backbone `--backbone-lr-mult`× |
| `--out` | `./runs/dinov3_m2f` | **SET** | writes `best_ep<N>.pth`, `last_ep<N>.pth`, `run_config.json`, `loss_log.csv`. Pass this **directory** to `infer.py --ckpt`. **Training WIPES it first** — see below |
| `--seed` | `0` | **same on both sides of an A/B** | seeds python/numpy/torch *and* the DataLoader workers. Before this existed nothing was seeded, so a ~2-point val difference between two runs could not be attributed to the change under test. Also fixes a real bug — see below |

### v2 changes — the reason this directory exists

| arg | default | recommended | notes |
|---|---|---|---|
| `--crowd` | `instance` | `instance` | **Tier 0.** All 1173 train `iscrowd` annotations touch a tile border — they are clipped buildings, not COCO-style crowds. `background` (v1) trains them as negatives and teaches the model to suppress buildings at tile edges |
| `--taps` | `auto` | `auto` | **Tier 3.** Feeds the 4 pyramid levels from 4 different ViT blocks (5/11/17/23 for ViT-L) instead of resampling one. `off` = v1. Or 4 explicit block indices, finest first |
| `--maskiou-weight` | `1.0` | `1.0` | **Tier 1.** The IoU head is a *detached* read-out, so this weight only trades against itself. `0` removes the head entirely — and then `infer.py` cannot use `--score-mode cls_iou` |
| `--collision-weight` | `1.0` | `1.0` → tune | **Tier 2.** Penalizes one query covering two GT buildings. Watch the `col` term actually fall; if it plateaus high, raise to 2–3 |
| `--boundary-weight` | `2.0` | `2.0` | **defaults ON in v2** (v1 was `0`). In BCE units; 1–5 is sane. `--crowd-weight` does nothing without it |
| `--fragment-weight` | `1.0` | `1.0` → maybe `0.5` | **Tier 2b, new after run1.** Mirror of `--collision-weight`: penalises TWO queries splitting ONE building. run1 proved the one-sided term was a mistake — merges did not move (5.1% → 5.2%) while fragmentation worsened (7.3% → 9.9%) and thin slivers went 0.3% → 6.0%. Closed form: `1 − (largest claimant's share)`, so `frg 0.25` reads as "the average contested building loses a quarter of itself to a second query". `0` reproduces run1 |
| `--crowd-weight` | `3.0` | `3.0` | **Tier 2.** Extra weight on the boundary band where two buildings are within `--crowd-gap` px — the narrow alleys that get merged |

### Usually leave alone

| arg | default | notes |
|---|---|---|
| `--dinov3` | `facebook/dinov3-vitl16-pretrain-lvd1689m` | ConvNeXt variant also supported; `--taps` is ViT-only |
| `--m2f` | `facebook/mask2former-swin-base-coco-instance` | warm-starts the pixel + transformer decoder |
| `--backbone` | `auto` | inferred from `--dinov3` |
| `--p-mosaic` | `0.0` | **check → `0.3`.** The only augmentation that raises instance density *and* shrinks apparent size together (3.7× instances, 0.29× median area) — both confirmed gaps to the dense-workshop fabric |
| `--p-rot-any` | `0.75` | default |
| `--p-scale` | `0.8` | default |
| `--boundary-width` | `3` | band half-width in mask-logit px |
| `--collision-active-thr` | `0.2` | a query is "active" (and charged) once it covers this fraction of some instance |
| `--crowd-gap` | `3` | how close two instances must be to count as crowded |
| `--maskiou-hidden` | `256` | |
| `--backbone-lr-mult` | `0.1` | only used when `--unfreeze-last > 0` |

### Ignore unless you are ablating

| arg | default | notes |
|---|---|---|
| `--unfreeze-last` | `0` | *ablation.* Fine-tune the last N ViT blocks. 248 tiles overfits a 300M encoder; try 4–6 only after everything else is settled |
| `--no-stem` | off | *ablation.* Disables the stride-4 image stem |
| `--basa-p` | `0.0` | *ablation.* Near-useless with one style per scene |
| `--no-maskiou-detach` | off | *ablation.* Lets the IoU head's gradient reach the pixel decoder. Detached it **cannot** make masks worse, and the measured +13 AP headroom is pure ranking, so there is no reason to take the risk |

### The run record — `<out>/run_config.json`

Written by **both** trainers (`runlog.py`, shared so that `vertex.py` does not
acquire a transformers dependency just to log JSON), and rewritten every epoch:

```
runs/v2/
  best_ep52.pth       <- lowest val loss so far; weights + the minimum `cfg`
                         infer.py needs to rebuild the architecture
  last_ep60.pth       <- the FINAL epoch only, written once at the end
  run_config.json     <- every argument, resolved settings, environment, result
  loss_log.csv        <- one row per epoch, every loss term
```

**Only two `.pth` ever exist.** Each save writes the new file *then* deletes the
older one carrying the same tag — that order, not the reverse, because a
checkpoint here is ~1.6 GB (the frozen backbone is in the `state_dict` too) and
a full disk partway through a save would otherwise leave you with neither.

**Training starts from a clean `--out`.** If the directory already exists it is
deleted and recreated. That removes a real failure mode: `loss_log.csv` is
*appended*, so a run killed at epoch 9 and relaunched produced one CSV holding
two runs back to back with the epoch column restarting at 1 — which plots as a
sudden jump and reads exactly like divergence.

The wipe is guarded. A non-empty directory is only removed when it actually
looks like a run output (holds a `run_config.json`, `loss_log.csv`, or a `.pth`).
Anything else aborts the launch, because the plausible typo is `--out ./runs`
instead of `--out ./runs/run4` — and `rmtree` on that would take every run with
it. **Inference and polygonization are untouched**; they still write alongside
existing output.

**`last` is written only on the final epoch.** Writing it every epoch cost ~13 s
of a 115 s epoch — about 13 minutes over 60 epochs — for a file that is normally
never loaded. The trade-off: a run killed mid-way leaves only `best_ep*.pth`, so
the newest weights on disk are the *best* ones rather than the *latest* ones.
`best` is still written the moment val improves, so an interrupted run is never
empty.

The epoch in the name is **1-based**, matching the `[ep 12/60]` log line and the
`epoch` field inside the file. v1 stored a 0-based `epoch`, so an old v1
checkpoint reports one less than the log line that produced it.

Because the filename moves during a run, don't hardcode it — pass the
**directory**:

```bash
python infer.py --ckpt runs/v2 --images ... --out ...
```

`resolve_ckpt` picks the highest-numbered `best_ep*.pth` (by parsed integer, not
lexically — `ep9` sorts after `ep100` as a string), falls back to `last_ep*.pth`,
then to a legacy `best.pth`, and errors if there is nothing. It prints which
file it chose.

**To evaluate `last` instead of `best`**, add `--ckpt-tag last`. Works on
`infer.py`, `vertex.py apply` and `vertex.py bench`:

```bash
python infer.py --ckpt runs/v2 --ckpt-tag last --images ../dataset/new_data/data_stride256/val/images --out output/v2/val_last --score-mode cls_iou --save-masks
```

Useful when you suspect the val loss picked the wrong epoch — `best` minimises
the **base Mask2Former loss**, which is deliberately blind to the mask-IoU head
(it is detached) and only indirectly related to AP. If `last` scores better on
`eval.py`, that is a real signal that val loss is the wrong selector for this
model, not noise.

Naming a file explicitly still works and overrides the tag: `--ckpt
runs/v2/last_ep59.pth`. Combining the two prints a warning rather than silently
loading the file you were trying to avoid.

| block | contents |
|---|---|
| `command`, `cwd`, `started`, `updated` | the invocation, verbatim |
| `args` | **every** argument, including ones left at their default |
| `args_from_cli` | which flags were **explicit**. This is the difference between "the run used `--taps auto`" and "the run used `--taps auto` because that was the default at the time" — defaults move between versions, so only the first is reproducible |
| `env` | python / torch / transformers versions, host, CUDA, GPU name |
| `derived` | settings **as resolved**, not as requested: `taps_resolved` becomes the actual block indices, `num_queries_effective` the count the model ended up with, plus param counts per LR group, dataset sizes, token grid, steps |
| `result` | `best_val`, `best_epoch`, `epochs_completed`, and the last value of each loss term |

Three deliberate properties:

- **First write happens before the model is built**, so a run that dies inside
  `from_pretrained` still leaves a record of what it was trying to do.
- **Rewritten every epoch**, because the usual way a 60-epoch run ends is being
  killed — a record that only covers finished runs is missing exactly the ones
  you need to look at.
- **Atomic** (temp file + replace), so a kill landing mid-write cannot destroy
  the record of a run that already completed 40 epochs.

To diff two runs:

```bash
diff <(python -m json.tool runs/v2/run_config.json) <(python -m json.tool runs/v2b/run_config.json)
```

### `<out>/loss_log.csv`

One row per epoch, **appended** — unlike `run_config.json`, which is rewritten.
This is the artefact that must survive a kill with its full history intact, and
rewriting it every epoch would risk the whole run on a single bad write.

```
epoch,train,val,bnd,col,iou_l2,iou_auc,iou_mae_pos,iou_mae_all,lr_head,is_best,secs,time
```

The header is fixed by the first row. A key added later is dropped with a
warning and a key that goes missing blanks its field, so columns can never
shift mid-file — a silently shifted column is worse than a missing metric.

```bash
python -c "import pandas as pd; d=pd.read_csv('runs/v2/loss_log.csv'); print(d.tail(10)); d.plot(x='epoch', y=['train','val']).figure.savefig('loss.png')"
```

### Reading the log

```
[ep 12/60] train 21.31  val 20.11  bnd 0.84  col 0.31  iou_auc 0.83  iou_mae+ 0.11  iou_mae 0.19  *
```

- `val` selects the checkpoint (base Mask2Former loss only)
- `bnd`, `col` — the two Tier 2 terms. **If either sits at exactly 0.0000, that
  term is doing nothing** and you have a configuration problem. Watch for a
  *plateau* too: on a real run `col` fell 80% (working) while `bnd` went flat at
  0.562 ± 0.006 from epoch 7 onward (stalled — raise `--boundary-weight`)
- **`iou_auc`** — P(the head scores a well-matched query above a garbage one).
  0.5 is chance; want > 0.8. Better than MAE, but **read it with a caveat**:
  most target≈0 queries are *parked* with near-empty masks, and telling an
  empty mask from a real one is nearly free given the log-area feature the head
  receives. A real run hit 0.87 after a single epoch for that reason. It
  measures "does the head reject garbage", not the harder AP-relevant question
  "does it rank a confident-but-wrong mask below a good one"
- `iou_mae+` — MAE restricted to queries that actually matched something
- `iou_mae` — MAE over *all* queries. **Nearly unreadable as progress, and kept
  only for continuity.** With `--num-queries 200` and ~26 instances per tile,
  ~87% of queries are parked at target ≈ 0, so this mostly measures how well the
  head predicts zero. A useless *constant* predictor scores 0.474 on that
  distribution, so a value like 0.19 is much better than constant while saying
  nothing about ranking. This metric replaced a bare `val_iou_mae` for exactly
  that reason

So the decisive Tier 1 check is not in the log at all — it is AP under two
rankings over the same masks, which needs no retraining:

```bash
python eval.py --gt ../dataset/new_data/data_stride256/val/annotations.json --npz output/v2/val --name by_iou_head --npz output/v2/val --name by_mask_quality --score-key pred_iou --score-key mask_quality
```

---

## Stage 3 — predict masks on val

```bash
python infer.py --ckpt runs/v2 --images ../dataset/new_data/data_stride256/val/images --out output/v2/val --score-mode cls_iou --threshold 0.05 --save-masks
```

| arg | default | recommended | notes |
|---|---|---|---|
| `--ckpt` | — | **SET** | a checkpoint file **or a run directory** — then the newest checkpoint with the `--ckpt-tag` tag is used, so the command does not go stale when the best epoch moves. Architecture is rebuilt from the `cfg` inside it; a mismatch is a hard error, not a silent garbage load |
| `--ckpt-tag` | `best` | `best` | which of the two rolling checkpoints to load when `--ckpt` is a **directory**: `best` (lowest val loss) or `last` (final epoch). Ignored — with a warning — when `--ckpt` names a file |
| `--images` | — | **SET** | folder of images |
| `--out` | — | **SET** | writes `*_overlay.png`, and `*_masks.npz` with `--save-masks` |
| `--save-masks` | off | **ON** | required by `eval.py`, `polygonize.py` and `vertex.py`. Without it you get pictures and nothing else |
| `--save-raw-masks` | off | *for analysis* | also writes `<stem>_raw_masks.npz`: the instance pool **before** de-duplication and cleaning, plus a `survived_dedup` bool per instance. The final npz has already thrown away the masks dedup lost, so this is the only way to test alternatives to dropping overlaps. Expect 2–4× more instances |
| `--score-mode` | `cls_iou` | `cls_iou` | **Tier 1.** `cls_iou` / `iou` use the mask-IoU head; `cls_mq` is v1. Falls back to `cls_mq` with a warning on a headless checkpoint |
| `--tile-size` | `512` | from ckpt | overridden by the checkpoint's `image_size` unless you pass it explicitly |
| `--overlap` | `128` | `128` | sliding-window overlap. Only used when the image is larger than the tile |
| `--threshold` | `0.5` | **`0.05` with `cls_iou`** | score cut, applied to the *combined* score. **The scale changed in v2 and the default did not.** v1's `cls × mq` sat at ~0.93, so 0.5 discarded nothing (measured: 0.5→0.8 moved TP/FP/FN by exactly zero). `cls × pred_iou` is a *predicted IoU* — ~0.8 for a good detection, ~0.4 for a mediocre one — so 0.5 silently deletes most true positives and the run looks worse than v1 for a purely mechanical reason. `infer.py` warns if you leave it above 0.3. Threshold low; AP integrates over the rest |
| `--tta` | off | **off** | 8× cost, refines boundaries, recovers no missed buildings. Turn on only for a final production run |

### Post-processing (defaults are measured, not guessed)

| arg | default | notes |
|---|---|---|
| `--mask-threshold` | `0.5` | sigmoid cut for binarization. Lower to ~0.35 only if masks look inset |
| `--min-side` | `8.0` | **drop instances whose minAreaRect short side is under this.** At 0.5 m/px, 8 px = 4 m — narrower than any real footprint here, so these are leakage. Measured on run1: drops 191 of 2134 instances, only 4 of them true positives → AP 0.3820→0.3844, AP<800px 0.1154→**0.1274**, precision 0.5809→0.6158, F1 0.6488→0.6689. `10` overshoots (AP 0.3804). `0` disables |
| `--max-aspect` | `6.0` | same filter on the long/short ratio. `0` disables |
| `--min-area` | `100` | drop instances below this px |
| `--iou-thr` | `0.5` | de-dup IoU |
| `--ios-thr` | `0.8` | de-dup containment (catches a small mask swallowed by a large one) |
| `--min-frac` | `0.15` | in a multi-blob instance, drop blobs below this fraction of the largest |
| `--max-hole-frac` | `0.25` | fill interior holes up to this fraction of area |
| `--open-k` | `3` | morphology **by reconstruction** — corner-preserving; plain opening chamfers rotated corners by 1–3 px |
| `--close-k` | `5` | the dual: fills enclosed holes and sub-kernel gaps, never touches the outer contour |
| `--clean-ios-thr` | `0.6` | containment threshold for the post-clean de-dup |
| `--no-clean` | off | *ablation.* Skips the whole cleaning stage |

### Visualization only

| arg | default | notes |
|---|---|---|
| `--alpha` | `0.45` | overlay opacity |
| `--show-scores` | off | prints `cls`, mask-quality and predicted IoU per instance — use when a prediction looks wrong and you want to know *why* |
| `--side-by-side` | off | image next to overlay |
| `--viz-stages` | off | raw / dedup / clean panels |

---

## Stage 4 — score the masks

```bash
python eval.py --gt ../dataset/new_data/data_stride256/val/annotations.json --npz output/v2/val --name v2 --npz ../dinov3/output/vit/new/val_stride256 --name v1 --out eval_v2.json
```

`--npz` and `--name` are repeatable and pair up in order, so v1 and v2 are
scored side by side in one table.

| arg | default | recommended | notes |
|---|---|---|---|
| `--gt` | — | **SET** | the split's `annotations.json` |
| `--npz` | `[]` | **SET** | repeatable: a folder of `*_masks.npz` |
| `--name` | `[]` | **SET** | one label per source, `--npz` first then `--json` |
| `--json` | `[]` | *alt* | COCO-results JSON (SAMPolyBuild style) |
| `--out` | none | **SET** | writes the whole result as JSON |
| `--crowd-ios-thr` | `0.5` | `0.5` | **Tier 0.** An unmatched prediction at least this fraction inside an `iscrowd` region is *ignored*, not counted FP — COCOeval's semantics, which the P/R/F1 block previously did not follow. `1.1` restores the old behaviour |
| `--score-key` | `[]` → `scores` for npz, `score` for json | **one per source** | **repeatable, paired with the sources in order like `--name`.** One key applies to all; one key per source compares rankings over the *same* masks. AP is a function of the ranking, so this changes AP a lot — 0.3783 / 0.3641 / 0.3519 for `scores` / `cls_scores` / `mask_quality` on identical v1 masks. It used to be single-valued, which made the head-to-head silently meaningless: two flags left only the last, and all 14 metrics came out byte-identical | which stored field ranks predictions: `scores`, `pred_iou`, `cls_scores`, `mask_quality`. **AP is a function of the ranking**, so this changes AP a lot — use it to A/B a ranking with no GPU. A missing key is now fatal rather than silently falling back |
| `--iou-thr` | `0.5` | `0.5` | for the P/R/F1 block; AP always sweeps |
| `--dilation-ratio` | `0.02` | `0.02` | Boundary-IoU band as a fraction of the image diagonal (14 px on a 512 tile). **Always quote this next to any boundary number** — the same 3 px shift scores 0.000 at d=3 and 0.647 at d=14 |
| `--boundary-px` | none | *ablation* | absolute band width, overrides the ratio |
| `--score-thr` | `0.0` | `0.0` | P/R/F1 only |

### Verified baseline

Running this on the **existing v1 predictions** with the Tier 0 fix:

```
P 0.6151 -> 0.6651    F1 0.6743 -> 0.7026    FP 706 -> 568  (+138 ignored on crowd)
```

Free — no retraining. AP is unchanged at 0.3783.

---

## Stage 5 — predict masks on train

Only for stage 7. The vertex refiner should be trained on the seeds it will
actually see; without this it falls back to GT masks degraded to match the
measured error profile.

```bash
python infer.py --ckpt runs/v2 --images ../dataset/new_data/data_stride256/train/images --out output/v2/train --score-mode cls_iou --threshold 0.05 --save-masks
```

Same arguments as stage 3. This is a leaky training signal in the strict sense —
the segmenter saw these tiles — but the refiner only consumes the *mask shape*,
and the alternative is a synthetic proxy. Documented, not hidden.

---

## Stage 6 — masks → seed polygons

```bash
python polygonize.py --masks output/v2/val --out output/v2/val_polys --images ../dataset/new_data/data_stride256/val/images --ann ../dataset/new_data/data_stride256/val/annotations.json --viz
```

Run it for `output/v2/train` too (drop `--viz`) if you are doing stage 7.

`regularize()` here is already the "orientation-constrained regularizer"
approach — its output is at **1.31° mean / 0.03° median** angular deviation
against GT's 0.84°. Rectilinearity is solved; do not try to tighten it.

| arg | default | recommended | notes |
|---|---|---|---|
| `--masks` | — | **SET** | folder of `*_masks.npz` (a single file also works) |
| `--out` | next to the npz | **SET** | folder for `*_polys.json` |
| `--min-area` | `200` | `200` | skip instances below this |
| `--min-iou` | `0.7` | `0.7` | reject the *regularization* (not the detection) if the polygon drifts from its mask; falls back to a simplified contour |
| `--dp-eps` | `3.0` | `3.0` | Douglas-Peucker tolerance |
| `--angle-tol` | `20.0` | **`20.0` — do not raise** | axis-snap tolerance. Loosening to 35 raises the right-angle share 59%→94% and *costs* 0.954→0.918 mean IoU, wrecking L/U/Z-plan buildings. Right-angle share is not a safe objective |
| `--min-edge` | `3.0` | `3.0` | drop edges shorter than this |
| `--images` | none | for `--viz` | source tiles for the raw panel |
| `--ann` | none | for `--viz` | GT polygons for a comparison panel. Only affects visualization |
| `--viz` | off | on for val | writes comparison panels — the fastest way to see what changed |
| `--alpha` | `0.45` | default | |
| `--no-corner-restore` | off | *ablation* | |
| `--no-fallback` | off | *ablation.* Drops instances instead of falling back — breaks index alignment with the npz |
| `--free-form` | off | *ablation.* No rectilinear prior at all |

---

## Stage 7 — train the vertex refiner

```bash
python vertex.py train --data-root ../dataset/new_data/data_stride256 --masks-dir-train output/v2/train --masks-dir-val output/v2/val --epochs 40 --batch-size 32 --workers 4 --lr 3e-4 --out runs/vertex
```

| arg | default | recommended | notes |
|---|---|---|---|
| `--data-root` | — | **SET** | dir containing `train/` and `val/` |
| `--masks-dir-train` | none | **SET** (stage 5) | real predicted masks for the train tiles. Without it, seeds come from GT masks degraded to match the measured error — calibrated (3.18 px mean target offset vs 3.27 px for real predictions) but it reproduces the error's *magnitude*, not its correlation with the image, and that correlation is the cue the model must learn |
| `--masks-dir-val` | none | **SET** (stage 3) | same for val |
| `--epochs` | `40` | `40` | ~6 min/epoch on CPU at batch 24; much faster on GPU |
| `--batch-size` | `32` | `32` | 0.70M params — this is not the bottleneck |
| `--workers` | `4` | `4` | each item calls `regularize()`, ~18 ms; workers matter |
| `--lr` | `3e-4` | `3e-4` | |
| `--out` | `./runs/vertex` | **SET** | |
| `--size` | `128` | **`128` — do not lower** | crop resolution, i.e. the model's entire spatial budget for sub-pixel corner localization. Lowering it reintroduces the defect being fixed |
| `--k` | `64` | `64` | contour sample points. GT polygons have ≤6 vertices 79% of the time, so this is not vertex capacity — it buys resolution for the per-edge line fits |
| `--max-shift` | `0.12` | `0.12` | offset bound in normalized crop units ≈ 7.7 crop px, comfortably above the 3.94 px median error |
| `--dim` | `128` | default | transformer width |
| `--layers` | `3` | default | transformer depth |
| `--corner-weight` | `1.0` | `1.0` | weight of the is-corner BCE against the offset loss |

Log line: `tr_off` / `tr_cor` are the two loss terms; **`va_resid` is the one to
watch** — mean absolute offset residual in crop pixels, directly comparable to
the 3.94 px the pipeline starts from.

---

## Stage 8 — score corner accuracy

```bash
python vertex.py bench --ckpt runs/vertex --data-root ../dataset/new_data/data_stride256/val --masks output/v2/val --seeds output/v2/val_polys
```

**This is the only metric that can see this stage.** Mask IoU cannot: a 2 px
corner shift scores 0.98. `bench` scores against GT *vertices* and prints the
two reference rows next to your result.

| arg | default | recommended | notes |
|---|---|---|---|
| `--ckpt` | — | **SET** | file or run directory |
| `--ckpt-tag` | `best` | `best` | which of the two rolling checkpoints to load when `--ckpt` is a **directory**: `best` (lowest val loss) or `last` (final epoch). Ignored — with a warning — when `--ckpt` names a file |
| `--data-root` | — | **SET** | a **split** dir (`…/val`), containing `images/` and `annotations.json` — not the parent |
| `--masks` | — | **SET** | folder of `*_masks.npz` |
| `--seeds` | none | **SET** | must match what you pass to `apply`, or you are not benchmarking the pipeline you will run |
| `--corner-thr` | `0.5` | `0.5` → tune | corner probability cut. Lower → more vertices |
| `--min-gap` | `2` | `2` | minimum index separation between kept corners |
| `--min-iou` | `0.80` | `0.80` | the safety guard, see stage 9 |
| `--min-area` | `200` | `200` | match stage 6 |

### The bar

| | mean | p50 | <2 px |
|---|---|---|---|
| current pipeline | 9.03 px | 3.94 | **24%** |
| `regularize()` on a **perfect** mask | 2.68 px | 1.10 | **84%** |

- Doesn't beat row 1 → **leave this stage off.**
- Beats row 1 but not row 2 → the image conditioning is not yet earning its
  keep. Next move is real training seeds (stage 5) or more capacity — *not* more
  post-processing.
- Beats row 2 → it is doing the thing only an image-conditioned head can do.

---

## Stage 9 — refine the polygons

```bash
python vertex.py apply --ckpt runs/vertex --masks output/v2/val --images ../dataset/new_data/data_stride256/val/images --seeds output/v2/val_polys --out output/v2/val_polys_refined
```

| arg | default | recommended | notes |
|---|---|---|---|
| `--ckpt` | — | **SET** | file or run directory |
| `--ckpt-tag` | `best` | `best` | which of the two rolling checkpoints to load when `--ckpt` is a **directory**: `best` (lowest val loss) or `last` (final epoch). Ignored — with a warning — when `--ckpt` names a file |
| `--masks` | — | **SET** | folder of `*_masks.npz` |
| `--images` | — | **SET** | source tiles — the whole point is reading the image |
| `--out` | — | **SET** | writes `*_polys.json`, same format as `polygonize.py` |
| `--seeds` | none | **SET** | `polygonize.py` output. Without it, seeds are re-derived from each raw mask and you lose `partition()` — the step that makes instances disjoint, worth 0.417→0.487 IoU on the instances it touches. Buildings cannot physically overlap; skip this and they can |
| `--corner-thr` | `0.5` | same as `bench` | |
| `--min-gap` | `2` | same as `bench` | |
| `--min-iou` | `0.80` | `0.80` | **the safety guard.** Rejects a refinement that disagrees with its own mask *and* does so worse than the seed did. This stage can decline to help; it must never harm. Raise toward 0.9 to be more conservative |
| `--min-area` | `200` | `200` | |

Watch the closing line: `refined N, fell back M (X%)`. A high fallback rate
means the refiner is not trusted on most instances — check `bench` before
shipping it.

---

## Stage 10 — production run on full scenes

Stages 3–9 above run on 512 tiles so `eval.py` can score them. For real output,
point `infer.py` at whole scenes — it does sliding-window inference, border
rejection and global de-duplication itself.

```bash
python infer.py --ckpt runs/v2 --images ../dataset/scenes --out output/v2/scenes --score-mode cls_iou --threshold 0.05 --tile-size 512 --overlap 128 --tta --save-masks
```
```bash
python polygonize.py --masks output/v2/scenes --out output/v2/scenes_polys
```
```bash
python vertex.py apply --ckpt runs/vertex --masks output/v2/scenes --images ../dataset/scenes --seeds output/v2/scenes_polys --out output/v2/scenes_polys_refined
```

Two differences from the eval path: `--tta` is worth its 8× cost here, and
`polygonize.py` must run on **complete scene-level instances** — polygonizing
per tile and merging afterwards leaves seam vertices along every tile boundary a
building crossed. That is why stitching and de-duplication happen inside
`infer.py`, before this.

---

# Measured results

**Current best: run3, `--threshold 0.10` with default containment.**
Trained on `data_stride128` (902 tiles / 25880 instances), 60 epochs,
`best_ep33.pth`. Scored on the common `data_stride256` val split (52 tiles,
1515 non-crowd GT) so it is comparable with everything below.

| | v1 | run1 | run2 | **run3** |
|---|---|---|---|---|
| predictions | 1675 | 1946 | 1987 | 1913 |
| **AP** | 0.3544 | 0.3844 | 0.3854 | **0.4262** |
| AP50 | 0.5681 | 0.6033 | 0.6101 | **0.6606** |
| **AP <800px** | 0.1062 | 0.1272 | 0.1372 | **0.1945** |
| AP 800–5000px | 0.4325 | 0.4562 | 0.4581 | **0.5028** |
| AP >5000px | 0.4210 | 0.4728 | 0.4720 | **0.4732** |
| AR100 | 0.4707 | 0.5137 | 0.5040 | **0.5476** |
| **Boundary AP** | 0.2460 | 0.2618 | 0.2601 | **0.3053** |
| precision | **0.6703** | 0.6151 | 0.5954 | 0.6646 |
| recall | 0.6871 | 0.7320 | 0.7248 | **0.7769** |
| **F1** | 0.6786 | 0.6685 | 0.6538 | **0.7164** |
| mask IoU | 0.8171 | 0.8253 | 0.8224 | **0.8266** |
| Boundary IoU | 0.7396 | 0.7562 | 0.7512 | **0.7623** |

run3 is the first configuration that does not trade precision for recall: it
matches v1's precision (0.6646 vs 0.6703) while adding **9 points of recall**.

### Inference threshold / containment sweep, same checkpoint

| variant | preds | AP | precision | recall | F1 |
|---|---|---|---|---|---|
| `--threshold 0.05`, ios 0.8/0.6 | 2023 | 0.4279 | 0.6338 | 0.7848 | 0.7013 |
| `--threshold 0.05`, ios 1.1/1.1 | 2300 | **0.4369** | 0.5801 | **0.8152** | 0.6778 |
| **`--threshold 0.10`, ios 0.8/0.6** | 1913 | 0.4262 | **0.6646** | 0.7769 | **0.7164** |

Raising the threshold 0.05 → 0.10 costs **0.002 AP** and buys **+0.015 F1** —
the 110 predictions scoring in [0.05, 0.10) were almost entirely false
positives. `--ios-thr 1.1` gives the best AP but the worst F1; it is the right
choice only if a missed building costs more than a duplicate.

### Polygons (the deliverable)

| | v1 | **run3** | GT |
|---|---|---|---|
| polygons | 1675 | 1887 | 1515 |
| matched @IoU 0.5 | 1036 | **1155** | |
| missed | 479 | **360** | |
| **F1** | 0.6495 | **0.6790** | |
| polygon vs GT IoU | 0.8147 | **0.8248** | |
| polygon vs own mask IoU | 0.9392 | **0.9585** | |
| **angular deviation** | 1.444° | **0.782°** | 0.837° |
| **corners <2px** | 24.1% | **31.0%** | |
| corners <4px | 50.9% | **56.4%** | |

run3's polygons are now **more rectilinear than the ground truth** (0.782° vs
0.837°), and corner accuracy moved for the first time (24.1% → 31.0% within
2px) with no vertex refiner — against the 84% ceiling a perfect mask allows.

### Cumulative v1 → run3

AP **+0.072**, F1 **+0.038**, polygon F1 **+0.030**, angular deviation
1.44° → 0.78°, corner accuracy 24% → 31%, thin slivers 1.9% → 0%.

---


`runs/run1` at epoch ~20 of 60, against the v1 baseline in
`../dinov3/output/vit/new/val`. Both on the same 52 val tiles / 1515 non-crowd
GT instances.

| | v1 | **v2 run1** | Δ |
|---|---|---|---|
| AP | 0.3544 | **0.3820** | **+0.028** |
| AP50 | 0.5681 | 0.5995 | +0.031 |
| AP75 | 0.3879 | 0.3942 | +0.006 |
| AP <800px | 0.1062 | 0.1154 | +0.009 |
| AP 800–5000px | 0.4325 | 0.4541 | +0.022 |
| AP >5000px | 0.4210 | **0.4733** | **+0.052** |
| AR100 | 0.4707 | 0.5154 | +0.045 |
| Boundary AP | 0.2460 | 0.2608 | +0.015 |
| mask IoU (matched) | 0.8171 | 0.8252 | +0.008 |
| Boundary IoU (matched) | 0.7396 | 0.7562 | +0.017 |
| recall | 0.6871 | 0.7347 | +0.048 |
| precision | 0.6703 | 0.5809 | −0.089 † |
| TP / FP / FN | 1041 / 512 / 474 | 1113 / 803 / 402 | |
| ignored on crowd | 122 | 218 | ‡ |

† **Not comparable as printed.** The P/R/F1 block uses `--score-thr 0.0`, so
every stored prediction counts, and v2 ran inference at `--threshold 0.05`
against v1's `0.5` — 2134 predictions vs 1675. AP integrates over confidence
and is the fair number. Threshold-match before reading precision.

‡ Tier 0 working as intended: v2 fires on 218 tile-edge (`iscrowd`) buildings
against v1's 122, because it is no longer trained to suppress them — and
`eval.py` now ignores rather than penalises those.

Mask/Boundary IoU improved in **every** size bucket, including the worst one
(>5000px boundary IoU 0.6635 → 0.6768).

### Tier 1 isolated — same masks, ranking only

| ranked by | AP | AP50 |
|---|---|---|
| `cls × pred_iou` (`scores`) | **0.3820** | 0.5995 |
| `pred_iou` alone | 0.3818 | **0.6006** |
| `cls_scores` alone | 0.3714 | 0.5881 |
| `mask_quality` alone (the v1 signal) | 0.3146 | 0.5072 |

**+0.067 AP (+21%) from the IoU head over `mask_quality`, with identical mask
pixels.** Every ranking-invariant metric (AR100, P/R/F1, mask IoU) is
byte-identical across those four rows, which is how you know the comparison
isolates ranking and nothing else.

`cls × pred_iou` and `pred_iou` alone are within 0.0002 — **`cls` now
contributes nothing**, consistent with it being saturated (std 0.041). Either
`--score-mode cls_iou` or `iou` is fine.

---

# What has been tried, and what it measured

Read this before proposing anything. Most of the ideas below are reasonable and
were tried in good faith; the point of the table is that they have already been
measured on this dataset, so re-trying them costs a day and returns the same
answer. All numbers are the 52-tile val split.

## Runs

| run | config | best val | AP | verdict |
|---|---|---|---|---|
| v1 | `../dinov3`, 1675 preds | 19.85 @ep43 | 0.3544 | baseline |
| **run1** | v2 tiers 0/1/2/3, no seed | 20.07 @ep43 | **0.3844** | the v2 gain is real |
| run2 | run1 + `--fragment-weight 1.0`, `--seed 0` | 20.35 @ep54 | 0.3854 | fragmentation term did nothing |
| run3-mosaic | run2 + `--p-mosaic 0.3`, no frag | 25.77 @ep5, then rising | — | killed; mosaic hurts |
| **run3** | **`data_stride128`**, `--boundary-weight 5`, no frag | 20.23 @ep33 | **0.4262** | **best; adopt** |

## What worked

| change | measured |
|---|---|
| **Tier 1 mask-IoU head** | ranking alone: `mask_quality` 0.3146 → `pred_iou` 0.3854 = **+0.067 AP**. The single biggest lever in the project |
| **Tier 0 crowd-as-instance + eval crowd-ignore** | precision 0.615 → 0.665 with no retraining |
| **Tier 3 `--taps auto`** | AP <800px 0.1062 (v1) → 0.1272 → 0.1372 (run2) |
| **`--min-side 8 --max-aspect 6`** (sliver filter) | drops 191 of 2134, only 4 TPs: AP 0.3820 → 0.3844, F1 0.6488 → 0.6689, thin slivers 6.0% → **0%** |
| **`--ios-thr 1.1`** (stop discarding contained masks) | **AP 0.3844 → 0.4016**, AR100 0.5137 → 0.5488. Costs precision (0.615 → 0.551), so it is a deliverable-dependent choice — good for polygons, bad for one-instance-per-building |

## What did not work — do not re-try without new evidence

| idea | why it failed |
|---|---|
| ~~**`collision_loss`** (Tier 2, merge penalty)~~ **— CORRECTED, it works** | On stride256 the val merge rate did not move (5.1% → 5.8% → 5.7%) and I wrote it off. On **stride128 it works**: merged predictions fell to **3.7%**. The term was DATA-STARVED, not broken — 6546 training instances were not enough, 25880 were. Keep it |
| **`fragmentation_loss`** (Tier 2b) — **re-test before retiring** | On stride256 `frg` fell 96% while measured fragmentation got *worse* (9.2% → 10.8%), and the construction has a real flaw: two queries each owning a genuine half means each half's largest claimant is itself, so `excess ≈ 0`. BUT that verdict was reached under the same data starvation that made `collision_loss` look broken, and fragmentation is still ~10% — the largest unsolved failure mode. Re-test on stride128 before retiring it |
| **mosaic** (`--p-mosaic 0.3`) | val best at ep5 then rising (+0.091/ep) while train fell; +5.06 val behind run2 by ep13. Its original justification was a *cross-scene* train/test gap. This dataset is a column split of the same 7 scenes and the distributions already match (GT area median 2516 vs 2295, ratio **0.91**), so mosaic now *creates* a scale mismatch instead of closing one |
| **merging overlapping masks instead of dropping** | tested 3 ways on the raw pre-dedup pool. On the 510 groups dedup collapses: 79.4% ties, 12.2% worse, 8.4% better. AP 0.3844 → 0.3687. Adjacency-based merging is worse still (71.0% worse), and a rectangularity gate makes it worse again — because the union of two adjacent rectangles is *also* a rectangle, so no shape test separates "one split roof" from "two neighbours" |
| **detecting/repairing bays and tentacles** | GT has **more** of both than the predictions (bay >0.05: GT 32.6% vs pred 21.4%; tentacle: GT 3.2% vs pred 0.8%), so no threshold separates a defect from a real L-shaped building. Filling bays costs up to −0.126 IoU. Trimming tentacles costs −0.05 |
| **global morphology for appendages** | opening *by reconstruction* cannot remove an appendage (the body's seed propagates back through the connection — 5 of 2134 masks changed); plain opening touches 1039–1315 masks to move solidity only 10.8% → 9.6% |
| **raising `--image-size` for boundary accuracy** | resolution is not the constraint. GT round-tripped through the mask-logit grid caps IoU at **0.9523** at stride 2 (current) and run2 achieves 0.8224 — 0.13 of headroom before quantization bites. 2048 would cost 4× memory to lift a ceiling you are nowhere near |

## Defect diagnostics (run2 output)

Asked and answered, so they need not be re-asked:

- **holes**: 0 of 1987 masks. `fill_holes` clears them all. The raw pre-dedup pool has 134/4947 (2.7%), so a "hole" seen in an overlay of the final output is a **gap between two adjacent instances**, not a hole in one mask
- **saw edges**: autocorrelation of boundary error along the GT contour decays monotonically with **no local maximum** at any lag — so no ViT-token-grid (8 px) or mask-logit-grid (2 px) imprint. Correlation length ~20–30 px, i.e. smooth low-frequency error
- **wall leak**: centroid offset mean +0.34/+0.37 px against std 5.05/4.72, |mean|/std = **0.072**. No consistent direction, so not an off-nadir facade bias — leaks are appearance-driven per instance
- **notches / bays**: each query's mask is an independent sigmoid at 0.5 with no shape prior and no competition between queries, so a notch is simply where that query's probability dipped — shadow, roof material, rooftop clutter. Structural, not a bug

## GT quality

- **vertex detail is not a problem**: GT with >20 vertices still matches at 62.1%, and the 7–12 vertex group is the *best*-performing bucket (80.8%). Simplifying outlines would discard real supervision
- **thinness is**: GT under 8 px wide matches **4.9%** of the time (41 instances, mean IoU 0.061); 8–12 px matches 40.3%; compactness >8 matches **0.0%**. That is 2.3% of train / 2.7% of val, and ~10% of all val misses. A `--min-side` filter in the tiler is the untried fix here

## Open, in priority order

0. **MORE DATA IS THE BIGGEST LEVER FOUND.** stride256 → stride128 (3.6× tiles,
   4.0× instances) was worth **+0.041 AP**, more than every architectural change
   in this project combined. stride64 is the obvious next test, before any
   further loss engineering.

1. ~~**Apply `--ios-thr 1.1`**~~ to run2's output — free, measured +0.017 AP, not yet done
2. **Feed `bay_frac` / solidity into the IoU head** — bay-heavy masks measurably score lower (IoU 0.786 vs 0.825), and ranking is where Tier 1 has repeatedly paid. Use the defect as a confidence signal, not a repair target
3. **`--boundary-weight 4`–`5`** — `bnd` plateaued at 0.51–0.56 in both runs at only ~6% of the loss. The only term aimed at the boundary, and it has never been given real weight
4. **`--min-side` in the tiler** — stop supervising on GT the model provably cannot express

---

# Why each change exists

Baseline: `dinov3/output/vit/new/val_stride256`, 52 val tiles, 1515 non-crowd GT
instances, 1834 predictions.

| | v1 |
|---|---|
| AP / AP50 / AP75 | 0.378 / 0.612 / 0.392 |
| AP_S / AP_M / AP_L | **0.147** / 0.458 / 0.455 |
| P / R / F1 @ IoU 0.5 | 0.615 / 0.745 / 0.674 |
| TP / FP / FN | 1128 / 706 / 387 |
| mask IoU / boundary IoU (matched) | 0.817 / 0.740 |

Precision, not recall, is the bottleneck. The split is honest: val is the
rightmost x-column strip of each of 7 scenes (`crop_daegu1_x001852…`), train
stops at `x001280` + 512 = 1792, so **no tile overlaps between splits** despite
stride 256.

### Tier 0 — `iscrowd` is an ignore region, not background

Two bugs. **Eval:** `match_and_score` had no ignore logic, so 138 of 706 "false
positives" (20%) were predictions landing on crowd regions that `COCOeval`
correctly ignores — the AP and the precision were measuring different things.
Fixed and verified above.

**Training:** `_load_raw` also filtered `iscrowd=False`, making crowd regions
*background targets*. **100% of the 1173 train / 273 val crowd annotations touch
a tile border** — `iscrowd` here means "the tiler clipped this building", not
COCO's "unresolvable heap". Training them as background teaches the model to
suppress buildings at tile edges, exactly where sliding-window inference works.

They are loaded as ordinary instances rather than masked out because the
augmentation pipeline is `(img, masks)` — anything "special" would have to be
smuggled through `mosaic` and `rotate_any` in the mask *values*. The `ignore=`
argument on `boundary_loss` / `collision_loss` exists and is tested for anyone
running `--crowd background`, but nothing in `train_*.py` passes it.

### Tier 1 — mask-IoU head (largest single win, cannot hurt masks)

v1's `score = cls × mask_quality` carries almost no information:

- `cls_scores` mean 0.964, **std 0.041**, 36% above 0.99 — one foreground class,
  so the classifier had nothing to discriminate and saturated
- `mask_quality` mean 0.968, **std 0.020** — nearly a constant
- **24.5% of predictions overlap no GT at all**, mean score 0.903 vs 0.948 for TPs
- score thresholds 0.5→0.8 change TP/FP/FN by **exactly zero**
- correlation with true IoU: **r = 0.477**

Re-scoring v1's own predictions and re-running COCOeval:

| ranking | AP | AP50 | AP_S |
|---|---|---|---|
| random | 0.285 | 0.514 | 0.129 |
| `cls` alone | 0.364 | 0.615 | 0.143 |
| `cls × mq` (v1) | 0.378 | 0.612 | 0.147 |
| **oracle true IoU** | **0.508** | 0.743 | 0.267 |

42% of the available signal; a perfect ranker is **+13 AP with zero mask pixels
changed**. Hand-crafted cues can't substitute — least squares on {score, cls,
mq, rectangularity, compactness, log area} reaches only r = 0.524.

`heads.py` regresses IoU per query from the decoder query embedding + mask
features pooled under the query's own mask + 3 geometry scalars. Inputs are
**detached**: a pure read-out that cannot move a mask pixel.

### Tier 2 — instance separation

Of 387 missed GT buildings, by coverage against the union of all predictions:

- **45% (176) >60% covered** — found, then glued into a neighbour's instance
- 47% (183) <25% covered — genuinely undetected, **76% of those <1000 px**
- separately, **134 GT (11.5%) fragmented into ≥2 predictions**

v1's `boundary_loss` **cannot fix merges by construction**: it scores against
the *union* of GT masks, so a shared wall is interior to the target and one blob
spanning both buildings satisfies it.

This corrects the design I first sketched. "Change the target to
`union_edge ∪ contact_edge`" does not work for a zero-gap party wall — the union
target is 1 there, so there is nothing to learn. Split in two:

1. **`collision_loss`** — zero-gap merges. `sum_i cov − max_i cov` per query:
   0 for a query holding one building, growing with each extra one swallowed.
   Averaged over *active* queries only, else 200 mostly-parked queries dilute
   it. One-sided on purpose — the mirror term would fight the main loss's
   assignment, and NMS handles fragmentation.
2. **`--crowd-weight`** — narrow alleys. The 1–3 px sliver between adjacent
   workshops *is* in the union band but gets negligible weight.

### Tier 3 — real multi-scale features

v1 built all four pyramid levels from `last_hidden_state`: every level a
different view of the same tensor, with transposed convs inventing stride-4
detail a stride-16 map does not contain. Cost: AP_S 0.147 vs AP_M 0.458, and 139
of 183 genuinely-undetected buildings under 1000 px.

`--taps auto` feeds each level from a different block. One `LayerNorm` per tap,
which is **not** cosmetic: ViT activation scale grows by roughly an order of
magnitude from block 5 to 23, and without it the early levels are invisible to a
shared optimizer.

### Tier 4 — polygon vertex refinement

Only relevant for vector output; moves nothing on mask AP. Decomposing polygon
error on matched pairs:

```
predicted polygon vs its OWN mask   0.9367   <- polygonization
predicted mask     vs GT            0.8169   <- segmentation
predicted polygon vs GT             0.8140   <- total
```

**Polygonization costs 0.003 IoU and rectilinearity is already solved** (1.31°
mean / 0.03° median vs GT 0.84°). The 3.89° figure quoted earlier in development
was raw *mask* contours, **before** polygonization — do not use it to justify
work on the polygon stage.

What remains is corner localization (24% vs 84% within 2 px, table in stage 8),
and that whole gap is mask error. So a head reading the mask cannot beat
`regularize()` — it has exactly the information `regularize()` already used. It
must read the **image**. Hence refinement, not detection.

Load-bearing design points:

- **Stride 1 throughout** the encoder — the mask fails at this because the
  segmenter's finest features are stride 4; downsampling here reproduces the
  defect. Receptive field from dilation (1-2-4-8).
- **Line-fit-and-intersect**, not "output the corner points". Straight edges
  become a geometric guarantee, and an intersection of two fitted walls beats
  any single predicted point.
- **Near-identity init + `orig_prior`** — an undertrained model reproduces
  `regularize()` instead of scattering vertices.
- **IoU guard** — the stage can decline to help, never harm.

### Bugs the self-tests caught

Worth knowing, since they are the kind that produce plausible numbers rather
than crashes:

1. Zero-initializing a head's final **weight** (not just bias) makes the
   gradient w.r.t. its *input* identically zero — `--no-maskiou-detach` would
   have been a silent no-op.
2. Untrained corner logits selected corners from noise, so line fits spanned the
   wrong walls and vertices landed 5.75 px off a seed they were meant to
   reproduce. Fixed with `orig_prior`; now 0.10 px.
3. The cyclic positional encoding **wasn't cyclic**. Non-integer frequencies are
   not periodic over K samples, so index 0 and K−1 sat at distance 3.41 while 0
   and 1 sat at 2.02 — equal by symmetry in any correct encoding. Integer
   frequencies with 1/f amplitudes: now both exactly 1.905, monotone.
4. `masks_dir` in `VertexDataset` was a **no-op** — documented as "strongly
   preferred" while `__getitem__` always degraded the GT mask.
5. `%` in an argparse help string is a format spec; `--help` crashed with
   `TypeError: %o format`. Twice.

---

# Tuning order

The changes are independent. Verify one at a time.

1. **Tier 0 eval** — already verified, free, no retraining.
2. **Tier 1** — watch `val_iou_mae`; confirm with `eval.py --score-key pred_iou`
   vs `--score-key scores` on the same npz. This is where the +13 AP is.
3. **Tier 3** — `--taps auto` vs `off`, watch AP_S and the `<800px` bucket.
4. **Tier 2** — `--collision-weight`. Watch `col` actually fall, and check
   predicted-vs-GT instance count (v1: 1834 vs 1515) and merge/split counts, not
   just AP.
5. **Tier 4** — `vertex.py bench` against the two reference rows.

# Memory

`collision_loss` is the only change with a real cost: its `sem` tensor is
`(B, Q, h, w)` — 105 MB at `--image-size 1024 --num-queries 200 --batch-size 2`,
and autograd holds several of that shape. It pools 2× by default (`pool=` in
`losses.py`, validated invariant in `selftest.py [4]`); raise to 4 or set
`--collision-weight 0` if you OOM. The IoU head pools to 128² internally and is
negligible. Tier 3 keeps all 24 token tensors alive for the forward — the other
new allocation, unavoidable for tapping.

# Reproducing v1

```bash
python train_dinov3_mask2former.py --data-root ../dataset/new_data/data_stride256 --image-size 1024 --num-queries 200 --taps off --crowd background --maskiou-weight 0 --collision-weight 0 --boundary-weight 0 --out ./runs/v1_repro
```

Then `infer.py --score-mode cls_mq` and `eval.py --crowd-ios-thr 1.1`.
