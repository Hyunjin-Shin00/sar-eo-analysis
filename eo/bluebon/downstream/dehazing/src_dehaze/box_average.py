#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Oct 10 18:27:26 2025

@author: yp
"""

import numpy as np
from scipy import ndimage
from skimage.util import view_as_windows  # pip install scikit-image

def box_average_with_overlap_interpolated(
    image: np.ndarray,
    mask: np.ndarray,
    box: int = 32,              # box/window size (e.g., 32x32)
    stride: int = 8,            # overlap control: smaller than `box`
    min_count: int = 1,         # min valid pixels per box
    upsample: str = "bilinear", # "bilinear" or "nearest"
    pad_mode: str = "reflect",  # padding before windowing
):
    """
    1) Centered, overlapped box averages sampled on a coarse grid (step=stride).
    2) Interpolate coarse grid back to full resolution.

    True in `mask` means valid pixel; NaNs in image are treated as invalid.
    Returns (full_res, coarse, counts).
    """
    if image.ndim != 2 or mask.ndim != 2 or image.shape != mask.shape:
        raise ValueError("image and mask must be 2D arrays of the same shape")
    if stride <= 0 or box <= 0:
        raise ValueError("box and stride must be positive")
    if upsample not in ("bilinear", "nearest"):
        raise ValueError("upsample must be 'bilinear' or 'nearest'")

    H, W = image.shape
    valid = mask & np.isfinite(image)
    x = np.where(valid, image.astype(float), np.nan)

    # Centered windows → pad by half the box so the first window center is at (0,0)
    pad = box // 2
    xpad = np.pad(x, pad_width=pad, mode=pad_mode)

    # Build overlapped windows with step=stride → shape (Hc, Wc, box, box)
    win = view_as_windows(xpad, (box, box), step=stride)
    Hc, Wc = win.shape[:2]

    # Compute masked mean per window
    sums   = np.nansum(win, axis=(-1, -2))
    counts = np.sum(~np.isnan(win), axis=(-1, -2))
    coarse = sums / counts
    coarse[counts < min_count] = np.nan

    # Interpolate coarse grid back to original resolution
    if upsample == "nearest":
        # Expand coarse grid to an approximate size, then crop
        zoom_r = max(1, int(np.ceil(H / Hc)))
        zoom_c = max(1, int(np.ceil(W / Wc)))
        full_res = np.repeat(np.repeat(coarse, zoom_r, axis=0), zoom_c, axis=1)[:H, :W]
    else:
        # Bilinear interpolation
        full_res = ndimage.zoom(
            coarse,
            zoom=(H / Hc, W / Wc),
            order=1,  # bilinear
            prefilter=False
        )[:H, :W]

    return full_res, coarse, counts

# Example:
# full, coarse, cnt = box_average_with_overlap_interpolated(
#     image=img, mask=msk, box=32, stride=8, min_count=20, upsample="bilinear"
# )
