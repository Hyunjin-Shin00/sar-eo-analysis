"""
Tier 4 -- image-conditioned polygon vertex refinement.

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR
----------------------------------------
Measured on the 52 val tiles, decomposing polygon error into its two stages
(matched pairs, mask IoU):

    predicted polygon vs its OWN mask     0.9367     <- polygonization
    predicted mask     vs GT              0.8169     <- segmentation
    predicted polygon vs GT               0.8140     <- total

Polygonization costs 0.003 IoU. `polygonize.regularize()` is already doing its
job, including rectilinearity: its output sits at 1.31 deg mean / 0.03 deg
median angular deviation, against 0.84 deg for the GT itself. There is nothing
left to win by snapping angles harder -- and polygonize.py's own docstring
records what happens when you try.

What IS still wrong is corner LOCALISATION:

                                        mean    p50    within 2px
    current pipeline                     9.03    3.94      24%
    regularize() on a PERFECT GT mask    2.68    1.10      84%

The whole 24% -> 84% gap is mask error. Which fixes the design: a head that
reads the MASK cannot beat regularize(), because it has exactly the
information regularize() already used. To do better it has to read the IMAGE,
at high resolution, and be allowed to move vertices OFF the mask boundary.

So this is refinement, not detection:

    mask -> regularize() -> initial polygon      (topology + rectilinearity:
                                                  vertex count already matches
                                                  GT at 5.07 vs 5.11 mean)
         -> subdivide to K points
         -> THIS MODEL, on the image crop        (per-point offset + is-corner)
         -> keep corners, fit a line per edge, intersect adjacent lines
         -> exact polygon

The line-fit-and-intersect step is why edges come out perfectly straight: it is
a geometric guarantee, not something the network has to learn. The network only
has to say where the corners are and which points belong to which wall.

Fully decoupled from the segmenter -- it consumes masks.npz from any source
(v1, v2, SAMPolyBuild) and never runs the ViT. Trains in minutes on CPU-ish
hardware.

    python vertex.py selftest
    python vertex.py train --data-root ../dataset/new_data/data_stride256 --out runs/vertex
    python vertex.py apply --ckpt runs/vertex/best.pth \\
        --masks ../dinov3/output/vit/new/val_stride256 \\
        --images ../dataset/new_data/data_stride256/val/images --out output/v2/polys
"""

import argparse
import datetime
import json
import math
import time
from functools import partial
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from polygonize import regularize
from runlog import (append_loss_row, fresh_run_dir, resolve_ckpt,
                    save_ckpt, save_run_config)


# ==========================================================================
# 1. Geometry helpers -- plain numpy, no torch, so they are testable alone
# ==========================================================================
def close_poly(p):
    """Drop a duplicated last vertex if present. Everything here is implicitly closed."""
    p = np.asarray(p, np.float64)
    if len(p) > 1 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    return p


def subdivide_to(poly, k):
    """
    Polygon -> exactly `k` points, KEEPING every original vertex.

    Repeatedly splits the currently-longest edge at its midpoint. Uniform
    arc-length resampling would be simpler and is wrong here: it moves the
    corners, and the corners are the one thing regularize() already got right
    (vertex count 5.07 vs GT 5.11). The model's job is to nudge them, not to
    rediscover them.

    Returns (pts (k, 2), is_orig (k,) bool) in original cyclic order.
    """
    poly = close_poly(poly)
    n = len(poly)
    if n < 3:
        return None, None
    if k <= n:
        # Cannot subdivide down. Keep the k longest-edge-adjacent vertices?
        # No -- silently dropping real corners is worse than a short sequence.
        # Callers pad instead; see collate().
        return poly.copy(), np.ones(n, bool)

    lens = [float(np.linalg.norm(poly[(i + 1) % n] - poly[i])) for i in range(n)]
    total = n
    # (negative length, edge index, n_splits) -- a heap would be asymptotically
    # better but k <= 128 and n <= 51, so the argmax scan is not worth avoiding
    counts = [1] * n
    while total < k:
        i = int(np.argmax([lens[j] / counts[j] for j in range(n)]))
        counts[i] += 1
        total += 1
    pts, orig = [], []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        pts.append(a)
        orig.append(True)
        for s in range(1, counts[i]):
            pts.append(a + (b - a) * (s / counts[i]))
            orig.append(False)
    return np.array(pts, np.float64), np.array(orig, bool)


def seg_project(p, a, b):
    """Closest point to `p` on segment ab, and the squared distance."""
    ab = b - a
    d = float(ab @ ab)
    t = 0.0 if d == 0 else float(np.clip(((p - a) @ ab) / d, 0.0, 1.0))
    q = a + t * ab
    return q, float((p - q) @ (p - q))


def project_to_boundary(p, poly):
    """Closest point to `p` anywhere on the polygon's boundary."""
    poly = close_poly(poly)
    best, bd = poly[0], float("inf")
    for i in range(len(poly)):
        q, d = seg_project(p, poly[i], poly[(i + 1) % len(poly)])
        if d < bd:
            best, bd = q, d
    return best, math.sqrt(bd)


def fit_line(pts):
    """
    Total-least-squares line through >=2 points, as (normal, offset) with
    normal . x = offset and |normal| = 1.

    TLS (via SVD), not least-squares-in-y: a vertical wall has infinite slope
    and every y = mx + c fit blows up on it. Half the walls here are vertical.
    """
    pts = np.asarray(pts, np.float64)
    mu = pts.mean(axis=0)
    if len(pts) < 2:
        return None
    _, _, vt = np.linalg.svd(pts - mu, full_matrices=False)
    nrm = vt[-1]                              # least-variance direction
    nrm = nrm / max(np.linalg.norm(nrm), 1e-12)
    return nrm, float(nrm @ mu)


def intersect_lines(l1, l2, eps=1e-6):
    """Intersection of two (normal, offset) lines, or None if near-parallel."""
    if l1 is None or l2 is None:
        return None
    A = np.stack([l1[0], l2[0]])
    if abs(float(np.linalg.det(A))) < eps:
        return None
    return np.linalg.solve(A, np.array([l1[1], l2[1]], np.float64))


def cyclic_nms(scores, thr, min_gap):
    """
    Indices of kept corners: score above `thr`, greedy highest-first, and no
    two kept indices within `min_gap` of each other ON THE CIRCLE.

    Cyclic, not linear -- index 0 and index K-1 are neighbours, and a corner
    straddling the sequence start is exactly the case a linear NMS duplicates.
    """
    k = len(scores)
    order = np.argsort(-np.asarray(scores))
    keep = []
    for i in order:
        if scores[i] < thr:
            break
        if all(min(abs(int(i) - j), k - abs(int(i) - j)) >= min_gap for j in keep):
            keep.append(int(i))
    return sorted(keep)


def polygon_from_points(pts, corner_idx):
    """
    Refined points + chosen corner indices -> polygon with EXACTLY straight edges.

    Each edge spans the points from one corner to the next INCLUSIVE, so every
    span has >= 2 points and the TLS fit is always defined. Adjacent edge lines
    are then intersected to place the vertex. The corner points themselves are
    never used as output vertices -- an intersection of two fitted walls is far
    more accurate than any single predicted point, which is the whole reason to
    fit lines rather than just keep the corners.
    """
    k = len(pts)
    if len(corner_idx) < 3:
        return None
    lines = []
    for j in range(len(corner_idx)):
        a, b = corner_idx[j], corner_idx[(j + 1) % len(corner_idx)]
        idx = list(range(a, b + 1)) if b > a else list(range(a, k)) + list(range(0, b + 1))
        lines.append(fit_line(pts[idx]))

    out = []
    for j in range(len(lines)):
        v = intersect_lines(lines[j - 1], lines[j])
        if v is None:
            # Two collinear walls: no corner there at all. Dropping the vertex
            # is correct -- it means the two spans are one wall.
            continue
        out.append(v)
    return np.array(out, np.float64) if len(out) >= 3 else None


