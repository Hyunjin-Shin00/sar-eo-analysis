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
    # return rhot_ave, rhot_p


from scipy.interpolate import RegularGridInterpolator
from concurrent.futures import ThreadPoolExecutor

from scipy.ndimage import map_coordinates

#TEST back due to horizontal line noises
def box_average_with_overlap_interpolated(
    image: np.ndarray,
    mask: np.ndarray,
    box: int = 32,
    stride: int = 8,
    min_count: int = 1,
    upsample: str = "bilinear",
    pad_mode: str = "reflect",
    coarse_fill: str | None = None,
):
    if image.ndim != 2 or mask.ndim != 2 or image.shape != mask.shape:
        raise ValueError("image and mask must be 2D arrays of the same shape")

    H, W = image.shape
    valid = mask & np.isfinite(image)
    #-------Original
    x = np.where(valid, image.astype(float), np.nan)

    pad = box // 2
    xpad = np.pad(x, pad_width=pad, mode=pad_mode)

    win = view_as_windows(xpad, (box, box), step=stride)
    Hc, Wc = win.shape[:2]

    sums   = np.nansum(win, axis=(-1, -2))
    counts = np.sum(~np.isnan(win), axis=(-1, -2))
    idx = counts >= min_count
    coarse = np.full_like(sums, np.nan)
    coarse[idx] = sums[idx] / counts[idx]
    #------
    
    # ── SPEEDUP 1: integral image replaces view_as_windows ─────────────────Claude
    # x_valid = np.where(valid, image.astype(np.float32), 0.0)

    # pad = box // 2
    # # reflect-pad the value array (matches original pad_mode behavior)
    # # zero-pad the valid mask (outside is truly invalid)
    # # xp = np.pad(x_valid,           pad, mode=pad_mode)
    # # vp = np.pad(valid.astype(np.float32), pad, mode='constant', constant_values=0.0)
    # xp = np.pad(x_valid, pad, mode='constant', constant_values=0)
    # vp = np.pad(valid.astype(np.float32), pad, mode='constant', constant_values=0)

    # Hp, Wp = xp.shape
    # # ix = np.zeros((Hp+1, Wp+1))
    # # iv = np.zeros((Hp+1, Wp+1))
    # ix = np.zeros((Hp+1, Wp+1), dtype=np.float64)
    # iv = np.zeros((Hp+1, Wp+1), dtype=np.float64)
    # ix[1:, 1:] = np.cumsum(np.cumsum(xp, axis=0), axis=1)
    # iv[1:, 1:] = np.cumsum(np.cumsum(vp, axis=0), axis=1)

    # Hc = (Hp - box) // stride + 1
    # Wc = (Wp - box) // stride + 1

    # rs = np.arange(Hc) * stride;  cs = np.arange(Wc) * stride
    # r1, r2 = rs, rs + box
    # c1, c2 = cs, cs + box


    # sums   = (ix[r2[:,None], c2[None,:]] - ix[r1[:,None], c2[None,:]]
    #         - ix[r2[:,None], c1[None,:]] + ix[r1[:,None], c1[None,:]])
    # counts = (iv[r2[:,None], c2[None,:]] - iv[r1[:,None], c2[None,:]]
    #         - iv[r2[:,None], c1[None,:]] + iv[r1[:,None], c1[None,:]])
    # counts = counts.astype(int)

    # coarse = np.full((Hc, Wc), np.nan)
    # idx = counts >= min_count
    # coarse[idx] = sums[idx] / counts[idx]
    # ───────────────────────────────────────────────────────────────────────Chatgpt
    # x_valid = np.where(valid, image.astype(np.float32), 0.0)

    # pad = box // 2
    
    # xp = np.pad(x_valid, pad, mode=pad_mode)
    # vp = np.pad(valid.astype(np.float32), pad, mode=pad_mode)
    
    # Hp, Wp = xp.shape
    
    # ix = np.zeros((Hp+1, Wp+1), dtype=np.float32)
    # iv = np.zeros((Hp+1, Wp+1), dtype=np.float32)
    
    # ix[1:, 1:] = np.cumsum(np.cumsum(xp, axis=0), axis=1)
    # iv[1:, 1:] = np.cumsum(np.cumsum(vp, axis=0), axis=1)
    
    # Hc = (Hp - box) // stride + 1
    # Wc = (Wp - box) // stride + 1
    
    # rs = np.arange(Hc) * stride
    # cs = np.arange(Wc) * stride
    
    # r1, r2 = rs, rs + box
    # c1, c2 = cs, cs + box
    
    # sums = (
    #     ix[r2[:, None], c2[None, :]]
    #     - ix[r1[:, None], c2[None, :]]
    #     - ix[r2[:, None], c1[None, :]]
    #     + ix[r1[:, None], c1[None, :]]
    # )
    
    # counts = (
    #     iv[r2[:, None], c2[None, :]]
    #     - iv[r1[:, None], c2[None, :]]
    #     - iv[r2[:, None], c1[None, :]]
    #     + iv[r1[:, None], c1[None, :]]
    # )
    
    # coarse = np.full((Hc, Wc), np.nan, dtype=np.float32)
    # mask = counts >= min_count
    # coarse[mask] = sums[mask] / counts[mask]
    #--------------------------------------------------

    if coarse_fill == "nearest":
        coarse = _fill_nan_nearest(coarse)
    elif coarse_fill == "linear":
        coarse = _fill_nan_linear_with_nearest_fallback(coarse)

    # ── ONLY CHANGE: replace ndimage.zoom with proper grid interpolation ──
    if upsample == "nearest":
        # Nearest: just map each output pixel to nearest coarse center
        row_idx = np.clip((np.arange(H) / stride).astype(int), 0, Hc-1)
        col_idx = np.clip((np.arange(W) / stride).astype(int), 0, Wc-1)
        full_res = coarse[np.ix_(row_idx, col_idx)]
    else:
        # Bilinear: use actual box center coordinates
        # coarse[i,j] represents the average centered at pixel (i*stride, j*stride)
        y_c = np.arange(Hc) * stride   # actual row centers in full-res space
        x_c = np.arange(Wc) * stride   # actual col centers in full-res space

        # Clamp to image boundary
        y_c = np.clip(y_c, 0, H - 1)
        x_c = np.clip(x_c, 0, W - 1)

        interp = RegularGridInterpolator(
            (y_c, x_c), coarse,
            method='linear',
            bounds_error=False,
            fill_value=None  # extrapolate at edges instead of NaN
        )
        yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing='ij')
        full_res = interp((yy, xx))

    return full_res, coarse, counts
