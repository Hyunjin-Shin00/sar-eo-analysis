#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 24 17:41:55 2025

@author: yp
"""

import numpy as np
from scipy.fft import fft2, fftshift
from scipy.ndimage import zoom
from skimage.filters import sobel, gaussian
from skimage.transform import warp_polar, SimilarityTransform, warp, rotate
from skimage.registration import phase_cross_correlation


# ============================================================
# Preprocessing & Similarity Registration
# ============================================================

def _norm01(x):
    x = np.asarray(x, dtype=np.float32)
    x = x - np.nanmin(x)
    r = np.nanmax(x) - np.nanmin(x)
    if r < 1e-12:
        return np.zeros_like(x, dtype=np.float32)
    return x / r


def _preprocess_for_pcorr(im, use_gradient=True, valid_mask=None, mask_soft_sigma=8.0):
    """
    Preprocess for phase correlation / Fourier-Mellin.
    - optional Sobel gradient
    - optional valid_mask (boolean)
    - if valid_mask provided: apply *soft* mask to reduce FFT edge artifacts
    """
    im = np.asarray(im, dtype=np.float32)

    if use_gradient:
        im = sobel(im)

    if valid_mask is not None:
        vm = np.asarray(valid_mask, dtype=bool)
        # soft mask to avoid sharp edges in FFT
        w = gaussian(vm.astype(np.float32), sigma=mask_soft_sigma, preserve_range=True)
        w /= (w.max() + 1e-6)
        im = np.where(vm, im, 0.0)  # hard zero outside
        im = im * np.clip(w, 0.0, 1.0)

    return _norm01(im)


def estimate_rotation_scale_fm(ref, mov, upsample_factor=10, use_gradient=True,
                               valid_ref=None, valid_mov=None, mask_soft_sigma=8.0):
    ref_p = _preprocess_for_pcorr(ref, use_gradient=use_gradient,
                                  valid_mask=valid_ref, mask_soft_sigma=mask_soft_sigma)
    mov_p = _preprocess_for_pcorr(mov, use_gradient=use_gradient,
                                  valid_mask=valid_mov, mask_soft_sigma=mask_soft_sigma)

    F_ref = np.abs(fftshift(fft2(ref_p)))
    F_mov = np.abs(fftshift(fft2(mov_p)))

    F_ref = np.log1p(F_ref)
    F_mov = np.log1p(F_mov)

    radius = min(ref.shape) // 2
    lp_ref = warp_polar(F_ref, radius=radius, scaling="log")
    lp_mov = warp_polar(F_mov, radius=radius, scaling="log")

    (shift_r, shift_theta), fm_error, _ = phase_cross_correlation(
        lp_ref, lp_mov, upsample_factor=upsample_factor
    )

    num_angles = lp_ref.shape[0]
    angle_deg = (shift_theta / num_angles) * 360.0
    scale = np.exp(shift_r / lp_ref.shape[1])

    return float(angle_deg), float(scale), float(fm_error)



def apply_rotation_scale(im, angle_deg, scale, output_shape):
    """
    Apply isotropic scale then rotation (around center), returning output_shape.
    """
    im = np.asarray(im, dtype=np.float32)

    # 1) scale
    if abs(scale - 1.0) > 1e-6:
        im_scaled = zoom(im, (scale, scale), order=1)
    else:
        im_scaled = im

    # 2) center crop/pad to output_shape
    Ht, Wt = output_shape
    H, W = im_scaled.shape

    if H > Ht:
        sy = (H - Ht) // 2
        im_scaled = im_scaled[sy:sy+Ht, :]
    if W > Wt:
        sx = (W - Wt) // 2
        im_scaled = im_scaled[:, sx:sx+Wt]

    H, W = im_scaled.shape
    if H < Ht or W < Wt:
        pad_y = max(0, Ht - H)
        pad_x = max(0, Wt - W)
        p0 = pad_y // 2
        p1 = pad_y - p0
        q0 = pad_x // 2
        q1 = pad_x - q0
        im_scaled = np.pad(im_scaled, ((p0, p1), (q0, q1)),
                           mode="constant", constant_values=0)

    # 3) rotate
    if abs(angle_deg) > 1e-6:
        im_rs = rotate(im_scaled, angle=angle_deg, resize=False,
                       preserve_range=True, order=1)
    else:
        im_rs = im_scaled

    return im_rs


def apply_rotation_scale_mask(mask, angle_deg, scale, output_shape, thresh=0.5):
    """
    Apply the same isotropic scale + rotation to a boolean mask,
    returning a boolean mask with shape=output_shape.

    Uses:
      - zoom() for scaling
      - rotate() for rotation
      - crop/pad like apply_rotation_scale()
    """
    mask = np.asarray(mask).astype(np.float32)

    # 1) scale
    if abs(scale - 1.0) > 1e-6:
        m_scaled = zoom(mask, (scale, scale), order=0)  # nearest for masks
    else:
        m_scaled = mask

    # 2) center crop/pad to output_shape
    Ht, Wt = output_shape
    H, W = m_scaled.shape

    if H > Ht:
        sy = (H - Ht) // 2
        m_scaled = m_scaled[sy:sy+Ht, :]
    if W > Wt:
        sx = (W - Wt) // 2
        m_scaled = m_scaled[:, sx:sx+Wt]

    H, W = m_scaled.shape
    if H < Ht or W < Wt:
        pad_y = max(0, Ht - H)
        pad_x = max(0, Wt - W)
        p0 = pad_y // 2
        p1 = pad_y - p0
        q0 = pad_x // 2
        q1 = pad_x - q0
        m_scaled = np.pad(m_scaled, ((p0, p1), (q0, q1)),
                          mode="constant", constant_values=0)

    # 3) rotate
    if abs(angle_deg) > 1e-6:
        m_rs = rotate(m_scaled, angle=angle_deg, resize=False,
                      preserve_range=True, order=0)
    else:
        m_rs = m_scaled

    return (m_rs > thresh)

def estimate_translation_pcorr(ref, mov, upsample_factor=10, use_gradient=True,
                               valid_ref=None, valid_mov=None, mask_soft_sigma=8.0):
    ref_p = _preprocess_for_pcorr(ref, use_gradient=use_gradient,
                                  valid_mask=valid_ref, mask_soft_sigma=mask_soft_sigma)
    mov_p = _preprocess_for_pcorr(mov, use_gradient=use_gradient,
                                  valid_mask=valid_mov, mask_soft_sigma=mask_soft_sigma)

    (dy, dx), trans_error, _ = phase_cross_correlation(
        ref_p, mov_p, upsample_factor=upsample_factor
    )
    return float(dy), float(dx), float(trans_error)



def similarity_register(ref, mov, upsample_factor=10, use_gradient=True,
                        valid_ref=None, valid_mov=None, mask_soft_sigma=8.0, verbose=True):
    """
    Similarity register MOV -> REF:
      (angle, scale) via Fourier-Mellin,
      then (dy,dx) via phase correlation.

    Supports valid_ref/valid_mov masks and correctly warps valid_mov through
    the same rotation+scale before translation estimation.
    """

    if valid_ref is None:
        valid_ref = np.ones(ref.shape, dtype=bool)
    if valid_mov is None:
        valid_mov = np.ones(mov.shape, dtype=bool)

    # 1) rotation+scale from FM (use original masks)
    angle_deg, scale, fm_error = estimate_rotation_scale_fm(
        ref, mov,
        upsample_factor=upsample_factor,
        use_gradient=use_gradient,
        valid_ref=valid_ref,
        valid_mov=valid_mov,
        mask_soft_sigma=mask_soft_sigma
    )

    # 2) apply rotation+scale to MOV
    mov_rs = apply_rotation_scale(mov, angle_deg, scale, output_shape=ref.shape)

    # 3) apply SAME rotation+scale to MOV mask (IMPORTANT for internal invalids)
    valid_mov_rs = apply_rotation_scale_mask(
        valid_mov, angle_deg, scale, output_shape=ref.shape, thresh=0.5
    )
    if verbose and np.count_nonzero(valid_mov_rs) < 0.05 * valid_mov_rs.size:
        print("  [WARN] valid_mov after rot/scale is very small; translation may be unstable.")


    # 4) translation on the rotated/scaled data and masks
    dy, dx, trans_error = estimate_translation_pcorr(
        ref, mov_rs,
        upsample_factor=upsample_factor,
        use_gradient=use_gradient,
        valid_ref=valid_ref,
        valid_mov=valid_mov_rs,          # <-- warped mask
        mask_soft_sigma=mask_soft_sigma
    )

    return angle_deg, scale, (dy, dx), fm_error, trans_error




# ============================================================
# Multi-tile utilities (vertical strips)
# ============================================================

def make_vertical_tiles(H, n_tiles=4, overlap=256):
    """
    Split [0..H) into n_tiles with overlap.
    Returns:
      tiles: list of (y0,y1) including overlap
      cores: list of (core_y0, core_y1) non-overlap core
    """
    bounds = np.linspace(0, H, n_tiles + 1).astype(int)
    tiles, cores = [], []

    for i in range(n_tiles):
        core_y0 = bounds[i]
        core_y1 = bounds[i + 1]
        y0 = max(0, core_y0 - overlap)
        y1 = min(H, core_y1 + overlap)
        tiles.append((y0, y1))
        cores.append((core_y0, core_y1))

    return tiles, cores


def make_vertical_tile_weights(H, tiles, cores):
    """
    Create weights w[i](y) such that sum_i w[i](y)=1 for all y.
    Uses smooth cosine ramps in overlaps.
    Returns weights shape: (n_tiles, H, 1)
    """
    n_tiles = len(tiles)
    weights = np.zeros((n_tiles, H, 1), dtype=np.float32)

    # each tile dominates its core
    for i, (cy0, cy1) in enumerate(cores):
        weights[i, cy0:cy1, 0] = 1.0

    # smooth transitions in shared overlap regions
    for i in range(n_tiles - 1):
        y_blend0 = max(tiles[i][0], tiles[i + 1][0])
        y_blend1 = min(tiles[i][1], tiles[i + 1][1])
        if y_blend1 <= y_blend0:
            continue

        L = y_blend1 - y_blend0
        t = np.linspace(0, 1, L, dtype=np.float32)[:, None]
        ramp_down = 0.5 * (1 + np.cos(np.pi * t))  # 1 -> 0
        ramp_up   = 1.0 - ramp_down                # 0 -> 1

        weights[i,     y_blend0:y_blend1, 0] *= ramp_down[:, 0]
        weights[i + 1, y_blend0:y_blend1, 0] *= ramp_up[:, 0]

    # normalize: ensure sum=1 everywhere
    wsum = weights.sum(axis=0, keepdims=True)
    weights /= np.maximum(wsum, 1e-6)

    return weights

def valid_mask_from_range(im, vmin=None, vmax=None):
    im = np.asarray(im)
    m = np.isfinite(im)
    if vmin is not None:
        m &= (im >= vmin)
    if vmax is not None:
        m &= (im <= vmax)
    return m

def tile_to_global_similarity(tform_local, x0, y0):
    """
    Convert tile-local similarity transform to global coords:
      T_global = shift_back ∘ T_local ∘ shift_to_tile
    """
    shift_to_tile = SimilarityTransform(translation=(-x0, -y0))
    shift_back    = SimilarityTransform(translation=( x0,  y0))
    M_global = shift_back.params @ tform_local.params @ shift_to_tile.params
    return SimilarityTransform(matrix=M_global)


def fix_bad_tiles_by_neighbor(diags, tforms_global):
    """
    Replace bad tile transforms with nearest good neighbor transform.
    """
    ok = np.array([d["ok"] for d in diags], dtype=bool)
    if ok.all():
        return tforms_global, diags

    good = np.where(ok)[0]
    if len(good) == 0:
        return tforms_global, diags  # nothing good

    new_tforms = list(tforms_global)
    for i in range(len(diags)):
        if ok[i]:
            continue
        nearest = good[np.argmin(np.abs(good - i))]
        new_tforms[i] = tforms_global[nearest]
        diags[i]["replaced_by"] = int(nearest)
        diags[i]["ok"] = True
    return new_tforms, diags


# ============================================================
# Multi-tile Similarity Registration (one band -> one ref)
# ============================================================

def similarity_register_multi_tiles(
    ref,
    mov,
    n_tiles=4,
    overlap=256,
    upsample_factor=20,
    use_gradient=True,
    bg=0,
    verbose=True,
    fm_err_max=0.6,
    tr_err_max=0.6,
    auto_fix_bad_tiles=True,
    # NEW:
    valid_ref=None,
    valid_mov=None,
    mask_soft_sigma=8.0,
):
    H, W = ref.shape
    tiles, cores = make_vertical_tiles(H, n_tiles=n_tiles, overlap=overlap)
    weights = make_vertical_tile_weights(H, tiles, cores)

    if valid_ref is None:
        valid_ref = np.ones(ref.shape, dtype=bool)
    if valid_mov is None:
        valid_mov = np.ones(mov.shape, dtype=bool)

    tforms_global = []
    diags = []

    for i, (y0, y1) in enumerate(tiles):
        ref_tile = ref[y0:y1, :]
        mov_tile = mov[y0:y1, :]
        vref_tile = valid_ref[y0:y1, :]
        vmov_tile = valid_mov[y0:y1, :]

        if verbose:
            print(f"\n[TILE {i}] rows {y0}:{y1} (core {cores[i][0]}:{cores[i][1]})")

        angle, scale, (dy, dx), fm_err, tr_err = similarity_register(
            ref_tile, mov_tile,
            upsample_factor=upsample_factor,
            use_gradient=use_gradient,
            valid_ref=vref_tile,
            valid_mov=vmov_tile,
            mask_soft_sigma=mask_soft_sigma
        )

        ok = (fm_err < fm_err_max) and (tr_err < tr_err_max)

        if verbose:
            print(f"  angle={angle:.4f} deg, scale={scale:.6f}, shift=({dy:.2f},{dx:.2f}), "
                  f"errors fm={fm_err:.3f}, tr={tr_err:.3f}, ok={ok}")

        tform_local = SimilarityTransform(scale=scale,
                                          rotation=np.deg2rad(angle),
                                          translation=(dx, dy))
        tform_g = tile_to_global_similarity(tform_local, x0=0, y0=y0)

        tforms_global.append(tform_g)
        diags.append({
            "tile_index": i,
            "tile_range": (y0, y1),
            "core_range": cores[i],
            "angle_deg": angle,
            "scale": scale,
            "dy": dy,
            "dx": dx,
            "fm_error": fm_err,
            "tr_error": tr_err,
            "ok": ok,
        })

    if auto_fix_bad_tiles:
        tforms_global, diags = fix_bad_tiles_by_neighbor(diags, tforms_global)

    accum = np.zeros((H, W), dtype=np.float32)
    for i in range(n_tiles):
        warped_i = warp(
            mov,
            inverse_map=tforms_global[i].inverse,
            output_shape=ref.shape,
            order=1,
            cval=bg,
            preserve_range=True
        ).astype(np.float32)

        accum += warped_i * weights[i]

    return accum, tforms_global, diags, weights


def similarity_params_from_matrix(T):
    """
    Extract angle (deg), isotropic scale, and (dy,dx) from a SimilarityTransform.
    """
    M = T.params
    a, b, tx = M[0, 0], M[0, 1], M[0, 2]
    c, d, ty = M[1, 0], M[1, 1], M[1, 2]

    scale = np.sqrt(a*a + c*c)               # isotropic scale
    angle = np.degrees(np.arctan2(c, a))     # rotation angle in degrees

    # translation: tx is x-shift (dx), ty is y-shift (dy)
    dy, dx = ty, tx

    return angle, scale, dy, dx


# ============================================================
# Main: Two-refs multi-tile pipeline (VIS + optional NIR)
# ============================================================

def coreg_two_refs_similarity_fm_multitiles(
    images,
    vis_idxs,
    ref_vis,
    nir_idxs=None,
    ref_nir=None,
    upsample_f=20,
    bg=0,
    use_gradient=True,
    n_tiles=4,
    overlap=256,
    verbose=True,
    fm_err_max=0.6,
    tr_err_max=0.6,
    auto_fix_bad_tiles=True,
    valid_ranges=None,          # NEW: [[min0,max0], ...]
    mask_soft_sigma=8.0,        # NEW: soft mask blur sigma for FM
):
    """
    Multi-tile similarity coregistration:

      1) VIS bands -> ref_vis
      2) (optional) ref_nir -> ref_vis
      3) (optional) NIR bands -> ref_nir (local), composed -> ref_vis

    Returns:
      stack: (n_bands, H, W) in ref_vis coordinates (float32)
      tforms_tiles: list of per-band list-of-transforms [band][tile]
      diags_tiles: list of per-band list-of-diags [band][tile]
      out_shape: (H,W)
    """
    n_bands = len(images)
    ref = images[ref_vis]
    H, W = ref.shape
    out_shape = (H, W)
    
    def get_valid_mask(band_idx):
        if valid_ranges is None:
            return np.isfinite(images[band_idx])
        if band_idx >= len(valid_ranges):
            raise ValueError(f"valid_ranges length ({len(valid_ranges)}) < band index ({band_idx})")
        vmin, vmax = valid_ranges[band_idx]
        return valid_mask_from_range(images[band_idx], vmin, vmax)


    valid_ref = get_valid_mask(ref_vis)
    
    stack = np.zeros((n_bands, H, W), dtype=np.float32)

    # per band: list of transforms per tile
    tforms_tiles = [None] * n_bands
    diags_tiles = [None] * n_bands

    # ref_vis identity
    stack[ref_vis] = ref.astype(np.float32)
    tforms_tiles[ref_vis] = [SimilarityTransform() for _ in range(n_tiles)]
    diags_tiles[ref_vis] = [{"identity": True} for _ in range(n_tiles)]

    # ---------------------------
    # STEP 1: VIS -> ref_vis
    # ---------------------------
    if verbose:
        print(f"\n[STEP 1] VIS bands -> ref_vis {ref_vis} (multi-tile)")

    for ib in vis_idxs:
        if ib == ref_vis:
            continue

        if verbose:
            print(f"\n[VIS] Band {ib} -> ref_vis {ref_vis}")
            
        valid_mov = get_valid_mask(ib)

        warped, tforms_g, diags, weights = similarity_register_multi_tiles(
            ref=ref,
            mov=images[ib],
            n_tiles=n_tiles,
            overlap=overlap,
            upsample_factor=upsample_f,
            use_gradient=use_gradient,
            bg=bg,
            verbose=verbose,
            fm_err_max=fm_err_max,
            tr_err_max=tr_err_max,
            auto_fix_bad_tiles=auto_fix_bad_tiles,
            valid_ref=valid_ref,
            valid_mov=valid_mov,
            mask_soft_sigma=mask_soft_sigma,
        )

        stack[ib] = warped.astype(np.float32)
        tforms_tiles[ib] = tforms_g
        diags_tiles[ib] = diags

    # ---------------------------
    # If no NIR requested
    # ---------------------------
    if nir_idxs is None or ref_nir is None or len(nir_idxs) == 0:
        if verbose:
            print("\n[INFO] NIR registration skipped (nir_idxs or ref_nir not provided).")
        return stack, tforms_tiles, diags_tiles, out_shape

    # ---------------------------
    # STEP 2: ref_nir -> ref_vis
    # ---------------------------
    if verbose:
        print(f"\n[STEP 2] ref_nir {ref_nir} -> ref_vis {ref_vis} (multi-tile)")

    valid_mov = get_valid_mask(ref_nir)
    warped_nref, tforms_nref_to_vis, diags_nref, weights = similarity_register_multi_tiles(
        ref=ref,
        mov=images[ref_nir],
        n_tiles=n_tiles,
        overlap=overlap,
        upsample_factor=upsample_f,
        use_gradient=use_gradient,
        bg=bg,
        verbose=verbose,
        fm_err_max=fm_err_max,
        tr_err_max=tr_err_max,
        auto_fix_bad_tiles=auto_fix_bad_tiles,
        valid_ref=valid_ref,
        valid_mov=valid_mov,
        mask_soft_sigma=mask_soft_sigma,
    )

    stack[ref_nir] = warped_nref.astype(np.float32)
    tforms_tiles[ref_nir] = tforms_nref_to_vis
    diags_tiles[ref_nir] = diags_nref

    # ---------------------------
    # STEP 3: NIR -> ref_nir, compose -> ref_vis per tile
    # ---------------------------
    if verbose:
        print(f"\n[STEP 3] NIR bands -> ref_nir {ref_nir}, composed -> ref_vis {ref_vis} (multi-tile)")

    valid_ref_nir = get_valid_mask(ref_nir)
    ref_nir_img = images[ref_nir]

    for ib in nir_idxs:
        if ib == ref_nir:
            continue

        if verbose:
            print(f"\n[NIR] Band {ib} -> ref_nir {ref_nir} (local), composed -> ref_vis {ref_vis}")

        valid_mov = get_valid_mask(ib)
        # local band -> ref_nir
        _, tforms_band_to_nir, diags_local, weights = similarity_register_multi_tiles(
            ref=ref_nir_img,
            mov=images[ib],
            n_tiles=n_tiles,
            overlap=overlap,
            upsample_factor=upsample_f,
            use_gradient=use_gradient,
            bg=bg,
            verbose=verbose,
            fm_err_max=fm_err_max,
            tr_err_max=tr_err_max,
            auto_fix_bad_tiles=auto_fix_bad_tiles,
            valid_ref=valid_ref_nir,
            valid_mov=valid_mov,
            mask_soft_sigma=mask_soft_sigma,
        )

        # compose per tile: band->vis = (nir->vis) @ (band->nir)
        tforms_band_to_vis = []
        for t in range(n_tiles):
            M_global = tforms_nref_to_vis[t].params @ tforms_band_to_nir[t].params
            tforms_band_to_vis.append(SimilarityTransform(matrix=M_global))

        if verbose:
            print("\n[GLOBAL COMPOSED SIMILARITY: BAND -> REF_VIS]")
            for t, Tg in enumerate(tforms_band_to_vis):
                g_angle, g_scale, g_dy, g_dx = similarity_params_from_matrix(Tg)
                print(
                    f"  [GLOBAL TILE {t}] "
                    f"angle={g_angle:.3f} deg, "
                    f"scale={g_scale:.6f}, "
                    f"shift=({g_dy:.2f},{g_dx:.2f})"
                )

        # warp+blend using composed transforms and the same weights
        accum = np.zeros((H, W), dtype=np.float32)
        for t in range(n_tiles):
            warped_t = warp(
                images[ib],
                inverse_map=tforms_band_to_vis[t].inverse,
                output_shape=ref.shape,
                order=1,
                cval=bg,
                preserve_range=True
            ).astype(np.float32)
            accum += warped_t * weights[t]
        stack[ib] = accum

        tforms_tiles[ib] = tforms_band_to_vis
        diags_tiles[ib] = {
            "local_to_ref_nir": diags_local,
            "composed": True
        }

    return stack, tforms_tiles, diags_tiles, out_shape
