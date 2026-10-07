#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 24 16:23:33 2025
"""

import numpy as np
from scipy.fft import fft2, fftshift
from scipy.ndimage import zoom
from skimage.filters import sobel, gaussian
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


def _preprocess_for_pcorr(im, use_gradient=True, valid_mask=None, mask_soft_sigma=8.0):
    im = np.asarray(im, dtype=np.float32)
    if use_gradient:
        im = sobel(im)

    if valid_mask is not None:
        vm = np.asarray(valid_mask, dtype=bool)
        # soft mask to avoid FFT ringing
        w = gaussian(vm.astype(np.float32), sigma=mask_soft_sigma, preserve_range=True)
        w /= (w.max() + 1e-6)
        im = np.where(vm, im, 0.0)
        im = im * w

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

    angle_deg = (shift_theta / lp_ref.shape[0]) * 360.0
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

import numpy as np
from scipy.ndimage import zoom
from skimage.transform import rotate

def apply_rotation_scale_mask(mask, angle_deg, scale, output_shape, thresh=0.5):
    """
    Apply isotropic scale then rotation (around center) to a boolean mask,
    returning a boolean mask with shape=output_shape.

    This mirrors apply_rotation_scale() logic:
      1) zoom (scale)
      2) center crop/pad to output_shape
      3) rotate (no resize)

    Parameters
    ----------
    mask : array-like (H,W) bool or 0/1
    angle_deg : float
        Rotation angle in degrees (applied to mask).
    scale : float
        Isotropic scale (applied to mask).
    output_shape : tuple
        (Ht, Wt) desired output shape (typically ref.shape).
    thresh : float
        Threshold to binarize after transforms.

    Returns
    -------
    mask_rs : (Ht, Wt) boolean mask
    """
    mask = np.asarray(mask).astype(np.float32)

    # 1) scale (nearest neighbor is best for masks)
    if abs(scale - 1.0) > 1e-6:
        m_scaled = zoom(mask, (scale, scale), order=0)
    else:
        m_scaled = mask

    # 2) center crop/pad to output_shape
    Ht, Wt = output_shape
    H, W = m_scaled.shape

    # center-crop if too large
    if H > Ht:
        sy = (H - Ht) // 2
        m_scaled = m_scaled[sy:sy + Ht, :]
    if W > Wt:
        sx = (W - Wt) // 2
        m_scaled = m_scaled[:, sx:sx + Wt]

    # center-pad if too small
    H, W = m_scaled.shape
    if H < Ht or W < Wt:
        pad_y = max(0, Ht - H)
        pad_x = max(0, Wt - W)
        p0 = pad_y // 2
        p1 = pad_y - p0
        q0 = pad_x // 2
        q1 = pad_x - q0
        m_scaled = np.pad(
            m_scaled,
            ((p0, p1), (q0, q1)),
            mode="constant",
            constant_values=0
        )

    # 3) rotate (nearest neighbor; keep size)
    if abs(angle_deg) > 1e-6:
        m_rs = rotate(
            m_scaled,
            angle=angle_deg,
            resize=False,
            preserve_range=True,
            order=0
        )
    else:
        m_rs = m_scaled

    return (m_rs > thresh)

def estimate_translation_pcorr(
    ref,
    mov,
    upsample_factor=10,
    use_gradient=True,
    valid_ref=None,
    valid_mov=None,
    mask_soft_sigma=8.0,
):
    """
    Estimate translation (dy, dx) via phase correlation.

    Supports optional validity masks:
      - valid_ref: boolean mask for REF (same shape as ref)
      - valid_mov: boolean mask for MOV (same shape as mov)

    The masks are applied inside _preprocess_for_pcorr() using a soft mask
    (Gaussian blur) to reduce FFT edge artifacts.
    """
    if valid_ref is None:
        valid_ref = np.ones_like(ref, dtype=bool)
    if valid_mov is None:
        valid_mov = np.ones_like(mov, dtype=bool)

    ref_p = _preprocess_for_pcorr(
        ref, use_gradient=use_gradient, valid_mask=valid_ref, mask_soft_sigma=mask_soft_sigma
    )
    mov_p = _preprocess_for_pcorr(
        mov, use_gradient=use_gradient, valid_mask=valid_mov, mask_soft_sigma=mask_soft_sigma
    )

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


def valid_mask_from_range(im, vmin=None, vmax=None):
    im = np.asarray(im)
    m = np.isfinite(im)
    if vmin is not None:
        m &= (im >= vmin)
    if vmax is not None:
        m &= (im <= vmax)
    return m

def soften_mask(mask, sigma=8.0):
    """Blur mask to reduce sharp edges (good for FFT/Fourier–Mellin)."""
    m = gaussian(mask.astype(np.float32), sigma=sigma, preserve_range=True)
    m /= (m.max() + 1e-6)
    return np.clip(m, 0.0, 1.0)


def tile_to_global_similarity(tform_local, x0, y0):
    """
    Convert tile-local similarity transform to global coords:
      T_global = shift_back ∘ T_local ∘ shift_to_tile
    """
    shift_to_tile = SimilarityTransform(translation=(-x0, -y0))
    shift_back = SimilarityTransform(translation=(x0, y0))
    M_global = shift_back.params @ tform_local.params @ shift_to_tile.params
    return SimilarityTransform(matrix=M_global)


def similarity_register_two_tiles_masked(
    ref, mov,
    valid_ref=None, valid_mov=None,
    overlap=256,
    upsample_factor=20,
    use_gradient=True,
    bg=0,
    verbose=True,
    fm_err_max=0.6,
    tr_err_max=0.6,
    mask_soft_sigma=8.0,   # used inside similarity_register preprocessing
):
    """
    Two-tile Similarity registration (MOV -> REF) with validity masks.

    - Per-tile: estimates (angle,scale,dy,dx) using similarity_register()
      which internally applies soft masks during FM/PCorr and also warps the
      moving validity mask through rot/scale before translation estimation.
    - Produces global transforms for TOP and BOT and blends the two full-image warps.
    """

    ref = np.asarray(ref)
    mov = np.asarray(mov)

    H, W = ref.shape
    seam = H // 2
    top0, top1 = 0, min(H, seam + overlap)
    bot0, bot1 = max(0, seam - overlap), H

    if valid_ref is None:
        valid_ref = np.ones((H, W), dtype=bool)
    if valid_mov is None:
        valid_mov = np.ones((H, W), dtype=bool)

    # --- slice tiles (images + masks) ---
    ref_top  = ref[top0:top1, :]
    mov_top  = mov[top0:top1, :]
    vref_top = valid_ref[top0:top1, :]
    vmov_top = valid_mov[top0:top1, :]

    ref_bot  = ref[bot0:bot1, :]
    mov_bot  = mov[bot0:bot1, :]
    vref_bot = valid_ref[bot0:bot1, :]
    vmov_bot = valid_mov[bot0:bot1, :]

    # --- estimate similarity per tile (mask-aware) ---
    if verbose:
        print(f"[TILE TOP] rows {top0}:{top1}")

    angle_t, scale_t, (dy_t, dx_t), fm_t, tr_t = similarity_register(
        ref_top, mov_top,
        upsample_factor=upsample_factor,
        use_gradient=use_gradient,
        valid_ref=vref_top,
        valid_mov=vmov_top,
        mask_soft_sigma=mask_soft_sigma,
    )

    ok_top = (fm_t < fm_err_max) and (tr_t < tr_err_max)
    if verbose:
        print(f"  [TOP SIM] angle={angle_t:.4f} deg, scale={scale_t:.6f}, "
              f"shift=({dy_t:.2f},{dx_t:.2f}), errors fm={fm_t:.3f}, tr={tr_t:.3f}, ok={ok_top}")

    if verbose:
        print(f"[TILE BOT] rows {bot0}:{bot1}")

    angle_b, scale_b, (dy_b, dx_b), fm_b, tr_b = similarity_register(
        ref_bot, mov_bot,
        upsample_factor=upsample_factor,
        use_gradient=use_gradient,
        valid_ref=vref_bot,
        valid_mov=vmov_bot,
        mask_soft_sigma=mask_soft_sigma,
    )

    ok_bot = (fm_b < fm_err_max) and (tr_b < tr_err_max)
    if verbose:
        print(f"  [BOT SIM] angle={angle_b:.4f} deg, scale={scale_b:.6f}, "
              f"shift=({dy_b:.2f},{dx_b:.2f}), errors fm={fm_b:.3f}, tr={tr_b:.3f}, ok={ok_bot}")

    # --- build tile-local transforms (tile coordinates) ---
    T_top_local = SimilarityTransform(
        scale=scale_t,
        rotation=np.deg2rad(angle_t),
        translation=(dx_t, dy_t)
    )
    T_bot_local = SimilarityTransform(
        scale=scale_b,
        rotation=np.deg2rad(angle_b),
        translation=(dx_b, dy_b)
    )

    # --- convert to global coords (account for tile y-offset) ---
    def tile_to_global(T_local, y0):
        shift_to_tile = SimilarityTransform(translation=(0, -y0))
        shift_back    = SimilarityTransform(translation=(0,  y0))
        return SimilarityTransform(matrix=shift_back.params @ T_local.params @ shift_to_tile.params)

    T_top = tile_to_global(T_top_local, y0=top0)
    T_bot = tile_to_global(T_bot_local, y0=bot0)

    # --- warp full mov with each transform and blend ---
    warp_top = warp(
        mov, inverse_map=T_top.inverse, output_shape=ref.shape,
        order=1, cval=bg, preserve_range=True
    ).astype(np.float32)

    warp_bot = warp(
        mov, inverse_map=T_bot.inverse, output_shape=ref.shape,
        order=1, cval=bg, preserve_range=True
    ).astype(np.float32)

    w_top, w_bot = vertical_blend_weights(H, overlap=overlap, seam=seam)  # your corrected weights
    warped = warp_top * w_top + warp_bot * w_bot

    diag = {
        "top": {
            "tile_rows": (top0, top1),
            "angle": angle_t, "scale": scale_t, "dy": dy_t, "dx": dx_t,
            "fm_err": fm_t, "tr_err": tr_t, "ok": ok_top
        },
        "bot": {
            "tile_rows": (bot0, bot1),
            "angle": angle_b, "scale": scale_b, "dy": dy_b, "dx": dx_b,
            "fm_err": fm_b, "tr_err": tr_b, "ok": ok_bot
        },
    }

    return warped, T_top, T_bot, diag




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
    valid_ranges=None,          # NEW: [[min0,max0], ...]
    mask_soft_sigma=8.0,        # NEW: soft mask blur sigma for FM
):
    n_bands = len(images)
    ref = images[ref_vis]
    H, W = ref.shape
    out_shape = (H, W)

    # --- helper: per-band valid mask ---
    def band_valid_mask(bi):
        if valid_ranges is None:
            return np.isfinite(images[bi])
        vmin, vmax = valid_ranges[bi]
        return valid_mask_from_range(images[bi], vmin, vmax)

    valid_ref_vis = band_valid_mask(ref_vis)

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

        valid_mov = band_valid_mask(ib)

        warped, T_top, T_bot, diag = similarity_register_two_tiles_masked(
            ref=ref,
            mov=images[ib],
            valid_ref=valid_ref_vis,
            valid_mov=valid_mov,
            overlap=overlap,
            upsample_factor=upsample_f,
            use_gradient=use_gradient,
            bg=bg,
            verbose=verbose,
            fm_err_max=fm_err_max,
            tr_err_max=tr_err_max,
            mask_soft_sigma=mask_soft_sigma,
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

    valid_mov_nref = band_valid_mask(ref_nir)

    warped_nref, Tn_top, Tn_bot, diag_nref = similarity_register_two_tiles_masked(
        ref=ref,
        mov=images[ref_nir],
        valid_ref=valid_ref_vis,
        valid_mov=valid_mov_nref,
        overlap=overlap,
        upsample_factor=upsample_f,
        use_gradient=use_gradient,
        bg=bg,
        verbose=verbose,
        fm_err_max=fm_err_max,
        tr_err_max=tr_err_max,
        mask_soft_sigma=mask_soft_sigma,
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
    valid_ref_nir = band_valid_mask(ref_nir)

    for ib in nir_idxs:
        if ib == ref_nir:
            continue
        if verbose:
            print(f"\n[NIR] Band {ib} -> ref_nir {ref_nir} (tile-wise), then -> ref_vis {ref_vis}")

        valid_mov = band_valid_mask(ib)

        warped_local, Tl_top, Tl_bot, diag_local = similarity_register_two_tiles_masked(
            ref=ref_nir_img,
            mov=images[ib],
            valid_ref=valid_ref_nir,
            valid_mov=valid_mov,
            overlap=overlap,
            upsample_factor=upsample_f,
            use_gradient=use_gradient,
            bg=bg,
            verbose=verbose,
            fm_err_max=fm_err_max,
            tr_err_max=tr_err_max,
            mask_soft_sigma=mask_soft_sigma,
        )

        # compose GLOBAL transforms
        Tg_top = SimilarityTransform(matrix=(Tn_top.params @ Tl_top.params))
        Tg_bot = SimilarityTransform(matrix=(Tn_bot.params @ Tl_bot.params))

        if verbose:
            g_angle_t, g_scale_t, g_dy_t, g_dx_t = similarity_params_from_matrix(Tg_top)
            g_angle_b, g_scale_b, g_dy_b, g_dx_b = similarity_params_from_matrix(Tg_bot)
            print(f"  [GLOBAL TOP] angle={g_angle_t:.3f} deg, scale={g_scale_t:.6f}, shift=({g_dy_t:.2f},{g_dx_t:.2f})")
            print(f"  [GLOBAL BOT] angle={g_angle_b:.3f} deg, scale={g_scale_b:.6f}, shift=({g_dy_b:.2f},{g_dx_b:.2f})")

        # warp+blend global
        warp_top = warp(images[ib], inverse_map=Tg_top.inverse, output_shape=ref.shape,
                        order=1, cval=bg, preserve_range=True)
        warp_bot = warp(images[ib], inverse_map=Tg_bot.inverse, output_shape=ref.shape,
                        order=1, cval=bg, preserve_range=True)

        seam = H // 2
        w_top, w_bot = vertical_blend_weights(H, overlap=overlap, seam=seam)  # corrected version
        warped_global = warp_top * w_top + warp_bot * w_bot

        stack[ib] = warped_global.astype(np.float32)
        tforms_top[ib] = Tg_top
        tforms_bot[ib] = Tg_bot
        diags[ib] = {"local_to_ref_nir": diag_local, "composed": True}

    return stack, tforms_top, tforms_bot, diags, out_shape

