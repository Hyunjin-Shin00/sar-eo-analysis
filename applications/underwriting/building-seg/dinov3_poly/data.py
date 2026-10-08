"""
Per-instance crops from the refined scenes.

READS THE SCENES DIRECTLY, not the tiled dataset. Tiles clip buildings at their
borders, and a clipped building's "corners" are tile-edge artefacts rather than
building corners -- training a vertex head on those teaches it to fire on
nothing. Crops are small enough that no tiling is needed here at all.

THE SPLIT IS STAGE 1's SPLIT. tile_to_coco_multi_rot cuts a val band of
`val_width` px off the RIGHT of every scene (`cut = W - val_width`), so a
building whose box centre has x >= cut is val. Any other rule leaks pixels
stage 1 trained on into stage 2's validation and makes the two incomparable.

Scene images are loaded once in the parent process. On Linux, DataLoader
workers fork and share those read-only arrays copy-on-write, so 10 scenes at
~270 MB total cost that once rather than once per worker.
"""
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset

from targets import (crop_window, d4_points, render_edge, render_mask,
                     render_vertex, to_cells)

Image.MAX_IMAGE_PIXELS = None
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SKIP = {"gt_overlay.png"}


def rings_of(ann):
    s = ann["segmentation"]
    if isinstance(s, str):
        s = json.loads(s)
    if not s or not isinstance(s[0], (list, tuple)):
        return None
    r = np.asarray(s[0], np.float64).reshape(-1, 2)
    if len(r) > 3 and np.allclose(r[0], r[-1]):
        r = r[:-1]
    return r if len(r) >= 3 else None


def d4_image(img, k, flip):
    if k:
        img = np.rot90(img, k, (0, 1))
    if flip:
        img = img[:, ::-1]
    return np.ascontiguousarray(img)


class PolyDataset(Dataset):
    def __init__(self, root, split="train", crop=256, out=128, val_width=725,
                 augment=False, jitter=(0.88, 1.30, 0.12), min_side=8,
                 edge=True, scenes=None):
        import cv2
        self.cv2 = cv2
        self.crop, self.out, self.edge = crop, out, edge
        self.augment = augment
        self.jitter = jitter if augment else None
        self.imgs, self.items = [], []

        root = Path(root)
        dirs = sorted(d for d in root.iterdir() if d.is_dir())
        if scenes:
            dirs = [d for d in dirs if d.name in scenes]
        for d in dirs:
            ann_f = d / "annotations.json"
            img_f = next((f for f in sorted(d.iterdir())
                          if f.suffix.lower() in IMG_EXT and f.name not in SKIP),
                         None)
            if img_f is None or not ann_f.is_file():
                continue
            arr = np.asarray(Image.open(img_f).convert("RGB"))
            H, W = arr.shape[:2]
            cut = W - val_width
            si = len(self.imgs)
            self.imgs.append(arr)
            for an in json.loads(ann_f.read_text())["annotations"]:
                if an.get("iscrowd"):
                    continue
                r = rings_of(an)
                if r is None:
                    continue
                x1, y1 = r[:, 0].min(), r[:, 1].min()
                x2, y2 = r[:, 0].max(), r[:, 1].max()
                if max(x2 - x1, y2 - y1) < min_side:
                    continue
                is_val = (x1 + x2) / 2.0 >= cut
                if is_val != (split == "val"):
                    continue
                self.items.append((si, np.array([x1, y1, x2, y2]), r))
        print(f"[data] {split}: {len(self.items)} instances "
              f"from {len(self.imgs)} scenes")

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        si, box, ring = self.items[i]
        img = self.imgs[si]
        H, W = img.shape[:2]
        rng = np.random
        x0, y0, side = crop_window(box, jitter=self.jitter, rng=rng)

        # Crop with reflect padding rather than clamping the window: clamping
        # would shift a building near the scene edge off centre, and the head
        # has learned that the subject is the one in the middle.
        S = self.crop
        xi, yi = int(np.floor(x0)), int(np.floor(y0))
        n = int(np.ceil(side)) + 1
        pl, pt = max(0, -xi), max(0, -yi)
        pr, pb = max(0, xi + n - W), max(0, yi + n - H)
        sub = img[max(yi, 0):min(yi + n, H), max(xi, 0):min(xi + n, W)]
        if pl or pt or pr or pb:
            sub = np.pad(sub, ((pt, pb), (pl, pr), (0, 0)), mode="reflect")
        crop = self.cv2.resize(sub, (S, S), interpolation=self.cv2.INTER_LINEAR)

        # ring -> crop pixels, in the same frame the resize produced
        sc = S / float(n)
        r_px = np.stack([(ring[:, 0] - xi) * sc, (ring[:, 1] - yi) * sc], 1)
        b_px = np.array([(box[0] - xi) * sc, (box[1] - yi) * sc,
                         (box[2] - xi) * sc, (box[3] - yi) * sc])

        k = flip = 0
        if self.augment:
            k, flip = rng.randint(4), rng.rand() < 0.5
            crop = d4_image(crop, k, flip)
            r_px = d4_points(r_px, k, flip, S)
            c = d4_points(b_px.reshape(2, 2), k, flip, S)
            b_px = np.array([c[:, 0].min(), c[:, 1].min(),
                             c[:, 0].max(), c[:, 1].max()])
            f = crop.astype(np.float32)
            f *= rng.uniform(0.75, 1.30)
            f *= rng.uniform(0.88, 1.12, size=(1, 1, 3))
            f = 255.0 * np.power(np.clip(f, 0, 255) / 255.0,
                                 rng.uniform(0.75, 1.35))
            crop = np.clip(f, 0, 255).astype(np.uint8)

        # box channel at INPUT resolution: identity of the subject, nothing more
        bx = np.zeros((S, S), np.float32)
        xa, ya, xb, yb = np.clip(np.round(b_px).astype(int), 0, S)
        bx[ya:yb, xa:xb] = 1.0
        x = np.concatenate([crop.astype(np.float32).transpose(2, 0, 1) / 255.0,
                            bx[None]], 0)
        x[:3] = (x[:3] - np.array([0.485, 0.456, 0.406], np.float32)[:, None, None]) \
            / np.array([0.229, 0.224, 0.225], np.float32)[:, None, None]

        rc = r_px * (self.out / float(S))
        vmap, voff, vmask = render_vertex(rc, self.out)
        t = {"mask": torch.from_numpy(render_mask(rc, self.out))[None],
             "vmap": torch.from_numpy(vmap)[None],
             "voff": torch.from_numpy(voff),
             "vmask": torch.from_numpy(vmask)}
        if self.edge:
            t["edge"] = torch.from_numpy(render_edge(rc, self.out))[None]
        return {"x": torch.from_numpy(x), "t": t,
                "n_gt": len(ring), "idx": i,
                "frame": np.array([xi, yi, n], np.float64)}


def collate(b):
    keys = b[0]["t"].keys()
    return {"x": torch.stack([q["x"] for q in b]),
            "t": {k: torch.stack([q["t"][k] for q in b]) for k in keys},
            "n_gt": [q["n_gt"] for q in b],
            "idx": [q["idx"] for q in b],
            "frame": np.stack([q["frame"] for q in b])}