# def box_average_with_overlap_interpolated(
#     image: np.ndarray,
#     mask: np.ndarray,
#     box: int = 32,
#     stride: int = 8,
#     min_count: int = 1,
#     upsample: str = "bilinear",
#     pad_mode: str = "reflect",
#     coarse_fill: str | None = None,
# ):
#     if image.ndim != 2 or mask.ndim != 2 or image.shape != mask.shape:
#         raise ValueError("image and mask must be 2D arrays of the same shape")
#     if stride <= 0 or box <= 0:
#         raise ValueError("box and stride must be positive")

#     H, W = image.shape
#     valid = mask & np.isfinite(image)

#     # ── SPEEDUP 1: integral image replaces view_as_windows ─────────────────
#     x_valid = np.where(valid, image.astype(np.float32), 0.0)

#     pad = box // 2
#     # reflect-pad the value array (matches original pad_mode behavior)
#     # zero-pad the valid mask (outside is truly invalid)
#     xp = np.pad(x_valid,           pad, mode=pad_mode)
#     vp = np.pad(valid.astype(np.float32), pad, mode='constant', constant_values=0.0)

#     Hp, Wp = xp.shape
#     ix = np.zeros((Hp+1, Wp+1))
#     iv = np.zeros((Hp+1, Wp+1))
#     ix[1:, 1:] = np.cumsum(np.cumsum(xp, axis=0), axis=1)
#     iv[1:, 1:] = np.cumsum(np.cumsum(vp, axis=0), axis=1)

#     Hc = (Hp - box) // stride + 1
#     Wc = (Wp - box) // stride + 1

#     rs = np.arange(Hc) * stride;  cs = np.arange(Wc) * stride
#     r1, r2 = rs, rs + box
#     c1, c2 = cs, cs + box

#     sums   = (ix[r2[:,None], c2[None,:]] - ix[r1[:,None], c2[None,:]]
#             - ix[r2[:,None], c1[None,:]] + ix[r1[:,None], c1[None,:]])
#     counts = (iv[r2[:,None], c2[None,:]] - iv[r1[:,None], c2[None,:]]
#             - iv[r2[:,None], c1[None,:]] + iv[r1[:,None], c1[None,:]])
#     counts = counts.astype(int)

#     coarse = np.full((Hc, Wc), np.nan)
#     idx = counts >= min_count
#     coarse[idx] = sums[idx] / counts[idx]
#     # ───────────────────────────────────────────────────────────────────────

#     if coarse_fill == "nearest":
#         coarse = _fill_nan_nearest(coarse)
#     elif coarse_fill == "linear":
#         coarse = _fill_nan_linear_with_nearest_fallback(coarse)

#     # ── SPEEDUP 2: RegularGridInterpolator replaces ndimage.zoom ───────────
#     if upsample == "nearest":
#         row_idx = np.clip((np.arange(H) / stride).astype(int), 0, Hc-1)
#         col_idx = np.clip((np.arange(W) / stride).astype(int), 0, Wc-1)
#         full_res = coarse[np.ix_(row_idx, col_idx)]
#     else:
#         # Actual box center coordinates in full-res pixel space
#         # y_c = np.clip(np.arange(Hc) * stride, 0, H-1)
#         # x_c = np.clip(np.arange(Wc) * stride, 0, W-1)

#         # interp = RegularGridInterpolator(
#         #     (y_c, x_c), coarse,
#         #     method='linear',
#         #     bounds_error=False,
#         #     fill_value=None  # extrapolate at edges
#         # )
#         # yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing='ij')
#         # full_res = interp((yy, xx))
        
