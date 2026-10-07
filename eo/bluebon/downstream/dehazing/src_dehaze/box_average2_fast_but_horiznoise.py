#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Oct 10 18:27:26 2025

@author: yp
"""

from __future__ import annotations
import numpy as np
from scipy import ndimage
from scipy.interpolate import griddata
from skimage.util import view_as_windows  # pip install scikit-image

def _fill_nan_nearest(arr: np.ndarray) -> np.ndarray:
    """Fill NaNs by nearest neighbor on a 2D grid."""
    nanmask = np.isnan(arr)
    if not np.any(nanmask):
        return arr
    _, (ii, jj) = ndimage.distance_transform_edt(nanmask, return_indices=True)
    filled = arr.copy()
    filled[nanmask] = arr[ii[nanmask], jj[nanmask]]
    return filled

def _fill_nan_linear_with_nearest_fallback(arr: np.ndarray) -> np.ndarray:
    """Linear (bilinear on grid) fill for NaNs; nearest fallback outside convex hull."""
    Hc, Wc = arr.shape
    yy, xx = np.mgrid[0:Hc, 0:Wc]
    good = np.isfinite(arr)
    if not np.any(good):
        return arr  # nothing to interpolate from
    points = np.column_stack((yy[good], xx[good]))
    values = arr[good]
    # Linear interpolation at all grid points
    interp = griddata(points, values, (yy, xx), method="linear")
    # Fill holes (outside convex hull) with nearest neighbor
    if np.isnan(interp).any():
        interp_nn = griddata(points, values, (yy, xx), method="nearest")
        interp = np.where(np.isnan(interp), interp_nn, interp)
    return interp


# def box_average_with_overlap_interpolated(
#     image: np.ndarray,
#     mask: np.ndarray,
#     box: int = 32,              # box/window size (e.g., 32x32)
#     stride: int = 8,            # overlap control: smaller than `box`
#     min_count: int = 1,         # min valid pixels per box
#     upsample: str = "bilinear", # "bilinear" or "nearest"
#     pad_mode: str = "reflect",  # padding before windowing
#     coarse_fill: str | None = None, # None | "nearest" | "linear"
# ):
#     """
#     1) Centered, overlapped box averages sampled on a coarse grid (step=stride).
#     2) Optionally fill NaNs in coarse via interpolation.
#     3) Interpolate coarse grid back to full resolution.

#     True in `mask` means valid pixel; NaNs in image are treated as invalid.
#     Returns (full_res, coarse, counts).
#     """
#     if image.ndim != 2 or mask.ndim != 2 or image.shape != mask.shape:
#         raise ValueError("image and mask must be 2D arrays of the same shape")
#     if stride <= 0 or box <= 0:
#         raise ValueError("box and stride must be positive")
#     if upsample not in ("bilinear", "nearest"):
#         raise ValueError("upsample must be 'bilinear' or 'nearest'")
#     if coarse_fill not in (None, "nearest", "linear"):
#         raise ValueError("coarse_fill must be None, 'nearest', or 'linear'")

#     H, W = image.shape
#     valid = mask & np.isfinite(image)
#     x = np.where(valid, image.astype(float), np.nan)

#     # Centered windows → pad by half the box so the first window center is at (0,0)
#     pad = box // 2
#     xpad = np.pad(x, pad_width=pad, mode=pad_mode)

#     # Build overlapped windows with step=stride → shape (Hc, Wc, box, box)
#     win = view_as_windows(xpad, (box, box), step=stride)
#     Hc, Wc = win.shape[:2]

#     # Compute masked mean per window
#     sums   = np.nansum(win, axis=(-1, -2))
#     counts = np.sum(~np.isnan(win), axis=(-1, -2))
#     idx = counts >= min_count
#     coarse = np.full_like(sums, np.nan)
#     coarse[idx] = sums[idx] / counts[idx]
#     # coarse[counts < min_count] = np.nan

