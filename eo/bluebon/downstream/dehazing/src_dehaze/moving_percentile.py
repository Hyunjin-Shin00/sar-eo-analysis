#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Oct 10 17:20:53 2025

@author: yp
"""

import numpy as np
from scipy import ndimage
from skimage.util import view_as_windows  # pip install scikit-image

def local_percentile_interpolated(
    image: np.ndarray,
    mask: np.ndarray,
    q: float = 90,
    window: int = 31,     # odd; e.g., 31x31 neighborhood
    stride: int = 8,      # overlap control: smaller = denser sampling
    min_count: int = 10,  # min valid pixels required in a window
    fill_border: bool = True,  # fill any NaNs after interpolation via nearest
):
    """
    Compute a local percentile on a coarse overlapped grid, then interpolate
    back to per-pixel resolution. Masked (False) pixels are ignored in each window.

    Returns
    -------
    full_res : (H, W) float array
        Interpolated per-pixel percentile map (NaN where insufficient support).
    coarse   : (Hc, Wc) float array
        Coarse grid of window percentiles prior to interpolation.
    """

    if image.ndim != 2 or mask.ndim != 2 or image.shape != mask.shape:
        raise ValueError("image and mask must be 2D arrays of the same shape")

    H, W = image.shape
    x = image.astype(float).copy()
    x[~mask] = np.nan

    # pad so windows are centered all the way to the edges
    pad = window // 2
    xpad = np.pad(x, pad_width=pad, mode="reflect")

    # make overlapped windows with step=stride
    # windows shape: (Hc, Wc, window, window)
    win = view_as_windows(xpad, (window, window), step=stride)

    # count valid samples per window
    valid_counts = np.sum(~np.isnan(win), axis=(-1, -2))

    # percentile per window, ignoring NaNs
    coarse = np.nanpercentile(win, q, axis=(-1, -2))

    # enforce min_count requirement
    coarse = np.where(valid_counts >= min_count, coarse, np.nan)

    # interpolate coarse grid to full resolution (bilinear)
    # ndimage.zoom maps (Hc, Wc) -> approx (H, W) with order=1 (linear)
    zoom_r = H / coarse.shape[0]
    zoom_c = W / coarse.shape[1]
    full_res = ndimage.zoom(coarse, zoom=(zoom_r, zoom_c), order=1)

    # exact crop to (H, W) in case of rounding
    full_res = full_res[:H, :W]

    # optional: fill any NaNs (e.g., where coarse cells lacked min_count)
    if fill_border and np.isnan(full_res).any():
        nanmask = np.isnan(full_res)
        if nanmask.all():
            # nothing to fill; return as-is
            return full_res, coarse
        # nearest-neighbor fill using distance transform
        dist, (ii, jj) = ndimage.distance_transform_edt(
            nanmask, return_indices=True
        )
        filled = full_res.copy()
        filled[nanmask] = full_res[ii[nanmask], jj[nanmask]]
        full_res = filled

    return full_res, coarse

# Example:
# full, coarse = local_percentile_interpolated(img, msk, q=90, window=31, stride=8, min_count=20)