#         yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing='ij')

#         # scale coordinates into coarse grid space
#         yyc = yy / stride
#         xxc = xx / stride
        
#         full_res = map_coordinates(
#             coarse,
#             [yyc, xxc],
#             order=1,  # bilinear
#             mode='nearest'
#         )
#     # ───────────────────────────────────────────────────────────────────────

#     return full_res, coarse, counts


def wrap_boxaverage(img, msk_clean, boxsize, q, n_workers=4):
    arr = np.asarray(img)
    squeeze_single = False

    if arr.ndim == 2:
        arr = arr[None, ...]
        squeeze_single = True
    nb, H, W = arr.shape

    stride = boxsize // 2
    minc   = boxsize

    # ── SPEEDUP 3: parallel band loop ──────────────────────────────────────
    def process_band(ib):
        full, coarse, cnt = box_average_with_overlap_interpolated(
            image=arr[ib], mask=msk_clean,
            box=boxsize, stride=stride, min_count=minc,
            coarse_fill="linear", upsample="bilinear"
        )
        percentile = np.nanpercentile(coarse, q)
        return full, percentile

    with ThreadPoolExecutor(max_workers=min(n_workers, nb)) as ex:
        results = list(ex.map(process_band, range(nb)))
    # ───────────────────────────────────────────────────────────────────────

    rhot_ave = [r[0] for r in results]
    rhot_p   = [r[1] for r in results]

    if squeeze_single:
        return rhot_ave[0], rhot_p[0]
    return rhot_ave, rhot_p

def wrap_boxaverage_tiled(img, msk_clean, boxsize, q,
                           tile_size=4096, n_workers=4):
    """
    Process large image in overlapping tiles to avoid memory crash.
    tile_size : size of each tile in pixels
    overlap   : must be >= boxsize to avoid boundary artifacts
    """
    arr = np.asarray(img, dtype=np.float32)
    squeeze_single = False
    if arr.ndim == 2:
        arr = arr[None, ...]
        squeeze_single = True
    nb, H, W = arr.shape

    stride   = boxsize // 2
    minc     = boxsize
    overlap  = boxsize * 2  # safe margin — at least boxsize

    # Output canvas
    full_out = np.full((nb, H, W), np.nan)
    rhot_p   = [[] for _ in range(nb)]  # collect percentiles per tile

    # Generate tile ranges
    def tile_ranges(total, size, ovlp):
        starts = []
        s = 0
        while s < total:
            starts.append(s)
            s += size
        ranges = []
        for s in starts:
            e = min(s + size, total)
            # read range (with overlap padding)
            r0 = max(0, s - ovlp)
            r1 = min(total, e + ovlp)
            # write range (crop back to original tile)
            w0 = s
            w1 = e
            # where to crop from the processed tile result
            c0 = s - r0  # = ovlp except at left/top edge
            c1 = c0 + (w1 - w0)
            ranges.append((r0, r1, w0, w1, c0, c1))
        return ranges

    row_tiles = tile_ranges(H, tile_size, overlap)
    col_tiles = tile_ranges(W, tile_size, overlap)

    n_tiles = len(row_tiles) * len(col_tiles)
    print(f"Image: {H}x{W}, tiles: {len(row_tiles)}x{len(col_tiles)} = {n_tiles} total")

    for ti, (r0, r1, wr0, wr1, cr0, cr1) in enumerate(row_tiles):
        for tj, (c0, c1, wc0, wc1, cc0, cc1) in enumerate(col_tiles):
            print(f"  Tile ({ti},{tj}) / ({len(row_tiles)-1},{len(col_tiles)-1})"
                  f" read:[{r0}:{r1}, {c0}:{c1}]"
                  f" write:[{wr0}:{wr1}, {wc0}:{wc1}]")

            tile_img = arr[:, r0:r1, c0:c1]       # (nb, th, tw)
            tile_msk = msk_clean[r0:r1, c0:c1]    # (th, tw)

            def process_band(ib):
                full, coarse, _ = box_average_with_overlap_interpolated(
                    image=tile_img[ib], mask=tile_msk,
                    box=boxsize, stride=stride, min_count=minc,
                    coarse_fill="linear", upsample="bilinear"
                )
                # Crop overlap margins → only keep the valid write region
                cropped = full[cr0:cr1, cc0:cc1]
                pct = np.float32(np.nanpercentile(coarse, q))
                return cropped, pct

            with ThreadPoolExecutor(max_workers=min(n_workers, nb)) as ex:
                results = list(ex.map(process_band, range(nb)))

            for ib, (cropped, pct) in enumerate(results):
                full_out[ib, wr0:wr1, wc0:wc1] = cropped
                rhot_p[ib].append(pct)

    # Aggregate percentile across tiles (median of tile percentiles)
    rhot_p = [np.float32(np.median(p)) for p in rhot_p]

    if squeeze_single:
        return full_out[0], rhot_p[0]
    return list(full_out), rhot_p

def fill_nearest(arr):
    mask = np.isnan(arr)
    # indices of nearest non-nan elements
    idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return arr[tuple(idx)]