#     # === New: fill NaNs in coarse, if requested ===
#     if coarse_fill == "nearest":
#         coarse = _fill_nan_nearest(coarse)
#     elif coarse_fill == "linear":
#         coarse = _fill_nan_linear_with_nearest_fallback(coarse)
#     # (If None, keep NaNs.)
    
#     # Interpolate coarse grid back to original resolution
#     if upsample == "nearest":
#         # Expand coarse grid to an approximate size, then crop
#         zoom_r = max(1, int(np.ceil(H / Hc)))
#         zoom_c = max(1, int(np.ceil(W / Wc)))
#         full_res = np.repeat(np.repeat(coarse, zoom_r, axis=0), zoom_c, axis=1)[:H, :W]
#     else:
#         # Bilinear interpolation
#         full_res = ndimage.zoom(
#             coarse,
#             zoom=(H / Hc, W / Wc),
#             order=1,  # bilinear
#             prefilter=False
#         )[:H, :W]

#     return full_res, coarse, counts

# # Example:
# # # Fill coarse gaps with nearest neighbor, then bilinear upsample to full-res
# # full, coarse, cnt = box_average_with_overlap_interpolated(
# #     img, msk, box=32, stride=8, min_count=20,
# #     coarse_fill="nearest", upsample="bilinear"
# # )

# # # Or, do a smoother coarse fill (bilinear on the coarse lattice) with nearest fallback:
# # full, coarse, cnt = box_average_with_overlap_interpolated(
# #     img, msk, box=32, stride=8, min_count=20,
# #     coarse_fill="linear", upsample="bilinear"
# # )

# def wrap_boxaverage(img, msk_clean, boxsize, q):
#     arr = np.asarray(img)
#     squeeze_single = False

#     if arr.ndim == 2:  # single band
#         arr = arr[None, ...]  # -> (1, H, W)
#         squeeze_single = True
#         nb, H, W = arr.shape
#     elif arr.ndim == 3:
#         nb, H, W = arr.shape
            
#     stride=boxsize//2
#     minc=boxsize#*boxsize//20
    
#     rhot_ave = [] ; rhot_p=[]
#     for ib in range(nb):
#         full, coarse, cnt = box_average_with_overlap_interpolated(
#             image=arr[ib,:,:], mask=msk_clean, box=boxsize, stride=stride, min_count=minc, coarse_fill="linear", upsample="bilinear"  )
#         rhot_ave.append(full)
#         percentile = np.nanpercentile(coarse, q)
#         rhot_p.append(percentile)
#     if squeeze_single:
#         rhot_ave = rhot_ave[0]  # -> (H, W)
#         rhot_p = rhot_p[0] 
#     return rhot_ave, rhot_p


from scipy.ndimage import distance_transform_edt
import cv2  # pip install opencv-python-headless
from multiprocessing.pool import ThreadPool

def _fill_nan_nearest_fast(coarse):
    """Fast NaN fill using distance transform."""
    nan_mask = np.isnan(coarse)
    if not nan_mask.any():
        return coarse
    out = coarse.copy()
    _, idx = distance_transform_edt(nan_mask, return_indices=True)
    out[nan_mask] = coarse[idx[0][nan_mask], idx[1][nan_mask]]
    return out

from scipy.interpolate import RegularGridInterpolator

def upsample_bilinear_proper(coarse, H, W, stride):
    Hc, Wc = coarse.shape

    # Actual center coordinates of each coarse box in full-res pixel space
    y_c = np.arange(Hc, dtype=np.float32) * stride
    x_c = np.arange(Wc, dtype=np.float32) * stride

    # Clamp last point to image boundary (handles edge windows)
    y_c = np.clip(y_c, 0, H - 1)
    x_c = np.clip(x_c, 0, W - 1)

    y_f = np.arange(H)
    x_f = np.arange(W)

    interp = RegularGridInterpolator(
        (y_c, x_c), coarse,
        method='linear',
        bounds_error=False,
        fill_value=None  # extrapolate at edges
    )
    yy, xx = np.meshgrid(y_f, x_f, indexing='ij')
    return interp((yy, xx)).astype(np.float32)


