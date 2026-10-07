#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 24 16:23:33 2025

@author: yp
"""

import numpy as np
from scipy.fft import fft2, fftshift
from scipy.ndimage import zoom
from skimage.filters import sobel
from skimage.transform import warp_polar, SimilarityTransform, warp, rotate
from skimage.registration import phase_cross_correlation


# ============================================================
# Preprocessing & Registration helpers
# ============================================================

def _norm01(x):
    x = np.asarray(x, dtype=np.float32)
    x = x - np.nanmin(x)
    r = np.nanmax(x) - np.nanmin(x)
    if r < 1e-12:
        return np.zeros_like(x, dtype=np.float32)
    return x / r


def _preprocess_for_pcorr(im, use_gradient=True):
    im = np.asarray(im, dtype=np.float32)
    if use_gradient:
        im = sobel(im)
    return _norm01(im)


def estimate_rotation_scale_fm(ref, mov, upsample_factor=10, use_gradient=True):
    """
    Estimate (rotation, scale) via Fourier magnitude + log-polar phase correlation.
    Returns angle_deg (apply to mov), scale (apply to mov), fm_error.
    """
    ref_p = _preprocess_for_pcorr(ref, use_gradient=use_gradient)
    mov_p = _preprocess_for_pcorr(mov, use_gradient=use_gradient)

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

    # scale from shift_r in log radius space
    scale = np.exp(shift_r / lp_ref.shape[1])

    return float(angle_deg), float(scale), float(fm_error)


def apply_rotation_scale(im, angle_deg, scale, output_shape):
    """
    Apply isotropic scale then rotation (around center), returning output_shape.
    """
    im = np.asarray(im, dtype=np.float32)

    # scale
    if abs(scale - 1.0) > 1e-6:
        im_scaled = zoom(im, (scale, scale), order=1)
    else:
        im_scaled = im

    # center crop/pad to output_shape
    Ht, Wt = output_shape
    H, W = im_scaled.shape

    # crop
    if H > Ht:
        sy = (H - Ht) // 2
        im_scaled = im_scaled[sy:sy+Ht, :]
    if W > Wt:
        sx = (W - Wt) // 2
        im_scaled = im_scaled[:, sx:sx+Wt]

    # pad
    H, W = im_scaled.shape
    if H < Ht or W < Wt:
        pad_y = max(0, Ht - H)
        pad_x = max(0, Wt - W)
        p0 = pad_y // 2
        p1 = pad_y - p0
        q0 = pad_x // 2
        q1 = pad_x - q0
        im_scaled = np.pad(im_scaled, ((p0, p1), (q0, q1)),
                           mode='constant', constant_values=0)

    # rotate
    if abs(angle_deg) > 1e-6:
        im_rs = rotate(im_scaled, angle=angle_deg, resize=False,
                       preserve_range=True, order=1)
    else:
        im_rs = im_scaled

    return im_rs


def estimate_translation_pcorr(ref, mov, upsample_factor=10, use_gradient=True):
    """
    Estimate translation dy, dx via phase correlation.
    """
    ref_p = _preprocess_for_pcorr(ref, use_gradient=use_gradient)
    mov_p = _preprocess_for_pcorr(mov, use_gradient=use_gradient)

    (dy, dx), trans_error, _ = phase_cross_correlation(
        ref_p, mov_p, upsample_factor=upsample_factor
    )
    return float(dy), float(dx), float(trans_error)


def similarity_register(ref, mov, upsample_factor=10, use_gradient=True):
    """
    MOV -> REF similarity (rotation + scale + translation):
      1) estimate rotation/scale via Fourier–Mellin
      2) apply rot/scale to mov
      3) estimate translation via phase correlation
    """
    angle_deg, scale, fm_error = estimate_rotation_scale_fm(
        ref, mov, upsample_factor=upsample_factor, use_gradient=use_gradient
    )

    mov_rs = apply_rotation_scale(mov, angle_deg, scale, output_shape=ref.shape)

    dy, dx, trans_error = estimate_translation_pcorr(
        ref, mov_rs, upsample_factor=upsample_factor, use_gradient=use_gradient
    )

    return angle_deg, scale, (dy, dx), fm_error, trans_error


# ============================================================
# Tile approach helpers
# ============================================================

def split_two_tiles(H, overlap=256):
    mid = H // 2
    top = (0, min(H, mid + overlap))
    bot = (max(0, mid - overlap), H)
    seam = mid
    return top, bot, seam


def vertical_blend_weights(H, overlap, seam):
    """
    Correct blending weights for top/bottom two-tile blending.

    Guarantees:
      - w_top + w_bot = 1 everywhere
      - top-only region: w_top=1, w_bot=0
      - bottom-only region: w_top=0, w_bot=1
      - overlap: linear ramp
    """
    w_top = np.zeros((H, 1), dtype=np.float32)
    w_bot = np.zeros((H, 1), dtype=np.float32)

    y0 = max(0, seam - overlap)
    y1 = min(H, seam + overlap)

    # Top-only region
    w_top[:y0, :] = 1.0
    w_bot[:y0, :] = 0.0

    # Bottom-only region
    w_top[y1:, :] = 0.0
    w_bot[y1:, :] = 1.0

    # Overlap region
    if y1 > y0:
        ramp = np.linspace(1.0, 0.0, y1 - y0, dtype=np.float32)[:, None]
        w_top[y0:y1, :] = ramp
        w_bot[y0:y1, :] = 1.0 - ramp

    return w_top, w_bot


def tile_to_global_similarity(tform_local, x0, y0):
    """
    Convert tile-local similarity transform to global coords:
      T_global = shift_back ∘ T_local ∘ shift_to_tile
    """
    shift_to_tile = SimilarityTransform(translation=(-x0, -y0))
    shift_back = SimilarityTransform(translation=(x0, y0))
    M_global = shift_back.params @ tform_local.params @ shift_to_tile.params
    return SimilarityTransform(matrix=M_global)


def similarity_register_two_tiles(
    ref,
    mov,
    overlap=256,
    upsample_factor=20,
    use_gradient=True,
    bg=0,
    verbose=True,
    fm_err_max=0.6,
    tr_err_max=0.6,
):
    """
    Per-tile similarity register (top/bottom) + blend.
    Returns:
      mov_blend, tform_top_global, tform_bot_global, diagnostics
    """

    H, W = ref.shape
    top_rng, bot_rng, seam = split_two_tiles(H, overlap=overlap)
    (ty0, ty1) = top_rng
    (by0, by1) = bot_rng

    # tiles
    ref_top = ref[ty0:ty1, :]
    mov_top = mov[ty0:ty1, :]
    ref_bot = ref[by0:by1, :]
    mov_bot = mov[by0:by1, :]

    # estimate similarity per tile
    if verbose:
        print(f"[TILE TOP] rows {ty0}:{ty1}")
    angle_t, scale_t, (dy_t, dx_t), fm_t, tr_t = similarity_register(
        ref_top, mov_top, upsample_factor=upsample_factor, use_gradient=use_gradient
    )
    if verbose:
        print(f"  [TOP SIM] angle={angle_t:.3f} deg, scale={scale_t:.6f}, shift=({dy_t:.2f},{dx_t:.2f}), "
              f"errors fm={fm_t:.3f}, tr={tr_t:.3f}")

    if verbose:
        print(f"[TILE BOT] rows {by0}:{by1}")
    angle_b, scale_b, (dy_b, dx_b), fm_b, tr_b = similarity_register(
        ref_bot, mov_bot, upsample_factor=upsample_factor, use_gradient=use_gradient
    )
    if verbose:
        print(f"  [BOT SIM] angle={angle_b:.3f} deg, scale={scale_b:.6f}, shift=({dy_b:.2f},{dx_b:.2f}), "
              f"errors fm={fm_b:.3f}, tr={tr_b:.3f}")

    # quality checks + fallback
    top_ok = (fm_t < fm_err_max) and (tr_t < tr_err_max)
    bot_ok = (fm_b < fm_err_max) and (tr_b < tr_err_max)

    if not top_ok and bot_ok:
        if verbose:
            print("  [WARN] Top looks unreliable → copying bottom transform to top.")
        angle_t, scale_t, dy_t, dx_t, fm_t, tr_t = angle_b, scale_b, dy_b, dx_b, fm_b, tr_b
    elif not bot_ok and top_ok:
        if verbose:
            print("  [WARN] Bottom looks unreliable → copying top transform to bottom.")
        angle_b, scale_b, dy_b, dx_b, fm_b, tr_b = angle_t, scale_t, dy_t, dx_t, fm_t, tr_t

    # build local transforms
    tform_top_local = SimilarityTransform(scale=scale_t, rotation=np.deg2rad(angle_t),
                                          translation=(dx_t, dy_t))
    tform_bot_local = SimilarityTransform(scale=scale_b, rotation=np.deg2rad(angle_b),
                                          translation=(dx_b, dy_b))

    # convert to global coords
    tform_top_global = tile_to_global_similarity(tform_top_local, x0=0, y0=ty0)
    tform_bot_global = tile_to_global_similarity(tform_bot_local, x0=0, y0=by0)

    # warp full MOV twice (each with its tile transform)
    warp_top = warp(mov, inverse_map=tform_top_global.inverse, output_shape=ref.shape,
                    order=1, cval=bg, preserve_range=True)
    warp_bot = warp(mov, inverse_map=tform_bot_global.inverse, output_shape=ref.shape,
                    order=1, cval=bg, preserve_range=True)

    # blend
    w_top, w_bot = vertical_blend_weights(H, overlap=overlap, seam=seam)
    mov_blend = warp_top * w_top + warp_bot * w_bot

    diagnostics = {
        "top": dict(angle=angle_t, scale=scale_t, dy=dy_t, dx=dx_t, fm_err=fm_t, tr_err=tr_t),
        "bot": dict(angle=angle_b, scale=scale_b, dy=dy_b, dx=dx_b, fm_err=fm_b, tr_err=tr_b),
        "top_ok": top_ok,
        "bot_ok": bot_ok,
        "top_range": top_rng,
        "bot_range": bot_rng,
        "overlap": overlap
    }

    return mov_blend, tform_top_global, tform_bot_global, diagnostics


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
# Main: two-reference structure (VIS + optional NIR)
# ============================================================

def coreg_two_refs_similarity_fm_tiles(
    images,
    vis_idxs,
    ref_vis,
    nir_idxs=None,
    ref_nir=None,
    upsample_f=100,
    bg=0,
    use_gradient=True,
    overlap=256,
    verbose=True,
    fm_err_max=0.6,
    tr_err_max=0.6,
):
    """
    Coregistration using per-tile Similarity registration (Fourier–Mellin + phase correlation).

    Structure:
      1) VIS bands -> ref_vis (tile-wise)
      2) (optional) ref_nir -> ref_vis (tile-wise)
      3) (optional) NIR bands -> ref_nir (tile-wise), then composed -> ref_vis (tile-wise)

    Returns:
      stack: (n_bands, H, W) aligned in ref_vis frame
      tforms_top: list of SimilarityTransform (MOV->ref_vis) for top-tile warp
      tforms_bot: list of SimilarityTransform (MOV->ref_vis) for bottom-tile warp
      diags: list of dict diagnostics per band
      out_shape: (H, W)
    """

    n_bands = len(images)
    ref = images[ref_vis]
    H, W = ref.shape
    out_shape = (H, W)

    stack = np.zeros((n_bands, H, W), dtype=np.float32)
    tforms_top = [None] * n_bands
    tforms_bot = [None] * n_bands
    diags = [None] * n_bands

    # identity for ref_vis
    stack[ref_vis] = ref.astype(np.float32)
    tforms_top[ref_vis] = SimilarityTransform()
    tforms_bot[ref_vis] = SimilarityTransform()
    diags[ref_vis] = {"identity": True}

    # --------------------------
    # STEP 1: VIS -> ref_vis
    # --------------------------
    if verbose:
        print(f"\n[STEP 1] VIS bands -> ref_vis {ref_vis} (tile-wise)")

    for ib in vis_idxs:
        if ib == ref_vis:
            continue
        if verbose:
            print(f"\n[VIS] Band {ib} -> ref_vis {ref_vis}")

        warped, T_top, T_bot, diag = similarity_register_two_tiles(
            ref=ref,
            mov=images[ib],
            overlap=overlap,
            upsample_factor=upsample_f,
            use_gradient=use_gradient,
            bg=bg,
            verbose=verbose,
            fm_err_max=fm_err_max,
            tr_err_max=tr_err_max
        )

        stack[ib] = warped.astype(np.float32)
        tforms_top[ib] = T_top
        tforms_bot[ib] = T_bot
        diags[ib] = diag

    # If no NIR specified, stop here
    if nir_idxs is None or ref_nir is None or len(nir_idxs) == 0:
        if verbose:
            print("\n[INFO] NIR registration skipped (nir_idxs or ref_nir not provided).")
        return stack, tforms_top, tforms_bot, diags, out_shape

    # --------------------------
    # STEP 2: ref_nir -> ref_vis
    # --------------------------
    if verbose:
        print(f"\n[STEP 2] ref_nir {ref_nir} -> ref_vis {ref_vis} (tile-wise)")

    warped_nref, Tn_top, Tn_bot, diag_nref = similarity_register_two_tiles(
        ref=ref,
        mov=images[ref_nir],
        overlap=overlap,
        upsample_factor=upsample_f,
        use_gradient=use_gradient,
        bg=bg,
        verbose=verbose,
        fm_err_max=fm_err_max,
        tr_err_max=tr_err_max
    )

    stack[ref_nir] = warped_nref.astype(np.float32)
    tforms_top[ref_nir] = Tn_top
    tforms_bot[ref_nir] = Tn_bot
    diags[ref_nir] = diag_nref

    # --------------------------
    # STEP 3: NIR -> ref_nir -> ref_vis (compose top/bot separately)
    # --------------------------
    if verbose:
        print(f"\n[STEP 3] NIR bands -> ref_nir {ref_nir}, then composed -> ref_vis {ref_vis} (tile-wise)")

    ref_nir_img = images[ref_nir]

    for ib in nir_idxs:
        if ib == ref_nir:
            continue
        if verbose:
            print(f"\n[NIR] Band {ib} -> ref_nir {ref_nir} (tile-wise), then -> ref_vis {ref_vis}")

        # local per-tile similarity: band -> ref_nir
        warped_local, Tl_top, Tl_bot, diag_local = similarity_register_two_tiles(
            ref=ref_nir_img,
            mov=images[ib],
            overlap=overlap,
            upsample_factor=upsample_f,
            use_gradient=use_gradient,
            bg=bg,
            verbose=verbose,
            fm_err_max=fm_err_max,
            tr_err_max=tr_err_max
        )

        # Compose GLOBAL transforms:
        # band->ref_vis = (ref_nir->ref_vis) ∘ (band->ref_nir)
        # For tile-wise transforms: do it separately for top and bottom
        M_global_top = Tn_top.params @ Tl_top.params
        M_global_bot = Tn_bot.params @ Tl_bot.params

        Tg_top = SimilarityTransform(matrix=M_global_top)
        Tg_bot = SimilarityTransform(matrix=M_global_bot)
        
        if verbose:
            g_angle_t, g_scale_t, g_dy_t, g_dx_t = similarity_params_from_matrix(Tg_top)
            g_angle_b, g_scale_b, g_dy_b, g_dx_b = similarity_params_from_matrix(Tg_bot)
        
            print(f"  [GLOBAL TOP] angle={g_angle_t:.3f} deg, scale={g_scale_t:.6f}, shift=({g_dy_t:.2f},{g_dx_t:.2f})")
            print(f"  [GLOBAL BOT] angle={g_angle_b:.3f} deg, scale={g_scale_b:.6f}, shift=({g_dy_b:.2f},{g_dx_b:.2f})")

        # warp full band with each tile transform & blend with same weights
        warp_top = warp(images[ib], inverse_map=Tg_top.inverse, output_shape=ref.shape,
                        order=1, cval=bg, preserve_range=True)
        warp_bot = warp(images[ib], inverse_map=Tg_bot.inverse, output_shape=ref.shape,
                        order=1, cval=bg, preserve_range=True)

        seam = H // 2
        w_top, w_bot = vertical_blend_weights(H, overlap=overlap, seam=seam)
        warped_global = warp_top * w_top + warp_bot * w_bot

        stack[ib] = warped_global.astype(np.float32)
        tforms_top[ib] = Tg_top
        tforms_bot[ib] = Tg_bot

        diags[ib] = {
            "local_to_ref_nir": diag_local,
            "composed": True
        }

    return stack, tforms_top, tforms_bot, diags, out_shape
