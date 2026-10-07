#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 24 13:38:48 2025

@author: yp and Chatgpt5.2
"""

import numpy as np
from scipy.fft import fft2, fftshift
from scipy.ndimage import zoom
from skimage.filters import sobel
from skimage.transform import warp_polar, SimilarityTransform, warp, rotate
from skimage.registration import phase_cross_correlation


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------

def _norm01(x):
    x = np.asarray(x, dtype=np.float32)
    x = x - np.nanmin(x)
    r = np.nanmax(x) - np.nanmin(x)
    if r < 1e-12:
        return np.zeros_like(x, dtype=np.float32)
    return x / r


def _preprocess_for_pcorr(im, use_gradient=True, blur_sigma=None):
    """Preprocess for phase correlation / Fourier-Mellin."""
    im = np.asarray(im, dtype=np.float32)
    # Optional blur (often not needed; you can add Gaussian later if desired)
    if use_gradient:
        im = sobel(im)
    im = _norm01(im)
    return im


def estimate_rotation_scale_fm(ref, mov, upsample_factor=10, use_gradient=True):
    """
    Estimate (rotation, scale) using Fourier magnitude + log-polar phase correlation.
    Returns:
        angle_deg: angle to rotate MOV to align with REF (deg; +CCW)
        scale: scale factor to apply to MOV to align with REF
        fm_error: phase correlation error in log-polar space (lower is better)
    """

    ref_p = _preprocess_for_pcorr(ref, use_gradient=use_gradient)
    mov_p = _preprocess_for_pcorr(mov, use_gradient=use_gradient)

    # Fourier magnitude
    F_ref = np.abs(fftshift(fft2(ref_p)))
    F_mov = np.abs(fftshift(fft2(mov_p)))

    # Log amplitude to compress dynamic range
    F_ref = np.log1p(F_ref)
    F_mov = np.log1p(F_mov)

    # Log-polar mapping
    radius = min(ref.shape) // 2
    lp_ref = warp_polar(F_ref, radius=radius, scaling="log")
    lp_mov = warp_polar(F_mov, radius=radius, scaling="log")

    # Phase correlation in log-polar
    (shift_r, shift_theta), fm_error, _ = phase_cross_correlation(
        lp_ref, lp_mov, upsample_factor=upsample_factor
    )

    # Convert theta shift to degrees
    # warp_polar output shape: (num_angles, radius)
    num_angles = lp_ref.shape[0]
    angle_deg = (shift_theta / num_angles) * 360.0

    # Convert radial shift to scale
    # In log radius space, translation corresponds to multiplicative scaling
    # The mapping uses log scaling with radius samples = lp_ref.shape[1]
    # A standard approximation:
    scale = np.exp(shift_r / lp_ref.shape[1])

    return float(angle_deg), float(scale), float(fm_error)


def apply_rotation_scale(im, angle_deg, scale, output_shape):
    """
    Apply rotation and isotropic scaling around center to an image, returning output_shape.
    """
    im = np.asarray(im, dtype=np.float32)

    # 1) Scale (zoom) first
    if abs(scale - 1.0) > 1e-6:
        im_scaled = zoom(im, (scale, scale), order=1)
    else:
        im_scaled = im

    # 2) Center-crop/pad scaled image back to output_shape
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
        im_scaled = np.pad(im_scaled, ((p0, p1), (q0, q1)), mode='constant', constant_values=0)

    # 3) Rotate around center (no resize)
    if abs(angle_deg) > 1e-6:
        im_rs = rotate(im_scaled, angle=angle_deg, resize=False, preserve_range=True, order=1)
    else:
        im_rs = im_scaled

    return im_rs


def estimate_translation_pcorr(ref, mov, upsample_factor=10, use_gradient=True):
    """
    Estimate translation (dy, dx) using phase_cross_correlation on (optionally) Sobel images.
    Returns:
        dy, dx, trans_error
    """
    ref_p = _preprocess_for_pcorr(ref, use_gradient=use_gradient)
    mov_p = _preprocess_for_pcorr(mov, use_gradient=use_gradient)

    (dy, dx), trans_error, _ = phase_cross_correlation(
        ref_p, mov_p, upsample_factor=upsample_factor
    )
    return float(dy), float(dx), float(trans_error)


def similarity_register(ref, mov, upsample_factor=10, use_gradient=True):
    """
    Full similarity registration MOV -> REF:
      1) estimate (rotation, scale) via Fourier–Mellin (log-polar)
      2) apply rotation+scale to MOV
      3) estimate translation via phase correlation
    Returns:
      angle_deg, scale, (dy, dx), fm_error, trans_error
    """
    angle_deg, scale, fm_error = estimate_rotation_scale_fm(
        ref, mov, upsample_factor=upsample_factor, use_gradient=use_gradient
    )

    mov_rs = apply_rotation_scale(mov, angle_deg, scale, output_shape=ref.shape)

    dy, dx, trans_error = estimate_translation_pcorr(
        ref, mov_rs, upsample_factor=upsample_factor, use_gradient=use_gradient
    )

    return angle_deg, scale, (dy, dx), fm_error, trans_error


def warp_similarity_to_ref(mov, ref_shape, angle_deg, scale, dy, dx, bg=0):
    """
    Warp MOV into REF coordinate system using SimilarityTransform (rotation+scale+translation).
    """
    tform = SimilarityTransform(scale=scale, rotation=np.deg2rad(angle_deg), translation=(dx, dy))
    warped = warp(
        mov,
        inverse_map=tform.inverse,
        output_shape=ref_shape,
        order=1,
        cval=bg,
        preserve_range=True
    )
    return warped, tform


# ------------------------------------------------------------
# Main function: two-reference structure like coreg_two_refs
# ------------------------------------------------------------

def coreg_two_refs_similarity_fm(
    images,
    vis_idxs,
    ref_vis,
    nir_idxs=None,
    ref_nir=None,
    upsample_f=10,
    bg=0,
    use_gradient=True,
    verbose=True
):
    """
    Similarity-based coregistration using:
      - Rotation+scale from Fourier–Mellin (log-polar phase correlation)
      - Translation from phase_cross_correlation

    Mirrors your structure:
      1) VIS bands -> ref_vis
      2) (optional) ref_nir -> ref_vis
      3) (optional) other NIR -> ref_nir, then composed into ref_vis

    Returns:
      stack: warped bands in ref_vis frame (n_bands, H, W)
      params: list of dicts with angle, scale, shift, errors
      tforms: list of SimilarityTransform (mov -> ref_vis)
      out_shape: (H, W)
    """

    n_bands = len(images)
    ref = images[ref_vis]
    H, W = ref.shape
    out_shape = (H, W)

    stack = np.zeros((n_bands, H, W), dtype=np.float32)
    params = [None] * n_bands
    tforms = [None] * n_bands

    # Identity for ref_vis
    stack[ref_vis] = ref
    params[ref_vis] = dict(angle_deg=0.0, scale=1.0, dy=0.0, dx=0.0, fm_error=0.0, trans_error=0.0)
    tforms[ref_vis] = SimilarityTransform()

    # ---- Step 1: VIS group -> ref_vis
    if verbose:
        print(f"\n[STEP 1] VIS bands -> ref_vis {ref_vis}")

    for ib in vis_idxs:
        if ib == ref_vis:
            continue
        if verbose:
            print(f"\n[VIS] Band {ib} -> ref_vis {ref_vis}")

        angle_deg, scale, (dy, dx), fm_err, tr_err = similarity_register(
            ref, images[ib], upsample_factor=upsample_f, use_gradient=use_gradient
        )

        warped, tform = warp_similarity_to_ref(images[ib], ref.shape, angle_deg, scale, dy, dx, bg=bg)
        stack[ib] = warped.astype(np.float32)
        params[ib] = dict(angle_deg=angle_deg, scale=scale, dy=dy, dx=dx, fm_error=fm_err, trans_error=tr_err)
        tforms[ib] = tform

        if verbose:
            print(f"  [SIM] angle={angle_deg:.4f} deg, scale={scale:.6f}, shift(dy,dx)=({dy:.3f},{dx:.3f}), "
                  f"errors fm={fm_err:.4f}, tr={tr_err:.4f}")

    # ---- Step 2 & 3: NIR group optional
    if nir_idxs is not None and len(nir_idxs) > 0 and ref_nir is not None:
        if verbose:
            print(f"\n[STEP 2] ref_nir {ref_nir} -> ref_vis {ref_vis}")

        angle_deg, scale, (dy, dx), fm_err, tr_err = similarity_register(
            ref, images[ref_nir], upsample_factor=upsample_f, use_gradient=use_gradient
        )

        warped, tform_nref_to_vis = warp_similarity_to_ref(images[ref_nir], ref.shape, angle_deg, scale, dy, dx, bg=bg)
        stack[ref_nir] = warped.astype(np.float32)
        params[ref_nir] = dict(angle_deg=angle_deg, scale=scale, dy=dy, dx=dx, fm_error=fm_err, trans_error=tr_err)
        tforms[ref_nir] = tform_nref_to_vis

        if verbose:
            print(f"  [SIM] ref_nir angle={angle_deg:.4f} deg, scale={scale:.6f}, shift=({dy:.3f},{dx:.3f}), "
                  f"errors fm={fm_err:.4f}, tr={tr_err:.4f}")

        # Step 3: Other NIR -> ref_nir then compose -> ref_vis
        if verbose:
            print(f"\n[STEP 3] NIR bands -> ref_nir {ref_nir}, composed -> ref_vis {ref_vis}")

        ref_nir_img = images[ref_nir]

        for ib in nir_idxs:
            if ib == ref_nir:
                continue
            if verbose:
                print(f"\n[NIR] Band {ib} -> ref_nir {ref_nir} (local), then -> ref_vis {ref_vis}")

            # local similarity: band -> ref_nir
            angle_deg_l, scale_l, (dy_l, dx_l), fm_err_l, tr_err_l = similarity_register(
                ref_nir_img, images[ib], upsample_factor=upsample_f, use_gradient=use_gradient
            )

            tform_local = SimilarityTransform(
                scale=scale_l, rotation=np.deg2rad(angle_deg_l), translation=(dx_l, dy_l)
            )

            # compose: (ref_nir -> ref_vis) o (band -> ref_nir)
            # SimilarityTransform supports matrix composition via params
            M_global = tform_nref_to_vis.params @ tform_local.params
            tform_global = SimilarityTransform(matrix=M_global)

            warped = warp(
                images[ib],
                inverse_map=tform_global.inverse,
                output_shape=ref.shape,
                order=1,
                cval=bg,
                preserve_range=True
            )

            stack[ib] = warped.astype(np.float32)
            tforms[ib] = tform_global

            # For reporting, you can also decompose tform_global (optional)
            params[ib] = dict(
                angle_deg_local=angle_deg_l, scale_local=scale_l, dy_local=dy_l, dx_local=dx_l,
                fm_error_local=fm_err_l, trans_error_local=tr_err_l,
                composed=True
            )

            if verbose:
                print(f"  [LOCAL SIM] angle={angle_deg_l:.4f} deg, scale={scale_l:.6f}, shift=({dy_l:.3f},{dx_l:.3f}), "
                      f"errors fm={fm_err_l:.4f}, tr={tr_err_l:.4f}")
                # Print global transform summary
                # SimilarityTransform stores rotation in radians accessible from params
                rot_global = np.degrees(np.arctan2(M_global[1,0], M_global[0,0]))
                scl_global = np.sqrt(M_global[0,0]**2 + M_global[1,0]**2)
                print(f"  [GLOBAL SIM] approx angle={rot_global:.4f} deg, scale={scl_global:.6f}, "
                      f"translation=({M_global[0,2]:.3f},{M_global[1,2]:.3f})")

    else:
        if verbose:
            print("\n[INFO] NIR registration skipped (nir_idxs or ref_nir not provided).")

    # Convert stack back to original dtype if you want
    # stack = stack.astype(images[0].dtype)

    return stack, params, tforms, out_shape
