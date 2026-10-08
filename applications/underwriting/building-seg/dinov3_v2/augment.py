"""
Augmentation add-ons for the DINOv3 + Mask2Former building segmenter.

Two things:
  * rotate_any()  -- arbitrary-angle rotation, artifact-free
  * basa()        -- Batch Style Augmenter (batch-level, applied in the
                     training loop, NOT in __getitem__)

Import into train_dinov3_mask2former.py.
"""

import cv2
import numpy as np
import torch


# --------------------------------------------------------------------------
# 1. Arbitrary-angle rotation
# --------------------------------------------------------------------------
def rotate_any(img, masks, angle=None, min_keep=0.6, mode="pad"):
    """
    Rotate by an arbitrary angle. Two ways, and the default changed.

    mode="pad" (DEFAULT)
        Rotate in place and let the corners fill with black. Scale is
        PRESERVED. Black corners are unlike anything at test time and the model
        can in principle key off them -- that is the cost, and it is accepted
        deliberately, because the alternative was worse:

    mode="crop" (the old default)
        Rotate, crop the inscribed square (side S/sqrt(2)), resize back. No
        border fill, but an unavoidable 1.41x linear / 2.0x area ZOOM.

        Measured consequence on the stride256 train split: median instance area
        2288 px under D4 alone against 5398 px once an arbitrary angle fired --
        2.36x. So ROTATED buildings only ever reached the model MAGNIFIED, and
        a rotated building at native scale was never in the training
        distribution at all. On a held-out namdong scene whose buildings sit at
        ~30 deg (19.9% axis-aligned, against 99.6% in the training GT), run3
        produced blobby masks: rectangularity 0.9225 -> 0.7570, with 93.8% of
        masks below 0.90, and polygon vertices 5.5 -> 9.3.

        It also threw away supervision: instances surviving per sample fell
        from 29.6 to 11.4, because min_keep discards everything the inscribed
        square clips.

    Note D4 (the rot90 in aug_full) contributes NOTHING to orientation
    diversity -- mod 90 it is the identity on an axis-aligned building. This
    function is the only source of off-axis training signal, which is why its
    scale coupling mattered so much.

    min_keep: drop instances that lost more than (1 - min_keep) of their area
    to the frame. Truncated buildings are bad supervision -- the model is asked
    to predict a complete instance from a fragment.
    """
    H, W = img.shape[:2]
    if angle is None:
        angle = np.random.uniform(0, 360)

    # A multiple of 90 needs no crop -- do it exactly and keep the whole tile.
    if abs(angle % 90.0) < 1e-3:
        k = int(round(angle / 90.0)) % 4
        return (np.ascontiguousarray(np.rot90(img, k, (0, 1))),
                np.ascontiguousarray(np.rot90(masks, k, (1, 2))))

    M = cv2.getRotationMatrix2D((W / 2.0, H / 2.0), angle, 1.0)
    img_r = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if len(masks):
        m_r = np.stack([
            cv2.warpAffine(m, M, (W, H), flags=cv2.INTER_NEAREST,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            for m in masks])
    else:
        m_r = np.zeros((0, H, W), np.uint8)

    if mode == "pad":
        # Scale preserved; corners are black. Instances can still rotate partly
        # out of frame, so min_keep is applied against the PRE-rotation area --
        # an instance that lost most of itself to the frame edge is the same bad
        # supervision as one lost to a crop.
        if len(m_r):
            before = masks.reshape(len(masks), -1).sum(1).astype(np.float32)
            after = m_r.sum(axis=(1, 2)).astype(np.float32)
            m_r = m_r[after >= min_keep * np.maximum(before, 1)]
        return img_r, np.ascontiguousarray(m_r)

    # inscribed square -> guaranteed free of border fill
    s = int(min(H, W) / np.sqrt(2))
    y0, x0 = (H - s) // 2, (W - s) // 2
    img_c = img_r[y0:y0 + s, x0:x0 + s]
    m_c = m_r[:, y0:y0 + s, x0:x0 + s]

    # drop truncated instances (measured before resize, so scale cancels out)
    if len(m_c):
        before = m_r.sum(axis=(1, 2)).astype(np.float32)
        after = m_c.sum(axis=(1, 2)).astype(np.float32)
        m_c = m_c[after >= min_keep * np.maximum(before, 1)]

    img_o = cv2.resize(img_c, (W, H), interpolation=cv2.INTER_LINEAR)
    if len(m_c):
        m_o = np.stack([cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
                        for m in m_c])
    else:
        m_o = np.zeros((0, H, W), np.uint8)
    return img_o, m_o


# --------------------------------------------------------------------------
# 2. BaSA - Batch Style Augmenter
# --------------------------------------------------------------------------
def basa(x, alpha=0.3, p=0.5, extrap=(1.0, 3.0), eps=1e-6):
    """
    Parameter-free style augmentation on a batch of normalized images.

    Mechanism (MixStyle family): a per-image, per-channel (mean, std) pair is
    treated as that image's "style". Whitening and re-colouring with a
    different style changes appearance while leaving geometry untouched --
    which is what you want, since the masks stay valid with no transform.

    The "style-inverted batch" part: mixing only with styles present in the
    batch confines you to their convex hull, and with 300 tiles from one scene
    that hull is tiny. So each style is also reflected through the batch
    centroid (arithmetically for mean, geometrically for std, since std is
    positive) to synthesize styles on the far side of the observed
    distribution. Sampling from {shuffled real} u {inverted} extrapolates
    instead of interpolating.

    Apply AFTER processor normalization, in the training loop -- it needs the
    whole batch, so it cannot live in __getitem__.

    x: (B, C, H, W) float tensor. Returns same shape.
    """
    B = x.shape[0]
    if B < 2 or np.random.rand() > p:
        return x

    mu = x.mean(dim=(2, 3), keepdim=True)
    sd = x.std(dim=(2, 3), keepdim=True).clamp_min(eps)
    x_norm = (x - mu) / sd

    mu_c = mu.mean(dim=0, keepdim=True)
    sd_c = sd.mean(dim=0, keepdim=True)

    # Reflect AND amplify. Plain reflection (g = 1) maps a symmetric batch onto
    # itself -- verified empirically: 0/200 draws escaped the batch hull. The
    # gain g > 1 is what actually extrapolates.
    g = torch.empty(B, 1, 1, 1, device=x.device, dtype=x.dtype).uniform_(*extrap)
    mu_inv = mu_c - g * (mu - mu_c)                        # arithmetic
    sd_inv = (sd_c * (sd_c / sd) ** g).clamp_min(eps)      # geometric (sd > 0)

    perm = torch.randperm(B, device=x.device)
    pool_mu = torch.cat([mu[perm], mu_inv], dim=0)
    pool_sd = torch.cat([sd[perm], sd_inv], dim=0)

    pick = torch.randint(0, 2 * B, (B,), device=x.device)
    tgt_mu, tgt_sd = pool_mu[pick], pool_sd[pick]

    lam = torch.from_numpy(
        np.random.beta(alpha, alpha, size=(B, 1, 1, 1)).astype(np.float32)
    ).to(x.device, x.dtype)

    return x_norm * (lam * sd + (1 - lam) * tgt_sd) + \
        (lam * mu + (1 - lam) * tgt_mu)


# --------------------------------------------------------------------------
# 3. Drop-in replacement for BuildingInstanceDataset._aug
# --------------------------------------------------------------------------
def aug_full(img, masks, p_rot_any=0.5, p_scale=0.8,
             scale_range=(0.5, 2.0), min_keep=0.6, rot_mode="pad"):
    """
    Geometric: scale jitter -> D4 -> arbitrary rotation (sometimes).
    Photometric: per-channel gain, gamma, contrast.

    Handles len(masks) == 0 so empty tiles still get photometric variation.
    """
    H, W = img.shape[:2]

    # --- scale jitter, ZOOM IN ONLY (upscale then random crop).
    #
    # Zooming out of a pre-tiled 512 crop is impossible without inventing
    # pixels: you would resize down and pad, leaving up to 60% of the canvas
    # black (measured). Reflect-padding is worse -- it mirrors unlabelled
    # buildings into the pad, manufacturing false negatives.
    #
    # Note this means scale jitter alone CANNOT make buildings smaller, which
    # is the direction you actually need (Daegu sheds are 3-5x the Incheon
    # workshops). Use mosaic() for that, or re-tile from the source scene.
    #
    # MAGNIFICATION IS LOAD-BEARING, not cosmetic. Korean industrial buildings
    # sit a median 1.9 px apart at 0.5 m/px, and Mask2Former predicts masks at
    # 1/4 of its input -- one mask cell is 2 tile px -- so the median gap
    # between neighbours lands exactly on the resolution limit and 58% of
    # buildings are below it. Zooming in widens those gaps in feature space.
    #
    # This is what run3 got for free from rotate_any's old crop mode (1.41x on
    # top of this jitter, mean magnification 1.83 against run4's 1.40). Fixing
    # that zoom was right -- it was breaking rotation -- but it also removed a
    # separation aid, and run4 merges 2.7x more than run3 on dense tiles
    # (12.4% vs 4.6% of predictions covering two buildings) while being
    # identical on sparse ones. Set the range deliberately rather than
    # inheriting it from a bug.
    if np.random.rand() < p_scale:
        s = np.random.uniform(max(scale_range[0], 1.0), scale_range[1])
        nh, nw = max(int(H * s), H), max(int(W * s), W)
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        masks = (np.stack([cv2.resize(m, (nw, nh), interpolation=cv2.INTER_NEAREST)
                           for m in masks]) if len(masks)
                 else np.zeros((0, nh, nw), np.uint8))
        y = np.random.randint(0, nh - H + 1)
        x = np.random.randint(0, nw - W + 1)
        img = img[y:y + H, x:x + W]
        masks = masks[:, y:y + H, x:x + W]

    # --- D4: exact pixel permutations, no interpolation
    k = np.random.randint(4)
    img = np.rot90(img, k, (0, 1))
    masks = np.rot90(masks, k, (1, 2))
    if np.random.rand() < 0.5:
        img = img[:, ::-1]
        masks = masks[:, :, ::-1]
    img = np.ascontiguousarray(img)
    masks = np.ascontiguousarray(masks)

    # --- arbitrary angle on top of D4: together these cover the full circle
    if np.random.rand() < p_rot_any:
        img, masks = rotate_any(img, masks,
                                angle=np.random.uniform(0, 15),
                                min_keep=min_keep, mode=rot_mode)

    # --- photometric
    #
    # Brightness and colour CAST are sampled separately. They used to be one
    # per-channel uniform(0.8, 1.2), which can produce a cast only when two
    # channels happen to land at opposite extremes -- rare, and the range was
    # narrower than the training set's own spread.
    #
    # Measured on the stride256 tiles: per-tile channel means span 0.59-1.43 of
    # their split mean, so 0.8-1.2 covered less than half the natural variation.
    # And a held-out namdong scene sat at R/B 0.802 against the training set's
    # 0.950 +- 0.085 -- a 1.7-sigma colour cast at only 0.891x brightness, i.e.
    # mostly cast rather than exposure.
    #
    # So: a global exposure factor covering the observed 0.891x with margin,
    # then an independent per-channel cast. Their product spans R/B ratios from
    # 0.85/1.15 = 0.74 to 1.35, which contains the 0.844x shift comfortably.
    f = img.astype(np.float32)
    f *= np.random.uniform(0.70, 1.35)                          # exposure
    f *= np.random.uniform(0.85, 1.15, size=(1, 1, 3))          # colour cast
    f = 255.0 * np.power(np.clip(f, 0, 255) / 255.0, np.random.uniform(0.7, 1.4))
    m = f.mean()
    f = m + (f - m) * np.random.uniform(0.8, 1.25)
    img = np.clip(f, 0, 255).astype(np.uint8)

    return img, np.ascontiguousarray(masks)


# --------------------------------------------------------------------------
# 4. Mosaic - the only way to get SMALLER buildings from pre-tiled data
# --------------------------------------------------------------------------
def mosaic(samples, out_size=512, min_area=16, jitter=0.25):
    """
    Compose k*k tiles (k=2 by default via 4 samples) into one canvas.

    Why this matters more than it looks: it is the one augmentation that
    increases instance density AND decreases apparent building size at the
    same time, using only data you already have and inventing no pixels.

    Those are precisely the two confirmed differences between the training
    scene (large sheds, ~5-15 instances/tile, well separated) and the failure
    case (small workshops, 40+ instances/tile, sharing walls). Photometric
    augmentation cannot touch either.

    A 2x2 mosaic halves apparent building size and roughly quadruples
    instances per tile. The random split point also creates abutting
    boundaries between unrelated buildings, which is exactly the adjacency
    regime that produces merged masks at test time.

    samples: list of 4 (img HxWx3 uint8, masks NxHxW uint8)
    """
    S = out_size
    canvas = np.zeros((S, S, 3), np.uint8)
    out_masks = []

    # jittered split point so the seam is not always centred
    cx = int(S * np.random.uniform(0.5 - jitter, 0.5 + jitter))
    cy = int(S * np.random.uniform(0.5 - jitter, 0.5 + jitter))
    cells = [(0, 0, cx, cy), (cx, 0, S - cx, cy),
             (0, cy, cx, S - cy), (cx, cy, S - cx, S - cy)]

    for (img, masks), (x0, y0, w, h) in zip(samples, cells):
        if w < 8 or h < 8:
            continue
        H, W = img.shape[:2]
        # take a random sub-window of the source with the cell's aspect ratio,
        # then resize down into the cell -> genuine scale reduction
        ar = w / h
        if W / H > ar:
            sh = H
            sw = int(H * ar)
        else:
            sw = W
            sh = int(W / ar)
        sy = np.random.randint(0, H - sh + 1)
        sx = np.random.randint(0, W - sw + 1)

        sub = img[sy:sy + sh, sx:sx + sw]
        canvas[y0:y0 + h, x0:x0 + w] = cv2.resize(
            sub, (w, h), interpolation=cv2.INTER_AREA)

        for m in masks:
            ms = m[sy:sy + sh, sx:sx + sw]
            if ms.sum() == 0:
                continue
            mr = cv2.resize(ms, (w, h), interpolation=cv2.INTER_NEAREST)
            if mr.sum() < min_area:
                continue
            full = np.zeros((S, S), np.uint8)
            full[y0:y0 + h, x0:x0 + w] = mr
            out_masks.append(full)

    return canvas, (np.stack(out_masks) if out_masks
                    else np.zeros((0, S, S), np.uint8))