def _box_sums_integral(x_valid, valid_float, box, stride, pad_mode='reflect'):
    H, W = x_valid.shape
    pad = box // 2

    # Use reflect padding for values (avoids zero-pull bias at boundaries)
    # Use zero padding for valid mask (outside is truly invalid)
    xp = np.pad(x_valid,    pad, mode=pad_mode)
    vp = np.pad(valid_float, pad, mode='constant', constant_values=0.0)

    # In-place 2D cumsum
    ix = np.zeros((xp.shape[0]+1, xp.shape[1]+1), dtype=np.float32)
    iv = np.zeros((xp.shape[0]+1, xp.shape[1]+1), dtype=np.float32)
    np.cumsum(xp, axis=0, out=xp); np.cumsum(xp, axis=1, out=xp)
    np.cumsum(vp, axis=0, out=vp); np.cumsum(vp, axis=1, out=vp)
    ix[1:, 1:] = xp
    iv[1:, 1:] = vp

    Hc = (H + 2*pad - box) // stride + 1
    Wc = (W + 2*pad - box) // stride + 1

    rs = np.arange(Hc, dtype=np.int32) * stride
    cs = np.arange(Wc, dtype=np.int32) * stride
    r1, r2 = rs, rs + box
    c1, c2 = cs, cs + box

    sums   = (ix[r2[:,None], c2[None,:]] - ix[r1[:,None], c2[None,:]]
            - ix[r2[:,None], c1[None,:]] + ix[r1[:,None], c1[None,:]])
    counts = (iv[r2[:,None], c2[None,:]] - iv[r1[:,None], c2[None,:]]
            - iv[r2[:,None], c1[None,:]] + iv[r1[:,None], c1[None,:]])

    return sums, counts.astype(np.int32), Hc, Wc


def box_average_fast(image, mask, box=32, stride=8, min_count=1,
                     upsample="bilinear", coarse_fill=None):
    H, W = image.shape
    valid   = mask & np.isfinite(image)
    x_valid = np.where(valid, image.astype(np.float32), 0.0)

    sums, counts, Hc, Wc = _box_sums_integral(
        x_valid, valid.astype(np.float32), box, stride
    )

    coarse = np.full((Hc, Wc), np.nan, dtype=np.float32)
    idx = counts >= min_count
    coarse[idx] = sums[idx] / counts[idx]

    if coarse_fill in ("nearest", "linear"):
        coarse = _fill_nan_nearest_fast(coarse)

    # Pass stride so coarse centers are correctly mapped
    full_res = upsample_bilinear_proper(coarse, H, W, stride)

    return full_res, coarse, counts


def wrap_boxaverage(img, msk_clean, boxsize, q, n_workers=4):
    arr = np.asarray(img, dtype=np.float32)  # float32 upfront
    squeeze_single = False

    if arr.ndim == 2:
        arr = arr[None, ...]
        squeeze_single = True
    nb, H, W = arr.shape

    stride = boxsize // 2
    minc   = boxsize

    # Pre-convert mask once
    msk = np.asarray(msk_clean, dtype=bool)

    def process_band(ib):
        full, coarse, _ = box_average_fast(
            image=arr[ib], mask=msk,
            box=boxsize, stride=stride, min_count=minc,
            coarse_fill="linear", upsample="bilinear"
        )
        return full, float(np.nanpercentile(coarse, q))

    with ThreadPool(min(n_workers, nb)) as pool:
        results = pool.map(process_band, range(nb))

    rhot_ave = [r[0] for r in results]
    rhot_p   = [r[1] for r in results]

    if squeeze_single:
        return rhot_ave[0], rhot_p[0]
    return rhot_ave, rhot_p

def fill_nearest(arr):
    mask = np.isnan(arr)
    # indices of nearest non-nan elements
    idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return arr[tuple(idx)]