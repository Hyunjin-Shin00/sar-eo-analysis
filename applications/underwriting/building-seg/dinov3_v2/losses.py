"""
Auxiliary losses for the building segmenter.

All three are DELIBERATELY MATCHING-FREE. They score the model's raw query
outputs against the GT instance set without ever consulting the Hungarian
assignment, so they cannot break when the `transformers` loss internals move
between versions -- and they cannot fight the main loss for control of the
assignment.

Measured motivation (v1 model, 52 val tiles, see README):
  * boundary_loss    predictions sit 2.78 px off the true edge on average and
                     are 3.5x less rectilinear than GT (3.89 deg vs 1.12 deg
                     mean angular deviation).
  * collision_loss   176 of 387 missed buildings (45%) were NOT missed -- they
                     were absorbed into a neighbour's instance. 70 predictions
                     swallow >=2 GT buildings outright.
  * the crowd weight 2.95% of train pixels are `iscrowd` (clipped-at-tile-edge
                     buildings). They must not be scored as background.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
def semantic_prob(outputs):
    """
    Per-pixel "is this a building" probability, in [0, 1].

    max over queries of class x mask, NOT sum: bounded in [0, 1] however many
    queries fire on a pixel. Returns (B, h, w) at MASK-LOGIT resolution
    (input / 4), float32 -- the elementwise log/clamp arithmetic downstream is
    not autocast-safe in bf16.
    """
    # .float() BEFORE the arithmetic, not after: under autocast these arrive
    # as bf16, and a probability near 0.02 has about two mantissa bits there.
    ml = outputs.masks_queries_logits.float()            # (B, Q, h, w)
    cls = outputs.class_queries_logits.float().softmax(-1)[..., :-1].max(-1).values
    return (cls[:, :, None, None] * ml.sigmoid()).amax(dim=1)


def _resize_to(x, h, w, mode="nearest"):
    """(N, H, W) -> (N, h, w). Handles the N == 0 case, which interpolate does not."""
    if x.shape[0] == 0:
        return x.new_zeros((0, h, w))
    if x.shape[-2:] == (h, w):
        return x.float()
    kw = {} if mode == "nearest" else {"align_corners": False}
    return F.interpolate(x.float()[:, None], size=(h, w), mode=mode, **kw)[:, 0]


def instances_at(mask_labels, h, w):
    """
    Per-sample GT instance stacks resampled to the mask-logit grid.

    Nearest-neighbour, not area: these are used to build edge bands and
    coverage ratios, and a soft target would blur exactly the 1-3 px alley
    between two buildings that we are trying to teach.
    """
    return [_resize_to(m, h, w) for m in mask_labels]


def _dilate(x, k):
    """Binary dilation by a (2k+1) square. x: (N, h, w) -> (N, h, w)."""
    if k <= 0 or x.shape[0] == 0:
        return x
    return F.max_pool2d(x[:, None], 2 * k + 1, 1, k)[:, 0]


def _erode(x, k):
    if k <= 0 or x.shape[0] == 0:
        return x
    return -F.max_pool2d(-x[:, None], 2 * k + 1, 1, k)[:, 0]


def crowd_zone(inst, gap):
    """
    (h, w) float mask, 1 where >=2 DISTINCT instances lie within `gap` px.

    This is the narrow-alley detector. Dilating every instance by `gap` and
    counting overlaps is O(N) through the batch dimension of max_pool2d -- the
    pairwise formulation would be O(N^2) and N reaches 95 on a mosaic sample.

    Note it is >= 2 on the *count*, so a lone building's own dilation ring
    never triggers.
    """
    if inst.shape[0] < 2:
        return inst.new_zeros(inst.shape[-2:])
    return (_dilate(inst, gap).sum(0) >= 2).float()


# --------------------------------------------------------------------------
# 1. boundary loss  (v1, plus crowd-aware weighting)
# --------------------------------------------------------------------------
def boundary_loss(outputs, mask_labels, width=3, eps=1e-6,
                  crowd_weight=0.0, crowd_gap=3, ignore=None):
    """
    BCE charged only on a band around the true building edge.

    Mask2Former's dice + point-sampled BCE weight every pixel equally, so a
    2 px error on the boundary of a 3000 px building is nearly free to the
    objective -- and the boundary is exactly what is wrong. Measured on val:
    masks are the RIGHT SIZE (median predicted/GT area 1.017) but sit 2.78 px
    off. Nothing in the base loss rewards fixing that, and no post-processing
    can: thresholding, 8-way TTA and image-gradient snapping were each measured
    and each failed, because the error is systematic rather than noisy.

    `crowd_weight` > 0 additionally upweights the band where two buildings are
    within `crowd_gap` px of each other. Those pixels -- the 1-3 px alley
    between adjacent workshops -- are a tiny fraction of the total band, so at
    uniform weight they contribute almost nothing, yet they are where the
    merge failures happen. This is the CHEAP half of the merge fix; the
    zero-gap party-wall case is interior to the union and needs
    `collision_loss` instead.

    `ignore` (B, h, w) suppresses the band entirely -- used for `iscrowd`
    regions, which are buildings clipped by the tile edge and whose true
    outline is not knowable from this tile.

    Returns a scalar in BCE units, so a weight around 1-5 puts it on a
    comparable footing with the existing mask terms.
    """
    sem = semantic_prob(outputs)                         # (B, h, w) fp32
    b, h, w = sem.shape
    inst = instances_at(mask_labels, h, w)

    tgt, weight = [], []
    for i, m in enumerate(inst):
        u = m.amax(0) if m.shape[0] else m.new_zeros((h, w))
        band = _dilate(u[None], width)[0] - _erode(u[None], width)[0]
        if crowd_weight > 0:
            band = band * (1.0 + crowd_weight * crowd_zone(m, crowd_gap))
        tgt.append(u)
        weight.append(band)

    tgt = torch.stack(tgt)
    weight = torch.stack(weight)
    if ignore is not None:
        weight = weight * (1.0 - _resize_to(ignore.float(), h, w))

    denom = weight.sum()
    if float(denom) < 1.0:                               # tile with no edges
        return sem.sum() * 0.0

    # BCE written out rather than F.binary_cross_entropy, which raises under
    # autocast ("unsafe to autocast") -- and the with_logits form is not
    # available: `sem` is a probability built from max over queries of
    # class x sigmoid(mask), so there is no single logit behind it. sem is
    # already fp32 and these ops stay fp32, so the clamp is what keeps the
    # logs finite.
    p = sem.clamp(eps, 1.0 - eps)
    bce = -(tgt * p.log() + (1.0 - tgt) * (1.0 - p).log())
    return (bce * weight).sum() / denom


# --------------------------------------------------------------------------
# 2. collision loss  (Tier 2 -- the merge fix)
# --------------------------------------------------------------------------
def collision_loss(outputs, mask_labels, active_thr=0.2, ignore=None, pool=2):
    """
    Penalise a SINGLE query for covering TWO GT buildings.

    This is the loss the union-based boundary term structurally cannot be:
    where two buildings share a wall with no gap, the union of the GT masks is
    solid, the union's edge band does not pass through the wall, and every
    union-based objective is satisfied by one blob spanning both. Measured
    consequence on v1: 45% of "missed" buildings were absorbed into a
    neighbour, and 70 predictions swallow >=2 GT buildings.

    Construction. For query q and GT instance i let

        cov[q, i] = sum_pixels( sem_q * m_i ) / sum_pixels( m_i )

    the fraction of building i claimed by query q, where sem_q is that query's
    class x mask probability. A well-behaved query has ONE large cov and the
    rest near zero. So the penalty is everything above the largest:

        excess_q = sum_i cov[q, i]  -  max_i cov[q, i]

    which is 0 for a clean query and grows with each extra building swallowed.
    Averaged over ACTIVE queries only (max_i cov > active_thr): with 200
    queries and ~26 instances per tile, most queries are parked on nothing,
    and including them would divide the signal by an almost constant ~180 and
    make the term untunable.

    Differentiable in both the mask logits and the class logits, and it never
    touches the assignment -- a query is free to move to whichever building it
    likes, it just may not hold two at once.

    Deliberately one-sided. The mirror term (many queries on one building, i.e.
    fragmentation, measured at 11.5% of GT) is NOT penalised here: suppressing
    duplicate queries is already the no-object class's job, and adding a
    "collapse onto one query" pressure fights the main loss's assignment. Use
    NMS/dedup at inference for that half.

    `pool` downsamples the probability field first. This term's one large
    intermediate is `sem`, at (B, Q, h, w) -- 105 MB at image-size 1024, Q=200,
    batch 2, and the autograd graph holds several tensors of that shape. Every
    quantity here is an AREA AVERAGE over an instance, so halving resolution
    changes the ratios negligibly and cuts that by 4x. Set pool=1 to disable.
    """
    ml = outputs.masks_queries_logits.float()
    cls = outputs.class_queries_logits.float().softmax(-1)[..., :-1].max(-1).values
    sem = cls[:, :, None, None] * ml.sigmoid()                    # (B, Q, h, w)
    if pool > 1 and min(sem.shape[-2:]) >= 2 * pool:
        # sigmoid THEN pool, not the reverse: pooling logits and then squashing
        # is not the mean probability, and it is the probability mass inside an
        # instance that `cov` is meant to measure.
        sem = F.avg_pool2d(sem, pool)
    b, q, h, w = sem.shape
    inst = instances_at(mask_labels, h, w)

    keep_mask = None
    if ignore is not None:
        keep_mask = 1.0 - _resize_to(ignore.float(), h, w)        # (B, h, w)

    total, n = sem.sum() * 0.0, 0
    for i in range(b):
        g = inst[i]
        if g.shape[0] < 2:            # nothing to confuse with
            continue
        if keep_mask is not None:
            g = g * keep_mask[i][None]
        gf = g.flatten(1)                                        # (N, hw)
        area = gf.sum(1)
        ok = area > 4                                            # drop slivers
        if int(ok.sum()) < 2:
            continue
        gf, area = gf[ok], area[ok]
        s = sem[i].flatten(1)                                    # (Q, hw)
        cov = (s @ gf.t()) / area[None].clamp_min(1.0)           # (Q, N)
        top = cov.amax(1)
        excess = cov.sum(1) - top
        act = top > active_thr
        if not bool(act.any()):
            continue
        total = total + excess[act].mean()
        n += 1
    return total / max(n, 1)


# --------------------------------------------------------------------------
# 3. mask-IoU regression target  (Tier 1)
# --------------------------------------------------------------------------
@torch.no_grad()
def maskiou_targets(outputs, mask_labels, mask_thr=0.0):
    """
    Per-query regression target for the mask-IoU head: the IoU between that
    query's binarised mask and the GT instance it overlaps most.

    MATCHING-FREE BY DESIGN, and that is not a compromise -- it is the exact
    quantity we want at inference. The oracle experiment that sized this whole
    change (AP 0.378 -> 0.508) ranked predictions by precisely
    `max over GT of IoU`, so the head is trained on the same target it is
    measured against. Using the Hungarian-matched GT instead would train the
    head on a different quantity than the one that pays off, and would couple
    it to `transformers` loss internals for no benefit.

    Unmatched / garbage queries get a target near 0, which is what we want
    them to learn to say about themselves.

    `mask_thr` is on the LOGIT (0.0 == sigmoid 0.5).
    Returns (B, Q) in [0, 1].
    """
    ml = outputs.masks_queries_logits
    b, q, h, w = ml.shape
    inst = instances_at(mask_labels, h, w)
    out = ml.new_zeros((b, q), dtype=torch.float32)
    for i in range(b):
        g = inst[i]
        if g.shape[0] == 0:
            continue
        p = (ml[i] > mask_thr).flatten(1).float()                # (Q, hw)
        gf = g.flatten(1)                                        # (N, hw)
        inter = p @ gf.t()                                       # (Q, N)
        union = p.sum(1)[:, None] + gf.sum(1)[None, :] - inter
        out[i] = (inter / union.clamp_min(1.0)).amax(1)
    return out


# --------------------------------------------------------------------------
# 4. fragmentation loss  (the mirror of collision_loss)
# --------------------------------------------------------------------------
def fragmentation_loss(outputs, mask_labels, active_thr=0.2, ignore=None,
                       pool=2):
    """
    Penalise TWO queries for splitting ONE GT building.

    The exact mirror of `collision_loss`, and it exists because leaving that
    term one-sided did not work. Measured on run1 (epoch 43) against v1:

        merges     (pred covering >=2 GT)   5.1% -> 5.2%   unchanged
        fragments  (GT covered by >=2 pred) 7.3% -> 9.9%   WORSE
        thin slivers (min side < 8 px)      0.3% -> 6.0%   20x worse

    collision_loss pushes a query to let go of the building it holds least,
    and nothing pushed back, so the model paid for merges by splitting. The
    original design note said NMS/dedup would handle that half; it does not,
    because two halves of one roof overlap barely at all and neither IoU nor
    containment NMS can see they belong together.

    Construction. Same cov matrix as collision_loss -- cov[q, i] is the
    fraction of instance i claimed by query q -- transposed:

        excess_i = sum_q cov[q, i]  -  max_q cov[q, i]

    0 when a single query owns the building, growing with every additional
    claimant. Averaged over ACTIVE instances only (some query claims more than
    `active_thr` of them), so a tile's empty background cannot dilute it.

    Note what this does NOT do: the max claimant is excluded, so the term never
    pushes against the query that actually owns the instance -- it only drains
    the runners-up, which is the same direction the no-object class already
    wants them to go. That is why it does not fight the Hungarian assignment.

    SCALE, exactly. When the claimants between them cover the instance once,
    the term reduces to

        excess_i = 1 - (largest claimant's share)

    so a clean instance scores 0, a 75/25 split scores 0.25, an even 2-way
    split 0.5, an even 3-way split 0.667, and the ceiling is 1. Verified
    against those closed-form values in selftest.py [14]. That makes it
    directly readable in the training log: `frg` 0.25 means the average
    contested building is losing a quarter of itself to a second query.
    """
    ml = outputs.masks_queries_logits.float()
    cls = outputs.class_queries_logits.float().softmax(-1)[..., :-1].max(-1).values
    sem = cls[:, :, None, None] * ml.sigmoid()
    if pool > 1 and min(sem.shape[-2:]) >= 2 * pool:
        sem = F.avg_pool2d(sem, pool)
    b, q, h, w = sem.shape
    inst = instances_at(mask_labels, h, w)

    keep_mask = None
    if ignore is not None:
        keep_mask = 1.0 - _resize_to(ignore.float(), h, w)

    total, n = sem.sum() * 0.0, 0
    for i in range(b):
        g = inst[i]
        if g.shape[0] == 0:
            continue
        if keep_mask is not None:
            g = g * keep_mask[i][None]
        gf = g.flatten(1)
        area = gf.sum(1)
        ok = area > 4
        if not bool(ok.any()):
            continue
        gf, area = gf[ok], area[ok]
        s = sem[i].flatten(1)
        cov = (s @ gf.t()) / area[None].clamp_min(1.0)      # (Q, N)
        top = cov.amax(0)                                   # per INSTANCE now
        excess = cov.sum(0) - top
        act = top > active_thr
        if not bool(act.any()):
            continue
        total = total + excess[act].mean()
        n += 1
    return total / max(n, 1)
