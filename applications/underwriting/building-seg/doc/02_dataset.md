# 2. Dataset

Korean industrial and suburban building footprints from satellite imagery at
**0.5 m per pixel**. Two forms exist and both are used:

- **Scenes** — ten large images with hand-refined polygon labels. This is the
  source of truth, and it is what stage 2 trains on directly.
- **Tiles** — 512×512 crops generated from the scenes, with rotation
  augmentation baked in. This is what stage 1 trains on.

Everything below describes the **refined** dataset only.

---

## 2.1 The scenes

`dataset/refined_data/scenes/` — ten folders, each holding one image and one
single-image COCO `annotations.json`.

| scene | width | height | instances | mean vertices | median area (px²) |
|---|---|---|---|---|---|
| changwon_crop1 | 3000 | 3000 | 616 | 4.60 | 1704 |
| changwon_crop2 | 2700 | 2000 | 1059 | 4.75 | 1242 |
| daegu_crop1 | 2364 | 3019 | 713 | 4.77 | 2603 |
| daegu_crop2 | 1377 | 1447 | 364 | 4.84 | 1803 |
| gumi_crop1 | 2446 | 1883 | 484 | 4.89 | 2372 |
| gumi_crop2 | 2222 | 1936 | 342 | 5.45 | 2159 |
| gumi_crop3 | 1513 | 2086 | 336 | 4.98 | 2559 |
| namdong_crop1 | 2088 | 3035 | 987 | 5.06 | 2077 |
| namdong_crop2 | 2000 | 2000 | 543 | 4.64 | 2280 |
| namdong_crop3 | 2500 | 2500 | 981 | 4.74 | 1747 |
| **total** | | | **6425** | **4.84** | |

**52.2 megapixels** of imagery, **6425** building polygons, **31 097** vertices.
Four geographic areas: Changwon, Daegu, Gumi, Namdong (Incheon).

### Geometry of the labels

Measured across all 6425 polygons — these numbers drive most of the design
decisions in `03_model.md`:

| property | value |
|---|---|
| vertices per polygon | median **4**, p90 6, max 51 |
| edge length | median **35.2 px**, p5 9.0, p1 3.8 |
| edges shorter than 2 px | **0.6%** |
| building long side | median **65 px**, p10 26, p90 133 |
| distance to the nearest vertex of *another* building | median 23.7 px, p10 3.0 |
| convex polygons | 73.6% |
| corner turn angle | median 89.9°, p99 97.2°, **p99.9 143.2°** |
| turns within 5° of a right angle | **92.3%** |

Two things follow. The buildings are **near-rectilinear quadrilaterals** —
four well-placed corners describe most of this dataset. And real corners
**never fold back**: only 0.064% of corners turn more than 150°, which is why
anything sharper in a prediction can safely be treated as an artefact.

### Annotation format

Standard single-image COCO:

```json
{
  "images":      [{"id": 0, "file_name": "daegu_crop1.png", "height": 3019, "width": 2364}],
  "annotations": [{"id": 0, "image_id": 0, "category_id": 1, "iscrowd": 0,
                   "area": 2603.4, "bbox": [x, y, w, h],
                   "segmentation": [[x1, y1, x2, y2, ..., x1, y1]]}],
  "categories":  [{"id": 1, "name": "building"}]
}
```

`segmentation` is one closed ring per building, as a flat coordinate list.
Coordinates are in the **edge convention**: the image spans `[0, W]`, and pixel
`i` covers `[i, i+1)`. This matters — treating them as pixel *indices* shifts
every corner by half to one pixel.

---

## 2.2 The labelling tool

`labeler/labeler.html` — a single self-contained file. Open it in a browser
(double-click; no server, no install, works offline). Everything runs
client-side, so the images never leave the machine.

**Loading.** Two file pickers: one for the scene image, one for the label JSON.
It reads the model's `_polys.json` output, a COCO `annotations.json`, a plain
`{"polys": [...]}` list, or a bare array — so a prediction can be loaded and
corrected rather than drawn from scratch, which is how these labels were made.

**Editing.**

| action | how |
|---|---|
| zoom | mouse wheel at the cursor, or the `− + Fit 1:1` buttons |
| pan | drag empty space, hold <kbd>Space</kbd>, or middle-drag |
| select a polygon | click it |
| move a vertex | drag the blue dot |
| delete a vertex | right-click it, or <kbd>Del</kbd> when selected |
| **insert a vertex** | click the **orange square** on the edge where it belongs |
| hide / show | `◉` in the list, or <kbd>V</kbd> |
| delete a polygon | `✕` in the list, or <kbd>Del</kbd> |
| new polygon | <kbd>N</kbd>, click points, <kbd>Enter</kbd> to close |
| undo | <kbd>Ctrl</kbd>+<kbd>Z</kbd>, 80 levels |

Insertion is positional by design: the orange handles sit *on edges*, so a new
vertex always lands between the two neighbours you picked. Ring order cannot be
guessed wrong. The right-hand panel lists every vertex coordinate and they can
be typed directly.

**Exporting.** Two buttons, and the distinction matters:

- **`Export COCO · this image`** → `<image>_annotations.json`, one image.
  This is what a per-scene folder needs.
- **`Export COCO · whole session`** → every image loaded during the session in
  one file. Useful for building a single training set; **wrong** for per-scene
  folders, because a per-scene tiler will then stamp every scene's polygons
  onto one image.

`Save session` / `Load session` lets work survive closing the browser.

**Supporting scripts** in `dataset/refined_data/`:

- `visualize_gt.py` — draws `gt_overlay.png` for every scene. It reads polygons
  through the *tiler's own loader*, so the overlay shows exactly what training
  will receive rather than a second opinion about the file.