# ==========================================================================
# 2. Crop geometry
# ==========================================================================
def crop_box(poly, shape, size, margin=0.18, min_pad=6.0):
    """
    Square crop around a polygon, and the affine that maps scene -> crop pixels.

    Square and isotropic on purpose: a non-uniform scale would change wall
    angles, and this model's whole output is angles and corners.

    Returns (x0, y0, scale) with  crop_xy = (scene_xy - [x0, y0]) * scale.
    """
    H, W = shape
    p = close_poly(poly)
    lo, hi = p.min(axis=0), p.max(axis=0)
    side = float(max(hi - lo).max() if hasattr(max(hi - lo), "max") else max(hi - lo))
    pad = max(side * margin, min_pad)
    side = side + 2 * pad
    c = (lo + hi) / 2.0
    x0, y0 = c[0] - side / 2.0, c[1] - side / 2.0
    return float(x0), float(y0), float(size) / max(side, 1e-6)


def sample_crop(img, mask, x0, y0, scale, size):
    """
    (3, size, size) float image crop and (1, size, size) mask crop.

    warpAffine rather than slice-and-resize: the box is fractional (it comes
    from a float polygon), and rounding it to integers costs up to half a pixel
    of the localisation this model exists to recover.
    """
    M = np.array([[scale, 0.0, -x0 * scale],
                  [0.0, scale, -y0 * scale]], np.float64)
    im = cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
    mk = cv2.warpAffine(mask.astype(np.uint8) * 255, M, (size, size),
                        flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=0)
    im = im.astype(np.float32) / 255.0
    im = (im - np.array([0.485, 0.456, 0.406], np.float32)) / \
         np.array([0.229, 0.224, 0.225], np.float32)
    return im.transpose(2, 0, 1), (mk[None].astype(np.float32) / 255.0)


# ==========================================================================
# 3. Model
# ==========================================================================
class ImageEncoder(nn.Module):
    """
    Full-resolution dilated conv stack.

    STRIDE 1 THROUGHOUT, deliberately. The point of this model is sub-pixel
    corner localisation, and the reason the mask cannot provide it is that the
    segmenter's finest features are stride 4. Downsampling here would reproduce
    the very defect being corrected. Receptive field comes from dilation
    instead: 1-2-4-8 over 3x3 kernels reaches ~31 px, which at 128 px crop
    covers a quarter of the building -- enough to see both ends of a wall.

    ~180k params at width 48.
    """

    def __init__(self, in_ch=4, width=48, out_ch=64):
        super().__init__()
        def blk(i, o, d):
            return nn.Sequential(
                nn.Conv2d(i, o, 3, 1, d, dilation=d, bias=False),
                nn.GroupNorm(8, o), nn.GELU())
        self.net = nn.Sequential(
            blk(in_ch, width, 1), blk(width, width, 2),
            blk(width, width, 4), blk(width, width, 8),
            nn.Conv2d(width, out_ch, 3, 1, 1))
        self.out_ch = out_ch

    def forward(self, x):
        return self.net(x)


