#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Oct 12 21:47:42 2025

@author: yp
"""

from __future__ import annotations
import numpy as np

def masked_histogram(
    image: np.ndarray,
    mask: np.ndarray,
    bins=256,                 # int or sequence of bin edges
    range=None,               # (min, max) for bins if bins is int
    density=False,            # True → PDF; False → counts
    weights: np.ndarray | None = None,  # optional weights, same shape as image
):
    """
    Compute a histogram over pixels that are BOTH non-NaN and unmasked.

    Assumptions
    -----------
    `mask` is boolean with True = valid/keep, False = ignore.
    NaNs in `image` are always ignored.

    Returns
    -------
    hist : (B,) array of counts or probabilities (if density=True)
    edges: (B+1,) array of bin edges
    centers: (B,) array of bin centers (useful for plotting)
    n_valid: number of pixels included (after mask & NaN filter)
    """
    if image.shape != mask.shape:
        raise ValueError("image and mask must have the same shape")

    # valid pixels: mask==True and value is finite
    valid = mask & np.isfinite(image)

    if weights is not None:
        if weights.shape != image.shape:
            raise ValueError("weights must have the same shape as image")
        w = weights[valid].ravel().astype(float)
    else:
        w = None

    vals = image[valid].ravel().astype(float)
    n_valid = vals.size

    if n_valid == 0:
        # Return empty-ish results consistent with np.histogram
        hist = np.zeros(bins if isinstance(bins, int) else (len(bins) - 1,), dtype=float)
        if isinstance(bins, int):
            # fabricate edges if nothing to compute from
            lo, hi = (0.0, 1.0) if range is None else range
            edges = np.linspace(lo, hi, hist.size + 1)
        else:
            edges = np.asarray(bins, dtype=float)
        centers = 0.5 * (edges[:-1] + edges[1:])
        return hist, edges, centers, 0

    hist, edges = np.histogram(vals, bins=bins, range=range, weights=w, density=density)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return hist, edges, centers, n_valid
