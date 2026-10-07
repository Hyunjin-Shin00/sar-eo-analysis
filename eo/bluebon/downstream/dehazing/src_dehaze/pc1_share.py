#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct 13 17:37:07 2025

@author: yp
"""

import numpy as np
from typing import Tuple

def _pc1_share_and_corrpart_patch(X: np.ndarray) -> Tuple[float, np.ndarray]:
    """
    X: (N, 4) array for one patch, rows=pixels in the patch, cols=bands.
    Returns:
      share: float in [0, 1]
      corr_part: (N, 4) correlated component in ORIGINAL units (variation around mean)
    """
    # z-score columns
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=1)
    sd_safe = np.where(sd == 0, 1.0, sd)
    Xz = (X - mu) / sd_safe

    # correlation PCA (4x4)
    R = np.corrcoef(Xz, rowvar=False)
    evals, evecs = np.linalg.eigh(R)        # ascending
    idx = np.argsort(evals)[::-1]
    lam1 = float(evals[idx[0]])
    v1   = evecs[:, idx[0]]                 # (4,)

    # rank-1 reconstruction in z-space
    scores = Xz @ v1                        # (N,)
    corr_part_z = np.outer(scores, v1)      # (N, 4)

    # back to original units (variation only; mean is NOT added)
    corr_part = corr_part_z * sd_safe       # (N, 4)

    # PC1 share on correlation matrix
    share = lam1 / 4.0
    return share, corr_part


def pc1_share_and_corrpart_sliding(
    I: np.ndarray,
    box_h: int,
    box_w: int,
    overlap_h: float = 0.5,
    overlap_w: float = 0.5,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Sliding-window PC1 share and correlated component for a 4-band image.

    Parameters
    ----------
    I : array (H, W, 4)
        Input image with 4 bands (last axis = bands). NaNs are allowed; they’re dropped per box.
    box_h, box_w : int
        Box (window) height and width in pixels.
    overlap_h, overlap_w : float in [0, 1)
        Fractional overlap between consecutive boxes vertically and horizontally.

    Returns
    -------
    share_map : array (n_boxes_h, n_boxes_w)
        PC1 share per box.
    corr_part : array (H, W, 4)
        Per-pixel correlated component (in original units), formed by averaging
        the rank-1 reconstructions from all boxes covering that pixel.
        (Variation around the local box mean; no global mean is added.)
    """
    H, W, D = I.shape
    assert D == 4, "The last dimension must be 4 bands."

    # strides from overlap
    sh = max(1, int(round(box_h * (1.0 - overlap_h))))
    sw = max(1, int(round(box_w * (1.0 - overlap_w))))

    # number of valid boxes (no padding; only boxes fully inside the image)
    nbh = 1 + (H - box_h) // sh if H >= box_h else 0
    nbw = 1 + (W - box_w) // sw if W >= box_w else 0

    share_map = np.full((nbh, nbw), np.nan, dtype=float)
    corr_sum  = np.zeros_like(I, dtype=float)
    corr_cnt  = np.zeros((H, W, 1), dtype=float)

    for bi in range(nbh):
        top = bi * sh
        for bj in range(nbw):
            left = bj * sw
            patch = I[top:top+box_h, left:left+box_w, :]   # (bh, bw, 4)

            # handle NaNs: mask out any pixel with NaN in any band
            mask = ~np.isnan(patch).any(axis=2)
            if not mask.any():
                continue

            X = patch[mask].reshape(-1, 4)  # (N, 4)
            # need at least 2 valid pixels to form correlations
            if X.shape[0] < 2:
                continue

            share, corr_part_flat = _pc1_share_and_corrpart_patch(X)
            share_map[bi, bj] = share

            # put the correlated component back into the window grid
            corr_patch = np.zeros_like(patch, dtype=float)
            # only fill valid pixels; invalid stay 0 (and won’t be counted)
            corr_patch[mask] = corr_part_flat

            # accumulate (for averaging where windows overlap)
            corr_sum[top:top+box_h, left:left+box_w, :] += corr_patch
            corr_cnt[top:top+box_h, left:left+box_w, :] += mask[..., None].astype(float)

    # average overlapping contributions; keep zeros where never covered
    with np.errstate(divide='ignore', invalid='ignore'):
        corr_part = np.where(corr_cnt > 0, corr_sum / corr_cnt, 0.0)

    return share_map, corr_part


# ---------------- Example ----------------
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    H, W = 256, 256
    # synthetic 4-band image with a smooth common factor plus noise
    y, x = np.mgrid[0:H, 0:W]
    common = np.sin(2*np.pi*x/64) * np.cos(2*np.pi*y/64)  # smooth “factor”
    loads  = np.array([0.9, 0.7, 0.6, 0.4])
    noise  = rng.standard_normal((H, W, 4)) * 0.8
    I = common[..., None] * loads + noise

    share_map, corr_part = pc1_share_and_corrpart_sliding(
        I, box_h=32, box_w=32, overlap_h=0.5, overlap_w=0.5
    )
    print("share_map shape:", share_map.shape)
    print("corr_part shape:", corr_part.shape)
    print("share_map median:", np.nanmedian(share_map))