def cyclic_pe(k, dim, device):
    """
    Positional encoding for a CLOSED contour: sinusoids in the cyclic
    parameter t = i/k, so index 0 and index k-1 are adjacent in the encoding
    exactly as they are on the polygon. A standard linear PE would place them
    maximally far apart and the attention would learn a false seam.

    Two constraints, both found by `vertex.py selftest` [7] rather than by
    reasoning, and both easy to get wrong:

    INTEGER frequencies, tiled over 1..k/2. Only integer frequencies are
    periodic over k samples, so only they make the encoding genuinely cyclic:
    with the geometric non-integer spacing that seemed natural here, index 0
    and index k-1 came out at distance 3.409 while index 0 and index 1 were at
    2.024 -- values that are equal by symmetry in any actually-cyclic encoding.
    Above k/2 a sinusoid aliases, so that is the ceiling; `dim/2` components
    over fewer than dim/2 available frequencies simply repeat, which the input
    projection absorbs.

    Amplitudes falling as 1/f. Without it, components of comparable magnitude
    across the whole range contribute similar variance and encoding distance
    barely depends on separation -- measured at 1.15x between opposite ends of
    the contour and immediate neighbours, which is no usable ordering. With 1/f
    the fundamental dominates and distance grows monotonically with cyclic
    separation, which is the property attention needs.
    """
    t = torch.arange(k, device=device, dtype=torch.float32) / k * 2 * math.pi
    n = max(dim // 2, 1)
    f = (torch.arange(n, device=device) % max(k // 2, 1) + 1).float()
    ang = t[:, None] * f[None, :]
    amp = (1.0 / f)[None, :]
    return torch.cat([ang.sin() * amp, ang.cos() * amp], dim=-1)[:, :dim]


class VertexRefiner(nn.Module):
    """
    (image crop, mask crop, K seed points) -> (offset per point, is-corner per point).

    The sequence model is a transformer rather than the circular convolutions
    of Deep Snake / E2EC because the property we need is GLOBAL: opposite walls
    of a building are parallel and adjacent ones perpendicular, and enforcing
    that is a relation between points half the contour apart. A local conv
    stack cannot see it.
    """

    def __init__(self, size=128, k=64, dim=128, layers=3, heads=4,
                 enc_width=48, feat=64, max_shift=0.12):
        super().__init__()
        self.size, self.k, self.max_shift = size, k, max_shift
        self.enc = ImageEncoder(4, enc_width, feat)
        # per-point input: sampled feature + (x, y) + is-original-vertex flag
        self.inp = nn.Linear(feat + 3, dim)
        self.pe = dim
        layer = nn.TransformerEncoderLayer(
            dim, heads, dim * 4, dropout=0.0, batch_first=True,
            norm_first=True, activation="gelu")
        self.tr = nn.TransformerEncoder(layer, layers)
        self.norm = nn.LayerNorm(dim)
        self.off = nn.Linear(dim, 2)
        self.cor = nn.Linear(dim, 1)
        # Start as (very nearly) the IDENTITY TRANSFORM, so an untrained or
        # barely-trained model reproduces regularize() rather than scattering
        # vertices. Two halves to that:
        #
        #   offsets    small-gain weight + zero bias -> ~0.05 px of motion at
        #              init. Small gain and not exactly zero: a zero weight
        #              matrix makes the gradient w.r.t. this module's INPUT
        #              identically zero, so the transformer would receive no
        #              signal through the offset path at all.
        #   corners    the seed's OWN vertices are the prior. regularize()
        #              already picks the right number of them (5.07 mean
        #              against GT's 5.11), so `orig_prior` adds a large
        #              positive logit to points flagged is_orig and the learned
        #              term starts as a small perturbation of that. Without it
        #              an untrained model selects corners from noise, the line
        #              fits span the wrong walls, and vertices land 5.75 px
        #              off a seed it was supposed to reproduce (measured --
        #              this is what selftest [9] caught).
        for lin in (self.off, self.cor):
            nn.init.xavier_uniform_(lin.weight, gain=0.01)
            nn.init.zeros_(lin.bias)
        self.orig_prior = nn.Parameter(torch.tensor(4.0))

    def forward(self, img, mask, pts_n):
        """
        img    (B, 3, S, S)
        mask   (B, 1, S, S)
        pts_n  (B, K, 3)   normalised (x, y) in [-1, 1] plus is_orig flag

        Returns offset (B, K, 2) in NORMALISED units, corner logit (B, K).
        """
        f = self.enc(torch.cat([img, mask], dim=1))          # (B, C, S, S)
        grid = pts_n[..., :2].unsqueeze(1)                   # (B, 1, K, 2)
        # align_corners=True so that -1 and +1 land exactly on the outermost
        # pixel CENTRES, matching the normalisation in refine_polygon(). With
        # False the two disagree by half a pixel at every crop scale, which is
        # the same order as the error being corrected.
        s = F.grid_sample(f, grid, mode="bilinear", align_corners=True,
                          padding_mode="border")
        s = s[:, :, 0].transpose(1, 2)                       # (B, K, C)

        x = self.inp(torch.cat([s, pts_n], dim=-1))
        x = x + cyclic_pe(x.shape[1], x.shape[-1], x.device)[None]
        x = self.norm(self.tr(x))
        # tanh-bounded: an unbounded offset lets one bad point fly off the crop
        # and take the whole line fit with it
        off = self.off(x).tanh() * self.max_shift
        # pts_n[..., 2] is the is_orig flag; see orig_prior in __init__
        logit = self.cor(x).squeeze(-1) + self.orig_prior * pts_n[..., 2]
        return off, logit


# ==========================================================================
# 4. Targets
# ==========================================================================
def build_targets(seed, gt_poly, corner_tol=6.0, snap_radius=8.0):
    """
    Per-seed-point regression and classification targets.

    offset target
        If a GT VERTEX lies within `snap_radius`, aim at that vertex -- we want
        corners to land on corners, not merely on the outline. Otherwise aim at
        the nearest point on the GT BOUNDARY, which fixes the wall position.
        Both are in scene pixels; the caller normalises.

    corner target
        1 if this point is the closest seed point to some GT vertex AND within
        `corner_tol` of it. "Closest seed to a GT vertex" rather than "within
        tol of a GT vertex" because a subdivided edge can put three seed points
        inside the tolerance of one corner, and labelling all three positive
        teaches the model to fire a triple that cyclic_nms then has to guess
        between.

    Returns (target_xy (K, 2), corner (K,) float, valid (K,) bool).
    """
    seed = np.asarray(seed, np.float64)
    g = close_poly(gt_poly)
    k = len(seed)

    tgt = np.zeros((k, 2), np.float64)
    for i, p in enumerate(seed):
        d = np.linalg.norm(g - p, axis=1)
        j = int(np.argmin(d))
        tgt[i] = g[j] if d[j] <= snap_radius else project_to_boundary(p, g)[0]

    corner = np.zeros(k, np.float32)
    for v in g:
        d = np.linalg.norm(seed - v, axis=1)
        i = int(np.argmin(d))
        if d[i] <= corner_tol:
            corner[i] = 1.0
    return tgt, corner, np.ones(k, bool)


def degrade_mask(mask, rng, px=2.8):
    """
    Turn a GT mask into something shaped like a PREDICTED mask.

    Needed because there are no predictions on the train split -- inference has
    only ever been run on val -- and training the refiner on pristine GT masks
    would teach it that its input is already correct.

    Calibrated to the measured v1 error, not invented: mean |boundary offset|
    2.78 px, mean signed offset +0.65 px (very slightly dilated, NOT shrunk),
    and 3.89 deg of angular wobble against GT's 1.12. Reproduced as a smooth
    random displacement field plus a small net dilation bias -- smooth because
    the real error is systematic per-wall, not per-pixel noise, and per-pixel
    noise would be trivially denoised by the conv stack. The displacement field
    produces the angular wobble on its own; an explicit rotation term would
    double-count it.

    Validated against the real thing: target offsets built from degraded GT
    masks average 3.18 px, from real predicted masks 3.27 px. Close, but prefer
    real predictions where you have them (`--masks-dir-*`) -- the synthetic
    version reproduces the error's magnitude and not its correlation with the
    image, and that correlation is the cue the model has to learn.
    """
    h, w = mask.shape
    lo = max(h // 16, 2)
    fy = rng.standard_normal((lo, lo)).astype(np.float32)
    fx = rng.standard_normal((lo, lo)).astype(np.float32)
    fy = cv2.resize(fy, (w, h), interpolation=cv2.INTER_CUBIC)
    fx = cv2.resize(fx, (w, h), interpolation=cv2.INTER_CUBIC)
    s = px / max(float(np.abs(np.stack([fy, fx])).mean()), 1e-6) * 0.8
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    out = cv2.remap(mask.astype(np.uint8), gx + fx * s, gy + fy * s,
                    cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0).astype(bool)
    if rng.random() < 0.5:                      # net +0.65 px, so dilate more often
        out = cv2.dilate(out.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    return out


# ==========================================================================
# 5. Dataset
# ==========================================================================
class VertexDataset(torch.utils.data.Dataset):
    """
    One item per building instance.

    Seeds come from regularize() applied to a mask -- a real predicted mask if
    `masks_dir` has one for this tile, otherwise a degraded GT mask. That is
    the same function used at inference, so the model sees its true input
    distribution rather than a proxy.
    """

    def __init__(self, root, masks_dir=None, size=128, k=64, seed=0,
                 corner_tol=6.0, snap_radius=8.0, min_area=200):
        # NOTE: do NOT stash the pycocotools.mask module on self. A module
        # object cannot be pickled, and DataLoader workers are spawned (not
        # forked) on Windows, so `--workers > 0` died with
        # "TypeError: cannot pickle 'module' object" before any epoch ran --
        # while --workers 0 worked fine and hid it. Import it where it is used.
        from pycocotools.coco import COCO
        self.root = Path(root)
        self.coco = COCO(str(self.root / "annotations.json"))
        self.size, self.k = size, k
        self.corner_tol, self.snap_radius = corner_tol, snap_radius
        self.masks_dir = Path(masks_dir) if masks_dir else None
        self.rng = np.random.default_rng(seed)
        self.items = []
        for iid in sorted(self.coco.imgs):
            for aid in self.coco.getAnnIds(iid, iscrowd=False):
                a = self.coco.anns[aid]
                if a.get("area", 0) >= min_area:
                    self.items.append((iid, aid))
        self._img = {}
        self._npz = {}
        self.min_pred_iou = 0.5
        n_real = sum(1 for iid in self.coco.imgs if self._npz_path(iid))
        print(f"[vertex-data] {root}: {len(self.items)} instances over "
              f"{len(self.coco.imgs)} tiles; real predicted masks for "
              f"{n_real} tiles, degraded GT for the rest")

    def _npz_path(self, iid):
        if self.masks_dir is None:
            return None
        stem = Path(self.coco.imgs[iid]["file_name"]).stem
        p = self.masks_dir / f"{stem}_masks.npz"
        return p if p.exists() else None

    def _pred_mask(self, iid, gt_mask):
        """
        The predicted mask for THIS instance, or None.

        Picks the prediction with the highest IoU against the GT instance and
        requires `min_pred_iou`. Without that floor a missed building would be
        paired with whatever unrelated blob happened to overlap it most, and
        the model would be trained to drag a polygon across the image -- a much
        worse lesson than the synthetic degradation it replaces.
        """
        p = self._npz_path(iid)
        if p is None:
            return None
        if iid not in self._npz:
            z = np.load(p)
            H, W = (int(v) for v in z["shape"])
            b = z["boxes"]
            ms = []
            for i in range(len(z["scores"])):
                m = np.zeros((H, W), bool)
                m[int(b[i][1]):int(b[i][3]), int(b[i][0]):int(b[i][2])] = z[f"m{i}"]
                ms.append(m)
            self._npz[iid] = ms
        best, bi = 0.0, -1
        for i, m in enumerate(self._npz[iid]):
            u = (m | gt_mask).sum()
            v = (m & gt_mask).sum() / u if u else 0.0
            if v > best:
                best, bi = v, i
        return self._npz[iid][bi] if best >= self.min_pred_iou else None

    def __len__(self):
        return len(self.items)

    def _image(self, iid):
        if iid not in self._img:
            fn = self.coco.imgs[iid]["file_name"]
            im = cv2.imread(str(self.root / "images" / fn), cv2.IMREAD_COLOR)
            self._img[iid] = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        return self._img[iid]

    def _gt(self, a, H, W):
        from pycocotools import mask as maskutil
        s = a["segmentation"]
        if isinstance(s, str):
            s = json.loads(s)
        m = maskutil.decode(maskutil.merge(
            maskutil.frPyObjects(s, H, W))).astype(bool)
        # The GT polygon, not a re-traced mask contour: retracing would bake in
        # the rasterisation error that regularize()'s 1.10 px oracle floor is
        # already partly made of.
        polys = [np.array(p, np.float64).reshape(-1, 2) for p in s]
        return m, max(polys, key=len)

    def __getitem__(self, i):
        iid, aid = self.items[i]
        info = self.coco.imgs[iid]
        H, W = info["height"], info["width"]
        a = self.coco.anns[aid]
        gm, gpoly = self._gt(a, H, W)

        # A real predicted mask when one exists, otherwise a degraded GT mask.
        # Real is strictly better -- the synthetic degradation reproduces the
        # measured error MAGNITUDE but not its correlation with the image (a
        # mask is wrong precisely where the roof edge is ambiguous, and that is
        # exactly the cue this model has to learn to use).
        src = self._pred_mask(iid, gm)
        if src is None:
            src = degrade_mask(gm, self.rng)
        ys, xs = np.nonzero(src)
        if len(ys) < 16:
            src, ys, xs = gm, *np.nonzero(gm)
        y0, x0 = int(ys.min()), int(xs.min())
        crop = src[y0:int(ys.max()) + 1, x0:int(xs.max()) + 1]
        seed_local = regularize(crop)
        if seed_local is None or len(close_poly(seed_local)) < 3:
            seed_local = np.array([[0, 0], [crop.shape[1] - 1, 0],
                                   [crop.shape[1] - 1, crop.shape[0] - 1],
                                   [0, crop.shape[0] - 1]], np.float64)
        seed = close_poly(seed_local) + np.array([x0, y0], np.float64)

        pts, is_orig = subdivide_to(seed, self.k)
        if pts is None:
            pts, is_orig = seed, np.ones(len(seed), bool)
        tgt, corner, _ = build_targets(pts, gpoly, self.corner_tol,
                                       self.snap_radius)

        cx0, cy0, sc = crop_box(seed, (H, W), self.size)
        img, mk = sample_crop(self._image(iid), src, cx0, cy0, sc, self.size)

        def to_n(p):
            q = (np.asarray(p, np.float64) - np.array([cx0, cy0])) * sc
            return q / (self.size - 1) * 2.0 - 1.0

        pn, tn = to_n(pts), to_n(tgt)
        n = len(pn)
        return {
            "img": torch.from_numpy(img),
            "mask": torch.from_numpy(mk),
            "pts": torch.from_numpy(np.concatenate(
                [pn, is_orig[:, None].astype(np.float64)], 1).astype(np.float32)),
            "tgt_off": torch.from_numpy((tn - pn).astype(np.float32)),
            "corner": torch.from_numpy(corner),
            "n": n,
        }


def collate(batch, k):
    """
    Pad every sequence to k and carry a mask.

    A polygon with more than k vertices exists (GT max is 51) and is truncated
    rather than dropped; `pad` keeps the loss off the padding either way, so a
    short sequence costs nothing but never contributes phantom corners.
    """
    B = len(batch)
    out = {
        "img": torch.stack([b["img"] for b in batch]),
        "mask": torch.stack([b["mask"] for b in batch]),
        "pts": torch.zeros(B, k, 3),
        "tgt_off": torch.zeros(B, k, 2),
        "corner": torch.zeros(B, k),
        "pad": torch.zeros(B, k, dtype=torch.bool),
    }
    for i, b in enumerate(batch):
        n = min(b["n"], k)
        out["pts"][i, :n] = b["pts"][:n]
        out["tgt_off"][i, :n] = b["tgt_off"][:n]
        out["corner"][i, :n] = b["corner"][:n]
        out["pad"][i, :n] = True
    return out


# ==========================================================================
# 6. Inference
# ==========================================================================
@torch.no_grad()
def refine_polygon(model, img, mask, seed_poly, device="cpu", k=64, size=128,
                   corner_thr=0.5, min_gap=2, min_iou=0.80):
    """
    One instance: seed polygon -> refined polygon (scene coordinates).

    Returns (polygon, info). Falls back to `seed_poly` whenever the refinement
    cannot be trusted, and says why in info["fallback"]:

    The IoU guard is the load-bearing part. This stage runs on top of a
    pipeline that already reaches 0.814 against GT, so the only unacceptable
    outcome is making an instance worse. Accepting the refinement only when it
    still agrees with the mask it came from keeps the stage monotonic in the
    aggregate -- the same discipline polygonize_scene() already applies to
    regularize().
    """
    H, W = mask.shape
    seed = close_poly(seed_poly)
    if len(seed) < 3:
        return seed, {"fallback": "seed<3"}

    pts, is_orig = subdivide_to(seed, k)
    if pts is None:
        return seed, {"fallback": "subdivide"}
    n = min(len(pts), k)
    pts, is_orig = pts[:n], is_orig[:n]

    x0, y0, sc = crop_box(seed, (H, W), size)
    im, mk = sample_crop(img, mask, x0, y0, sc, size)
    pn = ((pts - np.array([x0, y0])) * sc) / (size - 1) * 2.0 - 1.0
    feat = np.concatenate([pn, is_orig[:, None].astype(np.float64)], 1)

    off, logit = model(
        torch.from_numpy(im)[None].to(device),
        torch.from_numpy(mk)[None].to(device),
        torch.from_numpy(feat.astype(np.float32))[None].to(device))
    off = off[0, :n].float().cpu().numpy().astype(np.float64)
    prob = torch.sigmoid(logit[0, :n]).float().cpu().numpy()

    refined = (pn + off + 1.0) / 2.0 * (size - 1) / sc + np.array([x0, y0])

    idx = cyclic_nms(prob, corner_thr, min_gap)
    if len(idx) < 3:
        # Nothing confident enough to be a corner. The seed's own vertices are
        # a sound second opinion -- they are what regularize() decided.
        idx = [i for i in range(n) if is_orig[i]]
    if len(idx) < 3:
        return seed, {"fallback": "corners<3"}

    poly = polygon_from_points(refined, idx)
    if poly is None:
        return seed, {"fallback": "degenerate"}

    def miou(p):
        c = np.zeros((H, W), np.uint8)
        cv2.fillPoly(c, [np.round(p).astype(np.int32)], 1)
        c = c.astype(bool)
        u = (c | mask).sum()
        return float((c & mask).sum() / u) if u else 0.0

    v_new, v_old = miou(poly), miou(seed)
    if v_new < min_iou and v_new < v_old:
        return seed, {"fallback": f"iou {v_new:.3f}<{min_iou}", "iou": v_new}
    return poly, {"fallback": None, "iou": v_new, "iou_seed": v_old,
                  "n_corners": len(idx)}


# ==========================================================================
# 7. Train / apply / selftest
# ==========================================================================
def loss_fn(off, logit, batch, corner_weight=1.0, pos_weight=8.0):
    """
    Smooth-L1 on offsets + BCE on corner-ness.

    Smooth-L1, not L2: the snap_radius rule in build_targets() produces a small
    number of large targets when regularize() put a vertex far from any GT
    corner, and L2 would let those dominate a batch whose typical target is
    ~1 px.

    pos_weight because corners are rare by construction -- ~5 of 64 points, so
    an unweighted BCE is 92% satisfied by predicting "never a corner".
    """
    pad = batch["pad"]
    if not bool(pad.any()):
        return off.sum() * 0.0, {}
    l_off = F.smooth_l1_loss(off[pad], batch["tgt_off"][pad], beta=0.02)
    l_cor = F.binary_cross_entropy_with_logits(
        logit[pad], batch["corner"][pad],
        pos_weight=torch.tensor(pos_weight, device=off.device))
    return l_off + corner_weight * l_cor, {
        "off": float(l_off), "cor": float(l_cor)}


def cmd_train(a):
    from torch.utils.data import DataLoader
    from tqdm.auto import tqdm
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    root = Path(a.data_root)
    tr = VertexDataset(root / "train", a.masks_dir_train, a.size, a.k, seed=0)
    va = VertexDataset(root / "val", a.masks_dir_val, a.size, a.k, seed=1)
    # functools.partial, not a lambda: DataLoader pickles collate_fn to send
    # it to spawned workers, and a lambda defined inside cmd_train is not
    # picklable ("Can't pickle local object"). Same Windows-spawn class of bug
    # as the module attribute in VertexDataset.
    col = partial(collate, k=a.k)
    tl = DataLoader(tr, batch_size=a.batch_size, shuffle=True, num_workers=a.workers,
                    collate_fn=col, drop_last=True)
    vl = DataLoader(va, batch_size=a.batch_size, shuffle=False,
                    num_workers=a.workers, collate_fn=col)

    model = VertexRefiner(a.size, a.k, a.dim, a.layers, max_shift=a.max_shift).to(dev)
    print(f"[vertex] params {sum(p.numel() for p in model.parameters())/1e6:.2f}M")
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=a.lr, total_steps=a.epochs * max(len(tl), 1), pct_start=0.15)
    fresh_run_dir(a.out)

    # `seeds_*` is the one setting you cannot recover from the checkpoint and
    # which changes what the model learned: real predicted masks or the
    # synthetic degradation. Record it explicitly.
    cfg_path = save_run_config(a.out, a, derived={
        "device": dev,
        "params_M": round(sum(p.numel() for p in model.parameters()) / 1e6, 3),
        "instances_train": len(tr), "instances_val": len(va),
        "steps_per_epoch": len(tl),
        "total_steps": a.epochs * max(len(tl), 1),
        "seeds_train": "real predicted masks" if a.masks_dir_train
                       else "degraded GT masks (synthetic)",
        "seeds_val": "real predicted masks" if a.masks_dir_val
                     else "degraded GT masks (synthetic)",
        "max_shift_crop_px": round(a.max_shift * (a.size - 1) / 2.0, 2),
    })
    print(f"[run] config -> {cfg_path}")

    best, best_ep = float("inf"), None
    for ep in range(a.epochs):
        t_ep = time.time()
        model.train()
        run = {}
        for batch in tqdm(tl, desc=f"ep {ep+1}/{a.epochs}", leave=False):
            batch = {kk: (v.to(dev) if torch.is_tensor(v) else v)
                     for kk, v in batch.items()}
            opt.zero_grad(set_to_none=True)
            off, logit = model(batch["img"], batch["mask"], batch["pts"])
            loss, parts = loss_fn(off, logit, batch, a.corner_weight)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            for kk, v in parts.items():
                run[kk] = run.get(kk, 0.0) + v
        model.eval()
        vl_sum, vpx, vn = {}, 0.0, 0
        with torch.no_grad():
            for batch in vl:
                batch = {kk: (v.to(dev) if torch.is_tensor(v) else v)
                         for kk, v in batch.items()}
                off, logit = model(batch["img"], batch["mask"], batch["pts"])
                _, parts = loss_fn(off, logit, batch, a.corner_weight)
                for kk, v in parts.items():
                    vl_sum[kk] = vl_sum.get(kk, 0.0) + v
                # residual in CROP PIXELS, the only number here that is
                # directly comparable to the 3.94 px the pipeline starts from
                pad = batch["pad"]
                r = (off - batch["tgt_off"])[pad].abs().mean(-1) * (a.size - 1) / 2.0
                vpx += float(r.mean()); vn += 1
        nb = max(len(tl), 1); nv = max(len(vl), 1)
        vpx /= max(vn, 1)
        msg = (f"[ep {ep+1}/{a.epochs}] "
               + "  ".join(f"tr_{kk} {v/nb:.4f}" for kk, v in run.items())
               + "  " + "  ".join(f"va_{kk} {v/nv:.4f}" for kk, v in vl_sum.items())
               + f"  va_resid {vpx:.2f}px")
        tot = sum(vl_sum.values()) / nv
        improved = tot < best            # evaluate BEFORE `best` is updated
        payload = {"model": model.state_dict(),
                   "cfg": {"size": a.size, "k": a.k, "dim": a.dim,
                           "layers": a.layers, "max_shift": a.max_shift},
                   "epoch": ep + 1,          # 1-based, matching the log line
                   "val": tot}
        # final epoch only -- see the note in train_dinov3_mask2former.py
        last_path = (save_ckpt(a.out, "last", ep + 1, payload)
                     if ep + 1 == a.epochs else None)
        best_path = None
        if improved:
            best, best_ep = tot, ep + 1
            best_path = save_ckpt(a.out, "best", ep + 1, payload)
            msg += "  *"
        print(msg)
        append_loss_row(a.out, {
            "epoch": ep + 1,
            "val": tot,
            **{f"tr_{kk}": v / nb for kk, v in run.items()},
            **{f"va_{kk}": v / nv for kk, v in vl_sum.items()},
            "va_resid_px": vpx,
            "lr": sched.get_last_lr()[0],
            "is_best": improved,
            "secs": round(time.time() - t_ep, 1),
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        # every epoch, so a killed run still has a record -- see save_run_config
        save_run_config(a.out, a, result={
            "epochs_completed": ep + 1,
            "best_val": best, "best_epoch": best_ep,
            "best_ckpt": (best_path or Path(a.out) /
                          f"best_ep{best_ep:02d}.pth").name,
            "last_ckpt": last_path.name if last_path else None,
            "last_val_resid_crop_px": vpx,
            **{f"last_va_{kk}": v / nv for kk, v in vl_sum.items()},
        })

    save_run_config(a.out, a, result={"finished": True})
    print(f"[done] best val {best:.4f} at epoch {best_ep} -> "
          f"{Path(a.out)/f'best_ep{best_ep:02d}.pth'}")
    print(f"[done] run config -> {Path(a.out)/'run_config.json'}")
    print(f"[done] apply/bench with:  --ckpt {a.out}")


def load_refiner(ckpt, device="cpu", prefer="best"):
    ck = torch.load(resolve_ckpt(ckpt, prefer=prefer),
                    map_location="cpu", weights_only=False)
    c = ck.get("cfg", {})
    m = VertexRefiner(c.get("size", 128), c.get("k", 64), c.get("dim", 128),
                      c.get("layers", 3), max_shift=c.get("max_shift", 0.12))
    missing, unexpected = m.load_state_dict(ck["model"], strict=False)
    if missing or unexpected:
        raise SystemExit(f"[fatal] vertex ckpt mismatch: missing={list(missing)[:4]} "
                         f"unexpected={list(unexpected)[:4]}")
    return m.to(device).eval(), c


def load_seeds(seeds_dir, stem, masks, shape):
    """
    Seed polygons from a polygonize.py run, paired to masks BY IoU.

    Why take seeds from polygonize.py at all rather than calling regularize()
    here: polygonize_scene() first runs partition(), which makes the instance
    masks disjoint. Buildings cannot physically overlap, and that step is worth
    0.417 -> 0.487 IoU on the instances it touches (see partition's docstring).
    Re-deriving seeds from the raw npz here would silently throw that away.

    Paired by IoU and NOT by list index: polygonize_scene() goes out of its way
    to stay index-aligned with the npz, but it can still `continue` past an
    instance below --min-area or whose fallback returns None, and a single skip
    shifts every later index. Matching by overlap cannot desynchronise.
    """
    p = Path(seeds_dir) / f"{stem}_polys.json"
    if not p.exists():
        return None
    recs = json.loads(p.read_text()).get("polygons", [])
    H, W = shape
    out = [None] * len(masks)
    for r in recs:
        poly = close_poly(np.array(r["polygon"], np.float64))
        if len(poly) < 3:
            continue
        c = np.zeros((H, W), np.uint8)
        cv2.fillPoly(c, [np.round(poly).astype(np.int32)], 1)
        c = c.astype(bool)
        best, bi = 0.0, -1
        for i, m in enumerate(masks):
            if out[i] is not None:
                continue
            u = (c | m).sum()
            v = (c & m).sum() / u if u else 0.0
            if v > best:
                best, bi = v, i
        if bi >= 0 and best >= 0.5:
            out[bi] = poly
    return out


def cmd_apply(a):
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, cfg = load_refiner(a.ckpt, dev, a.ckpt_tag)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    files = sorted(Path(a.masks).glob("*_masks.npz"))
    if not files:
        raise SystemExit(f"no *_masks.npz in {a.masks}")
    n_ref = n_fb = 0
    for f in files:
        stem = f.stem[:-6]
        ip = Path(a.images) / f"{stem}.png"
        if not ip.exists():
            print(f"  [skip] no image for {stem}")
            continue
        img = cv2.cvtColor(cv2.imread(str(ip), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        z = np.load(f)
        H, W = (int(v) for v in z["shape"])
        b, sc = z["boxes"], z["scores"]
        masks = []
        for i in range(len(sc)):
            m = np.zeros((H, W), bool)
            m[int(b[i][1]):int(b[i][3]), int(b[i][0]):int(b[i][2])] = z[f"m{i}"]
            masks.append(m)
        seeds = load_seeds(a.seeds, stem, masks, (H, W)) if a.seeds else None
        recs = []
        for i in range(len(sc)):
            m = masks[i]
            if m.sum() < a.min_area:
                continue
            if seeds is not None:
                seed = seeds[i]
                if seed is None:      # polygonize.py dropped this instance
                    continue
            else:
                ys, xs = np.nonzero(m)
                y0, x0 = int(ys.min()), int(xs.min())
                seed = regularize(m[y0:int(ys.max()) + 1, x0:int(xs.max()) + 1])
                if seed is None:
                    continue
                seed = close_poly(seed) + np.array([x0, y0], np.float64)
            poly, info = refine_polygon(model, img, m, seed, dev,
                                        cfg.get("k", 64), cfg.get("size", 128),
                                        a.corner_thr, a.min_gap, a.min_iou)
            if info["fallback"]:
                n_fb += 1
            else:
                n_ref += 1
            recs.append({"polygon": np.asarray(poly).tolist(),
                         "score": float(sc[i]),
                         "n_vertices": int(len(poly)),
                         "refined": info["fallback"] is None,
                         "fallback": info["fallback"]})
        (out / f"{stem}_polys.json").write_text(
            json.dumps({"shape": [H, W], "polygons": recs}))
        print(f"  {stem}: {len(recs)} polygons")
    print(f"[done] refined {n_ref}, fell back {n_fb} "
          f"({n_fb/max(n_ref+n_fb,1):.0%})  -> {out}")


def cmd_bench(a):
    """
    Score polygons against GT VERTICES, which is the number this whole stage
    exists to move and the one no mask metric reports.

    Reports, for seed (regularize alone) and refined side by side:
      corner error   per GT vertex, distance to the nearest polygon vertex
      angular dev    weighted mean deviation of edges from the polygon's own
                     dominant axes -- the rectilinearity number
      mask IoU       polygon against the GT mask, so a corner gain that costs
                     area is visible rather than hidden

    The reference points, measured on v1:
        current pipeline                    mean 9.03 px, p50 3.94, <2px 24%
        regularize() on a PERFECT GT mask   mean 2.68 px, p50 1.10, <2px 84%
    The second is the ceiling for anything that reads only the mask. Beating it
    is the whole claim of an image-conditioned head; not beating the first
    means this stage should stay switched off.
    """
    from pycocotools.coco import COCO
    from pycocotools import mask as maskutil
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, cfg = load_refiner(a.ckpt, dev, a.ckpt_tag)
    root = Path(a.data_root)
    coco = COCO(str(root / "annotations.json"))

    def angdev(p):
        p = close_poly(p)
        v = np.roll(p, -1, 0) - p
        L = np.linalg.norm(v, axis=1)
        k = L > 4
        if k.sum() < 3:
            return None
        th = cv2.minAreaRect(p.astype(np.float32))[2]
        aa = np.degrees(np.arctan2(v[k, 1], v[k, 0])) - th
        return float(np.average(np.abs(((aa + 45) % 90) - 45), weights=L[k]))

    acc = {k: [] for k in ("seed_err", "ref_err", "seed_ang", "ref_ang",
                           "seed_iou", "ref_iou")}
    n_fb = n_ok = 0
    for iid in sorted(coco.imgs):
        info = coco.imgs[iid]
        H, W = info["height"], info["width"]
        f = Path(a.masks) / f"{Path(info['file_name']).stem}_masks.npz"
        ip = root / "images" / info["file_name"]
        if not (f.exists() and ip.exists()):
            continue
        img = cv2.cvtColor(cv2.imread(str(ip), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        gts = []
        for aid in coco.getAnnIds(iid, iscrowd=False):
            s = coco.anns[aid]["segmentation"]
            if isinstance(s, str):
                s = json.loads(s)
            gm = maskutil.decode(maskutil.merge(
                maskutil.frPyObjects(s, H, W))).astype(bool)
            gts.append((gm, close_poly(max(
                [np.array(p, np.float64).reshape(-1, 2) for p in s], key=len))))
        z = np.load(f)
        b, sc = z["boxes"], z["scores"]
        masks = []
        for i in range(len(sc)):
            m = np.zeros((H, W), bool)
            m[int(b[i][1]):int(b[i][3]), int(b[i][0]):int(b[i][2])] = z[f"m{i}"]
            masks.append(m)
        seeds = load_seeds(a.seeds, Path(info["file_name"]).stem, masks,
                           (H, W)) if a.seeds else None
        for i in range(len(sc)):
            m = masks[i]
            if m.sum() < a.min_area:
                continue
            # Only matched instances: corner error against an unmatched
            # prediction measures detection, not vertex accuracy.
            best, bi = 0.0, -1
            for j, (gm, _) in enumerate(gts):
                u = (m | gm).sum()
                v = (m & gm).sum() / u if u else 0.0
                if v > best:
                    best, bi = v, j
            if best < 0.5:
                continue
            if seeds is not None:
                seed = seeds[i]
                if seed is None:
                    continue
            else:
                ys, xs = np.nonzero(m)
                y0, x0 = int(ys.min()), int(xs.min())
                seed = regularize(m[y0:int(ys.max()) + 1, x0:int(xs.max()) + 1])
                if seed is None:
                    continue
                seed = close_poly(seed) + np.array([x0, y0], np.float64)
            ref, info_r = refine_polygon(model, img, m, seed, dev,
                                         cfg.get("k", 64), cfg.get("size", 128),
                                         a.corner_thr, a.min_gap, a.min_iou)
            if info_r["fallback"]:
                n_fb += 1
            else:
                n_ok += 1
            gpoly = gts[bi][1]
            for tag, poly in (("seed", seed), ("ref", np.asarray(ref))):
                acc[f"{tag}_err"] += [float(np.min(np.linalg.norm(poly - v, axis=1)))
                                      for v in gpoly]
                d = angdev(poly)
                if d is not None:
                    acc[f"{tag}_ang"].append(d)
                c = np.zeros((H, W), np.uint8)
                cv2.fillPoly(c, [np.round(poly).astype(np.int32)], 1)
                c = c.astype(bool)
                u = (c | gts[bi][0]).sum()
                acc[f"{tag}_iou"].append(float((c & gts[bi][0]).sum() / u) if u else 0.0)

    def row(tag):
        e = np.array(acc[f"{tag}_err"])
        return (f"  {tag:8s} corner err mean {e.mean():6.2f}  p50 {np.percentile(e,50):5.2f}"
                f"  <2px {np.mean(e<2):4.0%}  <4px {np.mean(e<4):4.0%}"
                f"   ang {np.mean(acc[f'{tag}_ang']):5.2f}deg"
                f"   maskIoU {np.mean(acc[f'{tag}_iou']):.4f}")
    print(f"\nmatched instances: {n_ok + n_fb}   refined {n_ok}, "
          f"fell back {n_fb} ({n_fb/max(n_ok+n_fb,1):.0%})")
    print(f"  GT vertices scored: {len(acc['seed_err'])}")
    print(row("seed"))
    print(row("ref"))
    print("  ---- reference points, v1 -------------------------------")
    print("  pipeline   corner err mean   9.03  p50  3.94  <2px  24%  <4px  51%")
    print("  GT-mask    corner err mean   2.68  p50  1.10  <2px  84%  <4px  90%"
          "   <- mask-only ceiling")


def cmd_selftest(a):
    """Geometry and model checks with answers known from construction."""
    fails = []

    def ck(name, cond, detail=""):
        ok = bool(cond)
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
        if not ok:
            fails.append(name)

    print("\n[1] subdivide_to")
    sq = np.array([[0, 0], [40, 0], [40, 20], [0, 20]], np.float64)
    p, o = subdivide_to(sq, 16)
    ck("returns exactly k", len(p) == 16, str(len(p)))
    ck("keeps all originals", int(o.sum()) == 4, f"{int(o.sum())} flagged")
    ck("originals are the square's corners",
       all(np.isclose(p[o][i], sq[i]).all() for i in range(4)))
    ck("all points on the boundary",
       max(project_to_boundary(q, sq)[1] for q in p) < 1e-9)
    ck("long edges get more points",
       (o.cumsum() == 1).sum() > (o.cumsum() == 2).sum(),
       "40px edge vs 20px edge")

    print("\n[2] line fit + intersect (the straightness guarantee)")
    noisy = np.array([[0, 0.3], [10, -0.2], [20, 0.1], [30, -0.1]], np.float64)
    n_, c_ = fit_line(noisy)
    ck("fits a near-horizontal line", abs(n_[0]) < 0.05, f"normal {n_.round(3)}")
    v = fit_line(np.array([[5., 0], [5., 10], [5., 20]]))
    ck("handles a VERTICAL wall (slope form would blow up)",
       v is not None and abs(abs(v[0][0]) - 1.0) < 1e-6, f"normal {v[0].round(3)}")
    ck("parallel lines do not intersect",
       intersect_lines(fit_line(np.array([[0., 0], [1, 0]])),
                       fit_line(np.array([[0., 5], [1, 5]]))) is None)
    x = intersect_lines(fit_line(np.array([[0., 0], [1, 0]])),
                        fit_line(np.array([[3., 0], [3, 1]])))
    ck("perpendicular lines meet at the corner",
       x is not None and np.allclose(x, [3, 0], atol=1e-6), str(np.round(x, 3)))

    print("\n[3] polygon_from_points -- exact rectilinearity from noisy points")
    rng = np.random.default_rng(0)
    pts, orig = subdivide_to(sq, 32)
    jit = pts + rng.normal(0, 0.6, pts.shape)          # wobble like a real mask
    idx = [i for i in range(len(pts)) if orig[i]]
    poly = polygon_from_points(jit, idx)
    ck("recovers 4 vertices", poly is not None and len(poly) == 4,
       str(None if poly is None else len(poly)))

    def dev(p):
        p = close_poly(p)
        vv = np.roll(p, -1, 0) - p
        th = cv2.minAreaRect(p.astype(np.float32))[2]
        aa = np.degrees(np.arctan2(vv[:, 1], vv[:, 0])) - th
        L = np.linalg.norm(vv, axis=1)
        return float(np.average(np.abs(((aa + 45) % 90) - 45), weights=L))
    ck("edges are essentially exactly straight/square", dev(poly) < 0.6,
       f"{dev(poly):.3f} deg (GT is 0.84, raw masks 3.89)")
    ck("corners land near the truth",
       max(np.min(np.linalg.norm(poly - v, axis=1)) for v in sq) < 1.2,
       f"max {max(np.min(np.linalg.norm(poly-v,axis=1)) for v in sq):.3f} px")

    print("\n[4] cyclic_nms")
    s = np.zeros(20); s[[0, 1, 10, 19]] = [0.9, 0.8, 0.95, 0.85]
    keep = cyclic_nms(s, 0.5, 3)
    ck("suppresses index 19 next to index 0 across the seam",
       not (0 in keep and 19 in keep), str(keep))
    ck("keeps the distant peak", 10 in keep, str(keep))
    ck("thresholds", cyclic_nms(np.full(10, 0.1), 0.5, 2) == [])

    print("\n[5] build_targets")
    gt = np.array([[0, 0], [40, 0], [40, 20], [0, 20]], np.float64)
    seed = gt + np.array([2.0, 1.0])                    # whole polygon offset
    sp, so = subdivide_to(seed, 24)
    tg, cor, _ = build_targets(sp, gt)
    ck("exactly 4 corners labelled", int(cor.sum()) == 4, f"{int(cor.sum())}")
    ck("every target lies ON the GT boundary",
       max(project_to_boundary(t, gt)[1] for t in tg) < 1e-9,
       f"max off-boundary {max(project_to_boundary(t, gt)[1] for t in tg):.2e} px")
    shift = float(np.linalg.norm([2.0, 1.0]))
    moved = np.linalg.norm(tg - sp, axis=1).mean()
    ck("targets move each seed point by about the injected shift",
       abs(moved - shift) < 0.6 * shift, f"{moved:.2f} px vs shift {shift:.2f}")
    ck("corner targets are exact GT vertices",
       max(np.min(np.linalg.norm(gt - t, axis=1)) for t in tg[cor > 0]) < 1e-9)
    far = np.array([[0, 0], [4, 0], [4, 4], [0, 4]], np.float64)
    _, cf, _ = build_targets(*[subdivide_to(far + 50, 12)[0], gt][:2])
    ck("no corners when the seed is nowhere near GT", int(cf.sum()) == 0,
       f"{int(cf.sum())}")

    print("\n[6] crop geometry round-trip")
    S = 128
    x0, y0, sc = crop_box(sq + 100, (512, 512), S)
    q = (sq + 100 - np.array([x0, y0])) * sc
    ck("crop contains the polygon", q.min() > 0 and q.max() < S,
       f"[{q.min():.1f}, {q.max():.1f}] in [0, {S}]")
    back = q / sc + np.array([x0, y0])
    ck("scene -> crop -> scene is exact", np.abs(back - (sq + 100)).max() < 1e-9,
       f"max err {np.abs(back-(sq+100)).max():.2e}")
    ck("scale is isotropic (angles preserved)", np.isscalar(sc) or sc.size == 1)

    print("\n[7] model")
    torch.manual_seed(0)
    K = 32
    m = VertexRefiner(size=64, k=K, dim=64, layers=2, heads=4)
    im = torch.randn(2, 3, 64, 64); mk = torch.rand(2, 1, 64, 64)
    pn = torch.rand(2, K, 3) * 2 - 1
    off, lg = m(im, mk, pn)
    ck("offset shape", off.shape == (2, K, 2), str(tuple(off.shape)))
    ck("logit shape", lg.shape == (2, K), str(tuple(lg.shape)))
    # near-identity, not exactly-identity: see the init comment in __init__
    px_move = float(off.abs().max()) * (64 - 1) / 2.0
    ck("offset starts within a fraction of a pixel (near-identity init)",
       px_move < 0.2, f"{px_move:.4f} crop px")
    ck("offset is bounded by max_shift",
       float(off.abs().max()) <= m.max_shift + 1e-6)
    pn_flag = pn.clone()
    pn_flag[:, ::8, 2] = 1.0; pn_flag[:, [i for i in range(K) if i % 8], 2] = -1.0
    _, lg2 = m(im, mk, pn_flag)
    ck("is_orig points get a much higher corner logit at init",
       float(lg2[:, ::8].mean()) - float(lg2[:, 1::8].mean()) > 4.0,
       f"orig {float(lg2[:, ::8].mean()):.2f} vs sub {float(lg2[:, 1::8].mean()):.2f}")
    ck("corner probs are unsaturated (trainable)",
       0.0 < float(torch.sigmoid(lg).min()) and float(torch.sigmoid(lg).max()) < 1.0)
    ck("all finite", bool(torch.isfinite(off).all() and torch.isfinite(lg).all()))
    # cyclic PE must actually be cyclic
    pe = cyclic_pe(16, 64, torch.device("cpu"))
    d_adj = float((pe[0] - pe[1]).norm())
    d_seam = float((pe[0] - pe[15]).norm())
    ck("PE treats index 0 and k-1 as neighbours",
       abs(d_adj - d_seam) < 0.2 * max(d_adj, 1e-6),
       f"adjacent {d_adj:.3f} vs seam {d_seam:.3f}")
    d_opp = float((pe[0] - pe[8]).norm())
    ck("PE distance grows with cyclic separation", d_opp > 2.0 * d_adj,
       f"opposite {d_opp:.3f} vs adjacent {d_adj:.3f} (ratio {d_opp/d_adj:.2f})")
    ck("PE is monotone in separation",
       all(float((pe[0] - pe[j]).norm()) <= float((pe[0] - pe[j + 1]).norm()) + 1e-4
           for j in range(1, 8)))
    # it must be able to learn a constant shift
    tgt = torch.full((2, K, 2), 0.03)
    o2 = torch.optim.Adam(m.parameters(), lr=3e-3)
    for _ in range(250):
        o2.zero_grad()
        a_, _ = m(im, mk, pn)
        l = F.mse_loss(a_, tgt); l.backward(); o2.step()
    ck("learns a known offset", float(l) < 1e-4, f"MSE {float(l):.2e}")

    print("\n[8] degrade_mask matches the measured error profile")
    rng = np.random.default_rng(0)
    base = np.zeros((120, 120), bool); base[30:90, 30:90] = True
    offs, ious = [], []
    for _ in range(40):
        dg = degrade_mask(base, rng)
        ious.append((base & dg).sum() / max((base | dg).sum(), 1))
        dt_i = cv2.distanceTransform(dg.astype(np.uint8), cv2.DIST_L2, 5)
        dt_o = cv2.distanceTransform((~dg).astype(np.uint8), cv2.DIST_L2, 5)
        cs, _ = cv2.findContours(base.astype(np.uint8), cv2.RETR_EXTERNAL,
                                 cv2.CHAIN_APPROX_NONE)
        pp = np.concatenate([c[:, 0, :] for c in cs])
        offs.append(np.abs((dt_o - dt_i)[pp[:, 1], pp[:, 0]]).mean())
    mo, mi = float(np.mean(offs)), float(np.mean(ious))
    ck("mean |boundary offset| is in the measured ballpark (v1: 2.78px)",
       1.0 < mo < 6.0, f"{mo:.2f} px")
    ck("degraded mask still resembles the original (v1 mask-vs-GT 0.817)",
       0.65 < mi < 0.97, f"IoU {mi:.3f}")
    ck("degradation is not the identity", mo > 0.3)

    print("\n[9] refine_polygon fallbacks (must never crash or worsen)")
    img = (np.random.default_rng(0).random((256, 256, 3)) * 255).astype(np.uint8)
    msk = np.zeros((256, 256), bool); msk[60:140, 50:150] = True
    sd = np.array([[50., 60], [150, 60], [150, 140], [50, 140]])
    m2 = VertexRefiner(size=64, k=32, dim=64, layers=2)
    pol, info = refine_polygon(m2, img, msk, sd, k=32, size=64)
    ck("returns a polygon", pol is not None and len(pol) >= 3,
       f"{len(pol)} verts, fallback={info['fallback']}")
    ck("identity-init model reproduces the seed closely",
       max(np.min(np.linalg.norm(np.asarray(pol) - v, axis=1)) for v in sd) < 2.0,
       f"max corner move {max(np.min(np.linalg.norm(np.asarray(pol)-v,axis=1)) for v in sd):.2f} px")
    p2, i2 = refine_polygon(m2, img, msk, sd[:2], k=32, size=64)
    ck("degenerate seed falls back, does not raise", i2["fallback"] is not None,
       str(i2["fallback"]))

    print("\n" + "=" * 62)
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        raise SystemExit(1)
    print("all vertex checks passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("train")
    t.add_argument("--data-root", required=True)
    t.add_argument("--masks-dir-train", default=None,
                   help="folder of *_masks.npz for the TRAIN tiles. Strongly "
                        "preferred over the synthetic degradation: it is the "
                        "real input distribution. Run infer.py on the train "
                        "images once to produce it.")
    t.add_argument("--masks-dir-val", default=None)
    t.add_argument("--size", type=int, default=128,
                   help="crop resolution. This is the model's spatial budget "
                        "for sub-pixel corner localisation -- do not lower it "
                        "to save time.")
    t.add_argument("--k", type=int, default=64,
                   # '%%' not '%': argparse expands help through `help % params`
                   help="contour sample points. GT polygons have <=6 vertices "
                        "79%% of the time, so 64 is generous; it buys "
                        "resolution for the line fits, not vertex capacity.")
    t.add_argument("--dim", type=int, default=128)
    t.add_argument("--layers", type=int, default=3)
    t.add_argument("--max-shift", type=float, default=0.12,
                   help="offset bound in normalised crop units. 0.12 at "
                        "size 128 is ~7.7 crop px, comfortably above the "
                        "3.94 px median error being corrected.")
    t.add_argument("--corner-weight", type=float, default=1.0)
    t.add_argument("--epochs", type=int, default=40)
    t.add_argument("--batch-size", type=int, default=32)
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--lr", type=float, default=3e-4)
    t.add_argument("--out", default="./runs/vertex")
    t.set_defaults(func=cmd_train)

    p = sub.add_parser("apply")
    p.add_argument("--ckpt", required=True,
                   help="checkpoint file, or a run directory")
    p.add_argument("--ckpt-tag", choices=["best", "last", "snap"], default="best",
                   help="which of the two rolling checkpoints to load when --ckpt is a RUN DIRECTORY: best (lowest val loss) or last (final epoch). Ignored when --ckpt names a file.")
    p.add_argument("--masks", required=True, help="folder of *_masks.npz")
    p.add_argument("--images", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--seeds", default=None,
                   help="folder of *_polys.json from polygonize.py, used as the "
                        "seed polygons. STRONGLY RECOMMENDED: it preserves "
                        "partition() (disjoint instances) and polygonize.py's "
                        "quality filters. Without it, seeds are re-derived from "
                        "each raw mask and overlapping polygons are possible.")
    p.add_argument("--corner-thr", type=float, default=0.5)
    p.add_argument("--min-gap", type=int, default=2,
                   help="minimum index separation between kept corners")
    p.add_argument("--min-iou", type=float, default=0.80,
                   help="reject the refinement if the resulting polygon agrees "
                        "with its own mask less than this AND worse than the "
                        "seed did. The guard that keeps this stage monotonic.")
    p.add_argument("--min-area", type=int, default=200)
    p.set_defaults(func=cmd_apply)

    bn = sub.add_parser("bench", help="score corner accuracy vs GT vertices")
    bn.add_argument("--ckpt", required=True,
                    help="checkpoint file, or a run directory")
    bn.add_argument("--ckpt-tag", choices=["best", "last", "snap"], default="best",
                    help="which of the two rolling checkpoints to load when --ckpt is a RUN DIRECTORY: best (lowest val loss) or last (final epoch). Ignored when --ckpt names a file.")
    bn.add_argument("--data-root", required=True,
                    help="a SPLIT dir (…/val), containing images/ and "
                         "annotations.json")
    bn.add_argument("--masks", required=True, help="folder of *_masks.npz")
    bn.add_argument("--seeds", default=None,
                    help="folder of *_polys.json from polygonize.py; match "
                         "whatever you pass to `apply` or the benchmark does "
                         "not measure the pipeline you will run")
    bn.add_argument("--corner-thr", type=float, default=0.5)
    bn.add_argument("--min-gap", type=int, default=2)
    bn.add_argument("--min-iou", type=float, default=0.80)
    bn.add_argument("--min-area", type=int, default=200)
    bn.set_defaults(func=cmd_bench)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
