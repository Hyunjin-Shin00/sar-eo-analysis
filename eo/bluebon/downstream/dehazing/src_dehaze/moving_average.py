#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Oct 10 18:11:43 2025

@author: yp
"""
from __future__ import annotations
import numpy as np
from scipy import ndimage

def moving_average_masked(
    image: np.ndarray,
    mask: np.ndarray,
    window: int = 15,          # odd window size (e.g., 15 -> 15x15)
    min_count: int = 1,        # require at least this many valid pixels
    mode: str = "reflect",     # border handling for ndimage.convolve
    footprint: np.ndarray | None = None,  # optional boolean footprint
) -> np.ndarray:
    """
    Mask-aware moving mean using fast convolutions.
    True in `mask` means "valid / include".
    NaNs in `image` are treated as invalid automatically.
    """
    if image.ndim != 2 or mask.ndim != 2 or image.shape != mask.shape:
        raise ValueError("image and mask must be 2D arrays of the same shape")

    # valid = pixels that are both unmasked and finite
    valid = mask & np.isfinite(image)
    img0 = np.where(valid, image, 0.0).astype(float)

    if footprint is None:
        kernel = np.ones((window, window), dtype=float)
    else:
        if footprint.dtype != bool:
            footprint = footprint.astype(bool)
        kernel = footprint.astype(float)

    # numerator: sum of valid pixel values in each window
    num = ndimage.convolve(img0, kernel, mode=mode, cval=0.0)
    # denominator: count of valid pixels in each window
    den = ndimage.convolve(valid.astype(float), kernel, mode=mode, cval=0.0)

    out = np.divide(num, den, out=np.full_like(num, np.nan, dtype=float), where=den > 0)
    out[den < min_count] = np.nan
    return out