- `split_annotations.py` — splits a whole-session COCO export back into
  per-scene files. Matches scenes to session images by exact `(width, height)`
  rather than filename, and takes each scene from the most recently written
  export that contains it.

---

## 2.3 Generating the training tiles

`dataset/refined_data/tile_to_coco_multi_rot.py` turns the ten scenes into a
tiled COCO dataset. The current one is `data_stride128_rot/`.

### The order of operations, and why

```
scene  ──►  cut the val band off  ──►  rotate each band  ──►  tile  ──►  filter
            (train | val)              0/15/30/45°          512 px     black, size
```

**1. Split first, rotate second.** The val band is cut off *before* anything
else. Rotating a whole scene and splitting afterwards would put pixels from
either side of the boundary into the same rotated tile, and validation would
quietly contain training pixels. Cutting first makes the separation exact and
verifiable.

The cut is vertical: `cut = W − val_width`. Everything left of `cut` is train,
everything right is val. With `--val-width 725` on a 2364-px-wide scene, the
train band is x < 1639 and the val band is x ≥ 1639.

**2. Rotate at tiling time, not during training.** Rotating a 512 tile during
training leaves black corners — up to 41% of the canvas at 45°. Rotating the
whole *band* first and then cutting tiles out of the interior means a rotated
tile is full of real imagery. Tiles that unavoidably catch the rotated edge are
dropped by `--max-black` (default 0.02, i.e. 2%).

Rotation uses scale 1.0 with an explicit validity mask, so image and labels are
transformed by the identical matrix and cannot drift apart.

**3. Tile with overlap.** `--tile 512 --stride 128` gives 384 px of overlap.
Dense overlap means every building appears whole in at least one tile, which is
what makes the border-rejection rule in stage-1 inference sound.

**4. Filter what lands in each tile.**

- A clipped building keeps its label only if at least `--min-keep` (0.4) of its
  **original** area survives. Below that it is written as `iscrowd`.
  The original area is carried through from before the val-band cut, so a
  building already clipped once is judged against the real building rather than
  against its clipped self.
- Polygons under `--min-area` (64 px²) after clipping are dropped.
- Rotated tiles with more than `--max-black` border fill are skipped entirely.

`iscrowd` here does **not** mean COCO's "unresolvable heap". It means "the tiler
clipped this building". 100% of crowd annotations touch a tile border. Stage-1
training loads them as ordinary instances (`--crowd instance`) because a clipped
building is still a positive example, and dropping them to background teaches
the model to suppress buildings at tile edges — exactly where sliding-window
inference has to work.

### The generated dataset

`data_stride128_rot/`, produced with tile 512, stride 128, rotations
`0 15 30 45`, `--val-width 725`, `--rot-val`:

| split | tiles | annotations | of which crowd |
|---|---|---|---|
| train | 4532 | 162 601 | 28 642 |
| val | 916 | 31 401 | 5481 |

By rotation angle:

| angle | train tiles | train anns | val tiles | val anns |
|---|---|---|---|---|
| 0° | 1318 | 46 133 | 439 | 14 644 |
| 15° | 1120 | 40 405 | 216 | 7543 |
| 30° | 1050 | 38 301 | 165 | 5817 |
| 45° | 1044 | 37 762 | 96 | 3397 |

11 021 rotated tiles were skipped for exceeding the black-fill limit. Fewer
tiles survive at steeper angles, and fewer still in the narrow val band — which
is why `--val-width` must be generous: a 512-px band cannot yield a single clean
45° tile.

### Regenerating it

```bash
cd dataset/refined_data
SRC=(); for d in scenes/*/; do n=$(basename "$d"); SRC+=(--src "$d$n.png" "${d}annotations.json"); done
python tile_to_coco_multi_rot.py "${SRC[@]}" \
    --out data_stride128_rot \
    --tile 512 --stride 128 \
    --rot 0 15 30 45 --rot-val \
    --val-width 725 --max-black 0.02 --min-keep 0.4 --min-area 64
```

Scenes live one per sub-folder with the labels in `annotations.json`, so the
pairs are passed explicitly with `--src`; `--img-dir` pairs by filename stem on
a flat folder and does not recurse.

Add `--only train` or `--only val` to build one side. The boundary is unchanged
either way, so running the two separately gives byte-identical output to one
full run, and `dataset_info.json` merges instead of overwriting.

Output layout:

```
data_stride128_rot/
├── train/images/*.png          train/annotations.json
├── val/images/*.png            val/annotations.json
└── dataset_info.json           what was generated, and with which settings
```

Tile filenames record provenance — `crop_daegu1_r15_x000128_y000384.png` is
scene `crop_daegu1`, rotated 15°, at offset (128, 384) in the rotated band —
and each image record carries `scene`, `x0`, `y0` and `rot` fields.

---

## 2.4 Which stage uses what

| | trains on | why |
|---|---|---|
| **stage 1** | `data_stride128_rot/` tiles | it is a tiled detector; it must see tiles |
| **stage 2** | `scenes/` directly | it crops individual buildings, so it needs whole buildings — a tile edge cuts them, and a clipped building's "corners" are tile artefacts, not building corners |

Both use the **same split**: stage 2 calls a building val if its box centre has
`x ≥ W − 725`, reproducing the tiler's band exactly. Any other rule would leak
stage-1 training pixels into stage-2 validation and make the two incomparable.

Because `val_width` was chosen for the widest scene, narrow scenes give up more
of their width to validation, so the instance split is 4365 train / 2032 val —
**31.8% val**, higher than the 20% the tile count suggests.
