"""
Inference for the DINOv3 + Mask2Former building segmenter (v2).

v2 ranks and thresholds instances by the mask-IoU head (`--score-mode`), not
by `cls x mask_quality`. Measured on v1's 1834 val predictions: `cls x mq`
correlates r=0.477 with true IoU, and re-scoring with the true IoU raises AP
from 0.378 to 0.508. Every component is written to the .npz so eval.py can
compare rankings without re-running the model.

    python infer_dinov3_mask2former.py \
        --ckpt runs/dinov3_m2f/best.pth \
        --images /path/to/images \
        --out    /path/to/overlays

Handles images larger than the training tile size by sliding-window inference
with border-instance rejection and global de-duplication, so it works on both
512 crops and full scenes.

Optional --save-masks writes per-image .npz with instance masks + scores, which
is what MCR/PST consumes downstream.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

from transformers import Mask2FormerImageProcessor

from heads import predict_iou
from runlog import cli_flags, resolve_ckpt

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


# --------------------------------------------------------------------------
# instance container: store a cropped mask + bbox, not a full-scene array.
# On a large scene with thousands of buildings, full-size masks per instance
# will exhaust RAM very quickly.
# --------------------------------------------------------------------------
@dataclass
class Inst:
    x0: int
    y0: int
    mask: np.ndarray  # bool, shape (y1-y0, x1-x0)
    score: float      # what ranking and NMS actually use (see --score-mode)
    cls: float = -1.0    # classification confidence alone
    mq: float = -1.0     # mean probability inside the binarised mask
    iou: float = -1.0    # mask-IoU head's self-assessment, -1 if no head

    @property
    def x1(self):
        return self.x0 + self.mask.shape[1]

    @property
    def y1(self):
        return self.y0 + self.mask.shape[0]

    @property
    def area(self):
        return int(self.mask.sum())


def from_full(mask_full, score, offset=(0, 0), cls=-1.0, mq=-1.0, iou=-1.0):
    """Crop a full-tile boolean mask to its bbox and wrap as an Inst."""
    ys, xs = np.nonzero(mask_full)
    if len(ys) == 0:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return Inst(int(x0 + offset[0]), int(y0 + offset[1]),
                mask_full[y0:y1, x0:x1].copy(), float(score),
                float(cls), float(mq), float(iou))


def overlap_stats(a: Inst, b: Inst):
    """Returns (IoU, IoS). IoS = intersection / smaller area -- catches the
    containment case (a small mask swallowed by a large one) that IoU misses."""
    x0, y0 = max(a.x0, b.x0), max(a.y0, b.y0)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0
    sa = a.mask[y0 - a.y0:y1 - a.y0, x0 - a.x0:x1 - a.x0]
    sb = b.mask[y0 - b.y0:y1 - b.y0, x0 - b.x0:x1 - b.x0]
    inter = int(np.logical_and(sa, sb).sum())
    if inter == 0:
        return 0.0, 0.0
    aa, ab = a.area, b.area
    return inter / (aa + ab - inter), inter / max(min(aa, ab), 1)


def dedup(insts, iou_thr=0.5, ios_thr=0.8):
    """Greedy NMS over mask IoU and containment, highest score first."""
    keep = []
    for c in sorted(insts, key=lambda i: -i.score):
        ok = True
        for k in keep:
            # ONE call per pair. The previous form invoked overlap_stats twice
            # -- once for IoU, once for IoS -- recomputing the same mask
            # intersection on an already O(N^2) loop.
            iou, ios = overlap_stats(c, k)
            if iou >= iou_thr or ios >= ios_thr:
                ok = False
                break
        if ok:
            keep.append(c)
    return keep



# --------------------------------------------------------------------------
# Mask cleaning
#
# ORDER IS NOT ARBITRARY. Hole filling must precede de-duplication:
#   a nested instance sits in a HOLE of the outer mask
#     -> intersection(outer, inner) ~ 0  ->  IoS ~ 0
#     -> de-dup sees no containment and keeps both
# Measured: IoS 0.000 before filling, 1.000 after. Order is the fix, not the
# threshold.
# --------------------------------------------------------------------------
def fill_holes(mask, max_hole_frac=0.25):
    """
    Fill interior holes up to a fraction of the instance area.

    THE PAD IS LOAD-BEARING. from_full() crops tightly to the bounding box, so
    pixel (0, 0) is FOREGROUND for any shape whose corner reaches the bbox
    corner -- which is every axis-aligned building. Seeding floodFill there
    then fills nothing, every exterior background pixel inside the bbox is
    mistaken for a hole, and the mask inflates toward its bounding box.
    Measured on a concave test shape: 13000 -> 15000 px, i.e. 100% of the bbox.
    Padding by 1 guarantees the seed is background.

    Bounded rather than unconditional: factory blocks occasionally have real
    courtyards, and those should survive. Anything smaller is a segmentation
    dropout -- or a nested instance's footprint, which is the case that
    matters here.
    """
    m = np.ascontiguousarray(mask.astype(np.uint8))
    mp = np.pad(m, 1)                                  # <- guarantees (0,0) is background
    h, w = mp.shape
    flood = mp.copy()
    ff = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, ff, (0, 0), 1)                # background reachable from border
    holes = ((flood == 0) & (mp == 0)).astype(np.uint8)
    if holes.sum() == 0:
        return mask.astype(bool)

    n, lab, stats, _ = cv2.connectedComponentsWithStats(holes, 8)
    out = mp.copy()
    limit = max_hole_frac * max(int(m.sum()), 1)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] <= limit:
            out[lab == i] = 1
    return out[1:-1, 1:-1].astype(bool)


def split_components(inst, min_frac=0.15, min_area=100):
    """
    One instance mask -> one Inst per connected component.

    A query that fires on two disjoint blobs is a failure, but the two
    outcomes differ: comparable blobs are usually two real buildings merged
    into one query (split them), while a blob far smaller than the main one is
    almost always leakage (drop it).

    min_frac is that cutoff, measured against the largest component.
    """
    m = np.ascontiguousarray(inst.mask.astype(np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 2:                                   # background + one component
        return [inst]

    areas = stats[1:, cv2.CC_STAT_AREA]
    biggest = areas.max()
    out = []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < min_area or a < min_frac * biggest:
            continue
        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]
        cw = stats[i, cv2.CC_STAT_WIDTH]
        chh = stats[i, cv2.CC_STAT_HEIGHT]
        sub = (lab[y:y + chh, x:x + cw] == i)
        out.append(Inst(inst.x0 + int(x), inst.y0 + int(y), sub, inst.score,
                        inst.cls, inst.mq, inst.iou))
    return out or [inst]


def solidity(mask):
    """
    filled area / convex-hull area, over ALL components.

    An earlier version took only the largest external contour, which scored a
    two-blob mask at 1.000 -- it was measuring one blob and ignoring the other.
    Hulling every contour point together is what actually detects dispersion.

    USE WITH CARE. Korean factory blocks are frequently L- or U-shaped, and
    those legitimately score 0.6-0.75. This filter cannot distinguish a real
    L-shaped shed from a malformed mask, which is why min_solidity defaults to
    0.0 (off). Splitting and hole-filling already handle the artifacts it was
    meant to catch.
    """
    m = np.ascontiguousarray(mask.astype(np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return 0.0
    pts = np.vstack(cnts)
    ha = cv2.contourArea(cv2.convexHull(pts))
    return float(int(m.sum()) / ha) if ha > 0 else 0.0


def open_close(mask, open_k=3, close_k=5):
    """
    Opening and closing BY RECONSTRUCTION -- corner-preserving.

    Plain opening is the union of every k x k square that FITS inside the
    shape. At the corner of a ROTATED rectangle no axis-aligned square can
    reach the tip, so the tip is sliced off flat. Measured chamfer depth on a
    rotated shed: 1.0 px at k=3, 1.9 px at k=5, 2.9 px at k=7 and 45 deg.
    Axis-aligned buildings lose nothing, which is why the artefact only shows
    up on a rotated street grid.

    Reconstruction instead uses erosion only to DECIDE what survives, never to
    reshape it: a connected component is kept whole if it contains any eroded
    seed, and dropped entirely if it does not. Boundaries -- and therefore
    corners -- come through untouched (verified 1.0000x at 0/25/45 deg).

    Closing is the dual: a background component is filled if it contains no
    eroded background seed. The exterior always does, so the outer contour is
    never altered; only enclosed holes and sub-kernel gaps are filled.

    TRADE-OFF: reconstruction removes only ISOLATED thin objects. A thin spur
    attached to a real building shares its component and is therefore kept,
    where plain opening would have shaved it off (along with the corners).
    """
    m = np.ascontiguousarray(mask.astype(np.uint8))

    if open_k > 1:
        core = cv2.erode(m, np.ones((open_k, open_k), np.uint8))
        n, lab = cv2.connectedComponents(m, connectivity=8)
        if n > 1:
            seeded = np.unique(lab[core > 0])
            seeded = seeded[seeded != 0]
            m = np.isin(lab, seeded).astype(np.uint8) if seeded.size else m

    if close_k > 1:
        bg = (m == 0).astype(np.uint8)
        core = cv2.erode(bg, np.ones((close_k, close_k), np.uint8))
        n, lab = cv2.connectedComponents(bg, connectivity=8)
        if n > 1:
            seeded = np.unique(lab[core > 0])
            seeded = seeded[seeded != 0]
            m = (~np.isin(lab, seeded) if seeded.size
                 else np.ones_like(bg, bool)).astype(np.uint8)

    return m.astype(bool)


# --------------------------------------------------------------------------
def is_sliver(mask, min_side, max_aspect):
    """
    True for an instance too thin or too elongated to be a building.

    At 0.5 m/px a min side of 8 px is 4 m -- narrower than any real building
    footprint in this data, so these are always leakage: a strip along a
    neighbour's wall, or a fragment of a roof edge.

    Uses minAreaRect rather than the bbox, so a diagonal strip is measured
    across its true width instead of the width of the axis-aligned box that
    contains it.

    Measured on run1 (52 val tiles, 2134 predictions), min_side=8 /
    max_aspect=6 drops 191 instances of which only 4 were true positives:
        AP        0.3820 -> 0.3844
        AP <800px 0.1154 -> 0.1274      (slivers pollute the small bucket most)
        precision 0.5809 -> 0.6158
        F1        0.6488 -> 0.6689
    min_side=10 overshoots (AP 0.3804, recall 0.7215).
    """
    if min_side <= 0 and max_aspect <= 0:
        return False
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                             cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return True
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 20:
        return True
    (_, _), (w, h), _ = cv2.minAreaRect(c)
    lo, hi = min(w, h), max(w, h)
    if min_side > 0 and lo < min_side:
        return True
    return max_aspect > 0 and hi / max(lo, 1e-6) > max_aspect


def clean_instances(insts, fill=True, max_hole_frac=0.25,
                    morph=True, open_k=3, close_k=5,
                    split=True, min_frac=0.15,
                    min_area=100, min_solidity=0.0,
                    min_side=8.0, max_aspect=6.0,
                    iou_thr=0.5, ios_thr=0.6, verbose=True):
    """Full cleaning pass. Returns a new instance list."""
    n0 = len(insts)

    # 1. morphology -- before splitting, so hairline bridges are cut and the
    #    component labelling actually separates the blobs
    if morph:
        tmp = []
        for i in insts:
            m = open_close(i.mask, open_k, close_k)
            if m.sum() >= min_area:
                ni = from_full(m, i.score, offset=(i.x0, i.y0), cls=i.cls,
                               mq=i.mq, iou=i.iou)
                if ni is not None:
                    tmp.append(ni)
        insts = tmp

    # 2. fill holes -- BEFORE de-dup, so containment is visible to IoS
    if fill:
        insts = [Inst(i.x0, i.y0, fill_holes(i.mask, max_hole_frac), i.score,
                      i.cls, i.mq, i.iou) for i in insts]

    # 3. split multi-blob instances
    if split:
        insts = [s for i in insts
                 for s in split_components(i, min_frac, min_area)]
    n_split = len(insts)

    # 3b. drop slivers -- AFTER splitting, so a strip that split off a real
    #     body is caught too, and BEFORE de-dup, so a sliver can never suppress
    #     the instance it overlaps.
    n_pre_sliver = len(insts)
    insts = [i for i in insts if not is_sliver(i.mask, min_side, max_aspect)]
    n_sliver = n_pre_sliver - len(insts)

    # 4. shape sanity
    insts = [i for i in insts
             if i.area >= min_area and solidity(i.mask) >= min_solidity]
    n_shape = len(insts)

    # 5. de-dup last, now that masks are solid and holes are gone
    insts = dedup(insts, iou_thr, ios_thr)

    if verbose:
        print(f"[clean] {n0} -> morph/fill/split {n_split} -> "
              f"sliver -{n_sliver} -> shape filter {n_shape} -> "
              f"de-dup {len(insts)}")
    return insts

# --------------------------------------------------------------------------
def post_process(out, size, score_thr=0.5, mask_thr=0.5, min_area=100,
                 model=None, score_mode="cls_mq"):
    """
    Custom post-processing with a TUNABLE mask-binarization threshold.

    `Mask2FormerImageProcessor.post_process_instance_segmentation(threshold=)`
    is the CLASS-score threshold; mask binarization is hard-coded at sigmoid
    0.5 inside the processor. If masks come out systematically inset -- which
    is what a smooth, under-confident probability field looks like -- 0.5 is
    the wrong cut and there is no way to change it through that API.

    SCORE = cls * mask_quality, matching what the HF processor computes
    internally (verified: cls 0.525 x mq 0.506 = 0.266, identical to the
    built-in). Classification confidence alone rates a query that is certain
    it sees a building but draws a poor mask exactly as highly as one that
    draws a good mask, which is the wrong thing to sort and threshold on.

    mask_quality is the mean predicted probability inside the binarised
    region: a crisp mask averages near 1.0, a smeared one near mask_thr. On the
    v1 model it had std 0.020 across 1834 predictions -- very nearly a
    constant, which is why v2 defaults to the IoU head instead.

    Pass `model` to score with the v2 mask-IoU head. WITHOUT it the only
    available modes are the v1 ones, and a v2 checkpoint would be scored as
    though it had no head -- silently, since the masks are identical and only
    the ranking changes. run_tile()/_forward_probs() is the path inference
    actually uses; this helper exists for one-off calls on an `out` you already
    have.

    Returns (mask, score, cls, mask_quality, pred_iou) per instance.
    """
    cls = out.class_queries_logits[0].float().softmax(-1)  # (Q, num_labels + 1)
    cls_score = cls[:, :-1].max(-1).values                # drop no-object slot

    pi = predict_iou(model, out) if model is not None else None
    pred_iou = pi[0].float() if pi is not None else None
    logits = torch.nn.functional.interpolate(
        out.masks_queries_logits[0][None].float(), size=size,
        mode="bilinear", align_corners=False)[0]
    return _post_from_prob(logits.sigmoid(), cls_score, score_thr=score_thr,
                           mask_thr=mask_thr, min_area=min_area,
                           pred_iou=pred_iou, score_mode=score_mode)


SCORE_MODES = ("cls_iou", "iou", "cls_mq", "cls")


def combine_score(cls_score, mq, pred_iou, mode="cls_iou"):
    """
    The ranking signal. Measured AP on the v1 model, re-scoring its own
    predictions (52 val tiles, COCOeval segm):

        random                    0.285
        cls                       0.364
        cls_mq   (v1 default)     0.378
        oracle true IoU           0.508

    so `cls_iou` / `iou` are the modes that can actually reach the ceiling --
    but only as well as the head is trained. `cls_mq` reproduces v1 exactly and
    is the honest fallback for a checkpoint with no head.

    `cls_iou` rather than plain `iou` by default: cls still carries a little
    independent signal (r=0.424 against true IoU on its own) and multiplying
    keeps a query that is unsure it saw anything from being promoted by a
    confident-looking mask.
    """
    if pred_iou is None and mode in ("cls_iou", "iou"):
        raise SystemExit(
            f"--score-mode {mode} needs a mask-IoU head, and this checkpoint "
            f"has none. Use --score-mode cls_mq (v1 behaviour).")
    if mode == "cls_iou":
        return cls_score * pred_iou
    if mode == "iou":
        return pred_iou
    if mode == "cls_mq":
        return cls_score * mq
    if mode == "cls":
        return cls_score
    raise SystemExit(f"unknown --score-mode {mode}")


def _post_from_prob(prob, cls_score, score_thr=0.5, mask_thr=0.5, min_area=100,
                    pred_iou=None, score_mode="cls_mq"):
    """
    Scoring and thresholding, given a probability field and class scores.

    Split out of post_process so the TTA path can average probabilities across
    orientations and then score once, rather than scoring each orientation and
    trying to reconcile the results afterwards.
    """
    binm = prob > mask_thr

    area = binm.flatten(1).sum(1)
    mq = torch.where(
        area > 0,
        (prob * binm).flatten(1).sum(1) / area.clamp_min(1),
        torch.zeros_like(cls_score))

    score = combine_score(cls_score, mq, pred_iou, score_mode)
    keep = score > score_thr
    if not keep.any():
        return []

    # .detach() at the numpy boundary. This function is a pure tensor -> numpy
    # conversion, so detaching here is correct rather than papering over
    # something: any caller that forgets to wrap the model in no_grad would
    # otherwise hit "Can't call numpy() on Tensor that requires grad" -- which
    # is exactly what happened once the IoU head joined the score, because the
    # head's own parameters require grad even when its inputs are detached.
    def to_np(t):
        return t.detach().float().cpu().numpy()

    masks = binm[keep].detach().cpu().numpy()
    sc = to_np(score[keep])
    cs = to_np(cls_score[keep])
    mqs = to_np(mq[keep])
    ious = (to_np(pred_iou[keep]) if pred_iou is not None
            else np.full(len(sc), -1.0, np.float32))

    order = np.argsort(-sc)
    return [(masks[i], float(sc[i]), float(cs[i]), float(mqs[i]), float(ious[i]))
            for i in order if masks[i].sum() >= min_area]


def _d4(img, k, flip):
    """One of the 8 square symmetries. Flip first, then rotate."""
    if flip:
        img = img[:, ::-1]
    return np.ascontiguousarray(np.rot90(img, k, (0, 1)))


def _d4_inv_maps(x, k, flip):
    """Undo _d4 on a (Q, H, W) tensor of maps: unrotate, then unflip."""
    x = torch.rot90(x, -k, dims=(-2, -1))
    if flip:
        x = torch.flip(x, dims=(-1,))
    return x


def _forward_probs(model, processor, tile, device, size):
    """
    (prob (Q,H,W), cls_score (Q,), pred_iou (Q,) or None) at `size`, for one
    orientation.

    The IoU head is evaluated on the model's NATIVE mask logits, before the
    interpolation to `size`: it was trained against targets computed at that
    resolution, and it reads the stride-4 mask features, which only exist there.

    EVERYTHING that touches the model stays inside the no_grad block --
    including the IoU head. `MaskIoUHead(detach=True)` detaches its INPUTS, but
    its own parameters still require grad, so calling it outside no_grad returns
    a tensor that requires grad, `score = cls x pred_iou` inherits that, and the
    .numpy() in _post_from_prob raises "Can't call numpy() on Tensor that
    requires grad". Training needs those gradients, so predict_iou cannot simply
    be marked no_grad itself -- the scope has to be right here.
    """
    enc = processor(images=tile, return_tensors="pt")
    with torch.no_grad(), torch.amp.autocast(
            device, dtype=torch.bfloat16, enabled=(device == "cuda")):
        out = model(pixel_values=enc["pixel_values"].to(device))
        cls = out.class_queries_logits[0].float().softmax(-1)
        cls_score = cls[:, :-1].max(-1).values
        pi = predict_iou(model, out)
        pred_iou = pi[0].float() if pi is not None else None
        logits = torch.nn.functional.interpolate(
            out.masks_queries_logits[0][None].float(), size=size,
            mode="bilinear", align_corners=False)[0]
        return logits.sigmoid(), cls_score, pred_iou


def run_tile(model, processor, tile, device, threshold, min_area, mask_thr=0.5,
             tta=False, tta_min_iou=0.5, score_mode="cls_mq"):
    """
    One forward pass -- or 8, averaged, with tta=True.

    Returns list of (bool mask, score, cls, mask_quality) at tile resolution.

    Averaging Mask2Former outputs is not as simple as averaging probability
    maps: query i under one orientation is not query i under another, so a
    naive mean smears unrelated instances together. Instead the canonical pass
    defines the instance set, and each rotated pass contributes only through
    the query that best matches an existing one. Queries that match nothing
    are ignored rather than added -- a detection that appears in exactly one
    of 8 orientations is noise, and this is a mask-refinement pass, not a
    recall-recovery one.

    Training uses exact D4 plus arbitrary rotations, so the model is close to
    equivariant here and the disagreement between orientations is mostly
    boundary noise -- which is what averaging cancels.
    """
    size = tile.shape[:2]
    prob, cls_score, pred_iou = _forward_probs(model, processor, tile, device, size)

    if tta:
        h, w = size
        # rot90 on a non-square tile changes its shape, so scene-edge crops
        # get the flips only rather than being silently skipped
        views = ([(k, f) for k in range(4) for f in (False, True)] if h == w
                 else [(0, False), (0, True)])
        acc, n = prob.clone(), torch.ones_like(cls_score)
        iou_acc = pred_iou.clone() if pred_iou is not None else None
        ref = prob > mask_thr
        ref_f = ref.flatten(1).float()                     # (Q, N), reused
        ref_area = ref_f.sum(1)
        for k, f in views[1:]:
            p_t, c_t, i_t = _forward_probs(model, processor, _d4(tile, k, f),
                                           device, size)
            p_t = _d4_inv_maps(p_t, k, f)
            cand = p_t > mask_thr
            # Pairwise IoU by matmul, NOT by broadcasting to (Q, Q, H, W).
            # The broadcast form allocates Q*Q*H*W and .sum() upcasts it to
            # int64: 78 GiB at Q=200 on a 512 tile. This costs Q*H*W instead.
            c = cand.flatten(1).float()                    # (Q, N)
            inter = ref_f @ c.t()                          # (Q, Q)
            union = (ref_area[:, None] + c.sum(1)[None] - inter).clamp_min(1)
            best, idx = (inter / union).max(dim=1)
            hit = best >= tta_min_iou
            if hit.any():
                acc[hit] += p_t[idx[hit]]
                cls_score[hit] = cls_score[hit] + c_t[idx[hit]]
                if iou_acc is not None and i_t is not None:
                    iou_acc[hit] = iou_acc[hit] + i_t[idx[hit]]
                n[hit] += 1
        prob = acc / n[:, None, None]
        cls_score = cls_score / n
        if iou_acc is not None:
            # Averaged over the SAME orientations and the same matched queries
            # as the mask and the class score. Averaging over a different set
            # would rank instances by how many views happened to agree, which
            # is a different quantity than mask quality.
            pred_iou = iou_acc / n

    return _post_from_prob(prob, cls_score, score_thr=threshold,
                           mask_thr=mask_thr, min_area=min_area,
                           pred_iou=pred_iou, score_mode=score_mode)


def predict_image(model, processor, img, device, tile_size=512, overlap=128,
                  tta=False,
                  threshold=0.5, min_area=100, iou_thr=0.5, ios_thr=0.8,
                  mask_thr=0.5, return_stages=False, score_mode="cls_mq"):
    """
    Returns the final instance list, or -- with return_stages=True -- a dict
    {"raw": ..., "dedup": ...} so intermediate results can be visualized.
    "raw" is everything the model emitted after border rejection but before
    any duplicate removal.
    """
    H, W = img.shape[:2]

    if H <= tile_size and W <= tile_size:
        raw = run_tile(model, processor, img, device, threshold, min_area,
                       mask_thr, tta=tta, score_mode=score_mode)
        pool = [i for i in (from_full(m, s, cls=c, mq=q, iou=v)
                            for m, s, c, q, v in raw) if i]
        kept = dedup(pool, iou_thr, ios_thr)
        return {"raw": pool, "dedup": kept} if return_stages else kept

    step = tile_size - overlap
    xs = list(range(0, max(W - tile_size, 0) + 1, step))
    ys = list(range(0, max(H - tile_size, 0) + 1, step))
    if xs[-1] + tile_size < W:
        xs.append(W - tile_size)
    if ys[-1] + tile_size < H:
        ys.append(H - tile_size)

    pool = []
    for oy in ys:
        for ox in xs:
            tile = img[oy:oy + tile_size, ox:ox + tile_size]
            for m, s, c, q, v in run_tile(model, processor, tile, device,
                                          threshold, min_area, mask_thr,
                                          tta=tta, score_mode=score_mode):
                # Border rejection: any building smaller than the overlap is
                # fully contained in some tile, so a mask touching an interior
                # tile edge is a truncated duplicate. Drop it. This removes the
                # fragments that produce broken polygons, and most duplicates
                # for free -- before de-dup even runs.
                touches = (
                    (m[0].any() and oy > 0) or (m[-1].any() and oy + tile_size < H) or
                    (m[:, 0].any() and ox > 0) or (m[:, -1].any() and ox + tile_size < W)
                )
                if touches:
                    continue
                inst = from_full(m, s, offset=(ox, oy), cls=c, mq=q, iou=v)
                if inst is not None:
                    pool.append(inst)

    kept = dedup(pool, iou_thr, ios_thr)
    return {"raw": pool, "dedup": kept} if return_stages else kept


# --------------------------------------------------------------------------
def draw(img, insts, alpha=0.45, seed=0, detail=False):
    """Alpha-blend a distinct color per instance + contour + score."""
    rng = np.random.default_rng(seed)
    vis = img.copy()
    layer = img.copy()

    for k, ins in enumerate(insts):
        color = rng.integers(60, 255, 3).tolist()
        full = np.zeros(img.shape[:2], np.uint8)
        full[ins.y0:ins.y1, ins.x0:ins.x1] = ins.mask
        layer[full.astype(bool)] = color
        cnts, _ = cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, cnts, -1, color, 2)

    vis = cv2.addWeighted(layer, alpha, vis, 1 - alpha, 0)

    for ins in insts:
        # A bare confidence hides WHY a prediction is bad. Showing cls and mask
        # quality separately says immediately whether the model misclassified
        # or just drew the boundary badly.
        cv2.putText(vis, f"{ins.score:.2f}", (ins.x0 + 2, max(ins.y0 + 12, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1, cv2.LINE_AA)
        if detail and ins.cls >= 0:
            extra = f" i{ins.iou:.2f}" if ins.iou >= 0 else ""
            cv2.putText(vis, f"c{ins.cls:.2f} m{ins.mq:.2f}{extra}",
                        (ins.x0 + 2, max(ins.y0 + 24, 24)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.30, (0, 255, 255), 1, cv2.LINE_AA)
    return vis


def panel(img, insts, title, alpha=0.45, detail=False):
    """Overlay + a caption bar, so stacked stages stay identifiable."""
    vis = draw(img, insts, alpha=alpha, detail=detail)
    bar = np.zeros((26, vis.shape[1], 3), np.uint8)
    cv2.putText(bar, f"{title}  (n={len(insts)})", (6, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return np.concatenate([bar, vis], axis=0)


def save_masks_npz(path, insts, shape, score_mode, survived=None):
    """
    Write instances as an npz. One writer for both the final and the raw pool,
    so the two files always carry the same schema -- a raw dump missing
    `pred_iou` would silently fall back to `scores` in eval.py.

    `survived` is an optional bool per instance recording whether it survived
    de-duplication. Only meaningful for the raw pool, where it is the whole
    point: it identifies exactly which instances dedup discarded, which is the
    set you need to test merging instead of dropping.
    """
    out = dict(
        boxes=np.array([[i.x0, i.y0, i.x1, i.y1] for i in insts], np.int32
                       ).reshape(-1, 4),
        scores=np.array([i.score for i in insts], np.float32),
        cls_scores=np.array([i.cls for i in insts], np.float32),
        mask_quality=np.array([i.mq for i in insts], np.float32),
        # every component, not just the combined score, so eval.py can score
        # alternative rankings with --score-key and no re-run
        pred_iou=np.array([i.iou for i in insts], np.float32),
        score_mode=np.array(score_mode),
        shape=np.array(shape, np.int32),
    )
    if survived is not None:
        out["survived_dedup"] = np.asarray(survived, bool)
    for k, i in enumerate(insts):
        out[f"m{k}"] = i.mask
    np.savez_compressed(path, **out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True,
                    help="checkpoint file, OR a run directory -- then the "
                         "newest checkpoint with the --ckpt-tag tag is used")
    ap.add_argument("--ckpt-tag", choices=["best", "last", "snap"], default="best",
                    help="which of the two rolling checkpoints to load when --ckpt is a RUN DIRECTORY: best (lowest val loss) or last (final epoch). Ignored when --ckpt names a file.")
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dinov3", default="facebook/dinov3-vitl16-pretrain-lvd1689m")
    ap.add_argument("--m2f", default="facebook/mask2former-swin-base-coco-instance")
    ap.add_argument("--tile-size", type=int, default=512)
    ap.add_argument("--overlap", type=int, default=128)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--tta", action="store_true",
                    help="average masks over the 8 square symmetries. Refines "
                         "boundaries; costs 8x inference and does not recover "
                         "missed buildings.")
    ap.add_argument("--min-area", type=int, default=100)
    ap.add_argument("--iou-thr", type=float, default=0.5)
    ap.add_argument("--ios-thr", type=float, default=0.8)
    ap.add_argument("--score-mode", choices=list(SCORE_MODES),
                    default="cls_iou",
                    help="ranking / thresholding signal. cls_iou (default) and "
                         "iou use the v2 mask-IoU head; cls_mq is v1 behaviour "
                         "and the only option for a v1 checkpoint.")
    ap.add_argument("--mask-threshold", type=float, default=0.5,
                    help="sigmoid cut for mask binarization. Lower (~0.35) if "
                         "masks look inset relative to the roof.")
    ap.add_argument("--alpha", type=float, default=0.45)
    ap.add_argument("--show-scores", action="store_true",
                    help="also print cls and mask-quality under each score, so "
                         "a bad prediction can be attributed to classification "
                         "or to mask quality")
    ap.add_argument("--side-by-side", action="store_true")
    ap.add_argument("--no-clean", action="store_true",
                    help="skip the cleaning stage (morphology, hole fill, "
                         "component split, re-dedup)")
    ap.add_argument("--min-side", type=float, default=8.0,
                    help="drop instances whose minAreaRect short side is below "
                         "this many px. At 0.5 m/px, 8 px = 4 m -- narrower "
                         "than any real footprint here, so these are leakage. "
                         "Measured on run1: 8/6 drops 191 of 2134 instances, "
                         "only 4 of them true positives; AP 0.3820 -> 0.3844, "
                         "AP<800px 0.1154 -> 0.1274, F1 0.6488 -> 0.6689. "
                         "10 overshoots. 0 disables.")
    ap.add_argument("--max-aspect", type=float, default=6.0,
                    help="drop instances whose minAreaRect long/short ratio "
                         "exceeds this. 0 disables.")
    ap.add_argument("--min-frac", type=float, default=0.15,
                    help="clean: drop blobs below this fraction of the largest")
    ap.add_argument("--max-hole-frac", type=float, default=0.25)
    ap.add_argument("--open-k", type=int, default=3)
    ap.add_argument("--close-k", type=int, default=5)
    ap.add_argument("--clean-ios-thr", type=float, default=0.6,
                    help="containment threshold for the SECOND de-dup, the one "
                         "inside clean_instances. Deliberately STRICTER than "
                         "--ios-thr: hole filling and component splitting run "
                         "first, so containment that was invisible before is "
                         "visible here. NOTE it therefore overrides a relaxed "
                         "--ios-thr -- `--ios-thr 1.1` alone gave +7 instances "
                         "instead of +277 until this was also raised. infer.py "
                         "warns when the two disagree in that direction.")
    ap.add_argument("--viz-stages", action="store_true",
                    help="write a stacked raw / dedup / clean comparison")
    ap.add_argument("--save-masks", action="store_true",
                    help="also write .npz with instance masks + scores (for MCR/PST)")
    ap.add_argument("--save-raw-masks", action="store_true",
                    help="also write <stem>_raw_masks.npz: the instance pool "
                         "BEFORE de-duplication and cleaning, plus a "
                         "`survived_dedup` bool per instance. This is what you "
                         "need to test alternatives to dropping overlaps "
                         "(merging them, for instance) -- the final npz has "
                         "already discarded the losing masks. Expect roughly "
                         "2-4x more instances and a correspondingly larger "
                         "file; on full scenes that adds up.")
    args = ap.parse_args()

    from train_dinov3_mask2former import build_model

    device = "cuda" if torch.cuda.is_available() else "cpu"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --ckpt takes a run DIRECTORY or a file. Training writes best_ep<N>.pth,
    # whose name changes as the best moves, so hardcoding a filename in a
    # pipeline script goes stale after the next run.
    args.ckpt = resolve_ckpt(args.ckpt, prefer=args.ckpt_tag)
    ck = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    cfg = ck.get("cfg", {})
    if cfg:
        # Rebuild exactly what was trained. Explicit CLI flags still win.
        given = set(a.split("=")[0] for a in __import__("sys").argv if a.startswith("--"))
        if "--dinov3" not in given:
            args.dinov3 = cfg.get("dinov3", args.dinov3)
        if "--m2f" not in given:
            args.m2f = cfg.get("m2f", args.m2f)
        if "--tile-size" not in given:
            args.tile_size = cfg.get("image_size", args.tile_size)
        print(f"[load] checkpoint cfg: {cfg}")
    else:
        print("[warn] checkpoint has no 'cfg' (trained before this was added). "
              "Verify --dinov3 / --tile-size match training yourself.")

    # v2 additions come from cfg, never from a default: rebuilding with
    # taps="auto" against a checkpoint trained with taps="off" gives four
    # tap_norms with no saved weights, and the strict check below is what turns
    # that into an error instead of silent garbage.
    has_head = cfg.get("maskiou", False)
    model = build_model(args.dinov3, args.m2f, num_labels=1,
                        image_size=args.tile_size,
                        backbone=cfg.get("backbone", "auto"),
                        use_stem=cfg.get("use_stem", True),
                        num_queries=cfg.get("num_queries"),
                        taps=cfg.get("taps", "off"),
                        maskiou=has_head,
                        maskiou_hidden=cfg.get("maskiou_hidden", 256))
    if not has_head and args.score_mode in ("cls_iou", "iou"):
        print(f"[warn] checkpoint has no mask-IoU head; "
              f"--score-mode {args.score_mode} -> cls_mq")
        args.score_mode = "cls_mq"
    print(f"[run] score-mode: {args.score_mode}")

    # TWO de-dup passes use a containment threshold: predict_image's
    # (--ios-thr) and clean_instances' (--clean-ios-thr). The second is
    # stricter by default, so relaxing only the first is silently undone --
    # measured on run3: --ios-thr 1.1 alone gave +7 instances, both gave +277.
    # only when --ios-thr was EXPLICITLY relaxed: the stock 0.8 vs 0.6 pairing
    # is intentional and must not warn on every run
    _given = cli_flags()
    if ("--ios-thr" in _given and "--clean-ios-thr" not in _given
            and args.clean_ios_thr < args.ios_thr):
        print(f"[warn] --ios-thr {args.ios_thr} is looser than --clean-ios-thr "
              f"{args.clean_ios_thr}, so the cleaning pass will re-drop what "
              f"the first pass kept. Pass --clean-ios-thr {args.ios_thr} too "
              f"if you meant to relax containment everywhere.")

    # THE SCORE SCALE CHANGED, AND --threshold DID NOT.
    #
    # v1's cls x mask_quality sat at ~0.96 x 0.97 = 0.93, so the default
    # --threshold 0.5 discarded nothing (measured: thresholds 0.5 to 0.8 moved
    # TP/FP/FN by exactly zero). v2's cls x pred_iou is a predicted IoU, which
    # for a GOOD detection is ~0.8 and for a mediocre one is ~0.4 -- so 0.5 now
    # silently deletes most of the detections, and the run looks far worse than
    # v1 for a purely mechanical reason. Threshold low and let AP integrate.
    if args.score_mode in ("cls_iou", "iou") and args.threshold > 0.3:
        print(f"[warn] --threshold {args.threshold} is high for --score-mode "
              f"{args.score_mode}: that score is a predicted IoU, not a "
              f"saturated confidence. Use --threshold 0.05 and let eval.py "
              f"sweep, or you will drop most true positives.")
    missing, unexpected = model.load_state_dict(ck.get("model", ck), strict=False)
    print(f"[load] epoch={ck.get('epoch', '?')} val={ck.get('val', '?')} "
          f"missing={len(missing)} unexpected={len(unexpected)}")
    # Any missing/unexpected key in the trained parts means the architecture
    # does not match the checkpoint. strict=False will NOT raise -- it just
    # leaves those weights randomly initialized. Fail loudly instead.
    bad = [k for k in list(missing) + list(unexpected)
           if not k.startswith("model.pixel_level_module.encoder.vit.")
           and not k.startswith("model.pixel_level_module.encoder.net.")]
    if bad:
        raise SystemExit(
            f"[fatal] {len(bad)} weights do not match the checkpoint, e.g. {bad[:4]}\n"
            f"        The architecture differs from training. Check --dinov3, "
            f"--backbone, --tile-size.")
    model.to(device).eval()

    processor = Mask2FormerImageProcessor(
        do_resize=True,
        size={"height": args.tile_size, "width": args.tile_size},
        do_normalize=True,
        image_mean=[0.485, 0.456, 0.406],
        image_std=[0.229, 0.224, 0.225],
        do_reduce_labels=False,
        ignore_index=255,
    )

    # A FILE or a directory. Single-scene inference is a normal case --
    # predict_image tiles a whole scene internally -- and iterdir() alone
    # answered it with NotADirectoryError, which names the wrong problem.
    src = Path(args.images)
    if src.is_file():
        if src.suffix.lower() not in IMG_EXT:
            raise SystemExit(
                f"[fatal] --images {src} is not a recognised image "
                f"({', '.join(sorted(IMG_EXT))})")
        files = [src]
    elif src.is_dir():
        files = sorted(p for p in src.iterdir()
                       if p.suffix.lower() in IMG_EXT)
    else:
        raise SystemExit(f"[fatal] --images {src} does not exist")
    if not files:
        raise SystemExit(f"no images found in {args.images}")
    print(f"[run] {len(files)} images -> {out_dir}")

    for n, p in enumerate(files, 1):
        img = np.array(Image.open(p).convert("RGB"))
        stages = predict_image(
            model, processor, img, device,
            tile_size=args.tile_size, overlap=args.overlap,
            threshold=args.threshold, min_area=args.min_area,
            iou_thr=args.iou_thr, ios_thr=args.ios_thr, tta=args.tta,
            mask_thr=args.mask_threshold, return_stages=True,
            score_mode=args.score_mode)

        if not args.no_clean:
            stages["clean"] = clean_instances(
                stages["dedup"], max_hole_frac=args.max_hole_frac,
                open_k=args.open_k, close_k=args.close_k,
                min_frac=args.min_frac, min_area=args.min_area,
                min_side=args.min_side, max_aspect=args.max_aspect,

                iou_thr=args.iou_thr, ios_thr=args.clean_ios_thr,
                verbose=False)

        insts = stages.get("clean", stages["dedup"])

        if args.viz_stages:
            names = [k for k in ("raw", "dedup", "clean") if k in stages]
            vis = np.concatenate(
                [panel(img, stages[k], k, args.alpha, args.show_scores)
                 for k in names], axis=1)
        else:
            vis = draw(img, insts, alpha=args.alpha, detail=args.show_scores)
            if args.side_by_side:
                vis = np.concatenate([img, vis], axis=1)
        cv2.imwrite(str(out_dir / f"{p.stem}_overlay.png"),
                    cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))

        if args.save_masks:
            save_masks_npz(out_dir / f"{p.stem}_masks.npz", insts,
                           img.shape[:2], args.score_mode)

        if args.save_raw_masks:
            # Identity, not equality: dedup() returns the SAME Inst objects it
            # kept, so `id` tells us exactly which of the raw pool survived.
            # clean_instances() rebuilds objects, so raw->dedup is the only
            # boundary that can be tracked this way -- which is the one that
            # matters, since dedup is what DROPS instances.
            kept = {id(i) for i in stages["dedup"]}
            survived = [id(i) in kept for i in stages["raw"]]
            save_masks_npz(out_dir / f"{p.stem}_raw_masks.npz", stages["raw"],
                           img.shape[:2], args.score_mode, survived=survived)

        counts = "  ".join(f"{k}={len(v)}" for k, v in stages.items())
        print(f"  [{n}/{len(files)}] {p.name}: {counts}")

    print("[done]")


if __name__ == "__main__":
    main()