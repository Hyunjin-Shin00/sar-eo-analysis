#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 28 15:38:40 2025

@author: yp
"""

import numpy as np


def match_4band_image(X, bases):
    """
    X:      (4, ncols, nrows) float32/float64
    bases:  (K, 4) float32/float64

    Returns:
      best_basis: (ncols, nrows) int16
      c_star:     (ncols, nrows) float32   # additive bias in original units
      score:      (ncols, nrows) float32   # cosine on demeaned vectors
    """
    X = np.asarray(X, dtype=np.float32)
    B = np.asarray(bases, dtype=np.float32)          # (K,4)

    # Precompute per-basis mean and demeaned, unit-norm basis cols (shape (4,K))
    bk_mean = B.mean(axis=1)                         # (K,)
    B0 = B - bk_mean[:, None]                        # (K,4)
    B0 /= (np.linalg.norm(B0, axis=1, keepdims=True) + 1e-12)
    Bu = B0.T                                        # (4,K)

    # Per-pixel mean & demean
    mx = X.mean(axis=0)                              # (C,R)
    X0 = X - mx[None, :, :]                          # (4,C,R)
    X0_norm = np.sqrt(np.sum(X0*X0, axis=0)) + 1e-12 # (C,R)
    Xu = X0 / X0_norm[None, :, :]                    # (4,C,R)

    # Compute scores: (K, C*R) = (K,4) @ (4, C*R); then reshape to (K,C,R)
    C, R = X.shape[1], X.shape[2]
    Scores = (Bu.T @ Xu.reshape(4, C*R)).reshape(B.shape[0], C, R)  # (K,C,R)

    # Best basis per pixel
    best_k = np.argmax(Scores, axis=0).astype(np.int16)             # (C,R)
    score  = np.take_along_axis(Scores, best_k[None, ...], axis=0)[0].astype(np.float32)

    # Additive bias in ORIGINAL units
    c_star = (mx - bk_mean[best_k]).astype(np.float32)              # (C,R)

    return best_k, c_star, score

def match_4band_image_topk(X, bases, topk=3):
    """
    X:      (4, ncols, nrows) float32/float64
    bases:  (K, 4)            float32/float64
    topk:   int               number of best matches per pixel

    Returns:
      best_basis: (topk, ncols, nrows) int16       # basis indices [0..K-1]
      c_star:     (topk, ncols, nrows) float32     # additive bias per match (original units)
      score:      (topk, ncols, nrows) float32     # cosine similarity on demeaned vectors
    """
    X = np.asarray(X, dtype=np.float32)
    B = np.asarray(bases, dtype=np.float32)          # (K,4)
    K = B.shape[0]
    k = min(int(topk), K)

    # ---- Precompute per-basis pieces ----
    bk_mean = B.mean(axis=1)                         # (K,)
    B0 = B - bk_mean[:, None]                        # (K,4)
    B0 /= (np.linalg.norm(B0, axis=1, keepdims=True) + 1e-12)
    Bu = B0.T                                        # (4,K) columns are unit demeaned bases

    # ---- Per-pixel de-mean + unit vector ----
    C, R = X.shape[1], X.shape[2]
    mx = X.mean(axis=0)                              # (C,R)
    X0 = X - mx[None, :, :]                          # (4,C,R)
    X0_norm = np.sqrt(np.sum(X0 * X0, axis=0)) + 1e-12
    Xu = X0 / X0_norm[None, :, :]                    # (4,C,R)

    # ---- Scores: (K, C, R) ----
    Scores = (Bu.T @ Xu.reshape(4, C * R)).reshape(K, C, R)

    # ---- Top-k along the basis axis (axis=0) ----
    # 1) Unordered top-k with argpartition
    idx_part = np.argpartition(Scores, -k, axis=0)[-k:, :, :]        # (k,C,R)
    scores_part = np.take_along_axis(Scores, idx_part, axis=0)       # (k,C,R)

    # 2) Order those k in descending score
    order = np.argsort(-scores_part, axis=0)                          # (k,C,R)
    best_basis = np.take_along_axis(idx_part,   order, axis=0).astype(np.int16)
    score      = np.take_along_axis(scores_part, order, axis=0).astype(np.float32)

    # ---- Bias per candidate (original units) ----
    # c* = mean(x) - mean(b_k) for each selected k
    c_star = (mx[None, :, :] - bk_mean[best_basis]).astype(np.float32)  # (k,C,R)

    return best_basis, c_star, score

def downsample_mean_chw(x, fx=2, fy=2, pad=False, fill_value=np.nan):
    """
    x: (C, H, W)
    Returns: (C, H//fx, W//fy) (or padded/cropped)
    """
    C, H, W = x.shape
    H2 = (H + (-H % fx)) if pad else (H - H % fx)
    W2 = (W + (-W % fy)) if pad else (W - W % fy)

    if pad and (H2 > H or W2 > W):
        x = np.pad(x, ((0,0), (0, H2-H), (0, W2-W)), constant_values=fill_value)
    else:
        x = x[:, :H2, :W2]

    x = x.reshape(C, H2//fx, fx, W2//fy, fy).mean(axis=(2, 4))
    return x

def match_image_templateu_topk(X, bases, u, topk=3):
    """
    Returns:
      best_basis: (topk, C, R) int16
      alpha_star: (topk, C, R) float32
      score:      (topk, C, R) float32
    """
    X = np.asarray(X, dtype=np.float32)
    B = np.asarray(bases, dtype=np.float32)
    u = np.asarray(u, dtype=np.float32)

    nb = X.shape[0]
    assert B.shape[1] == nb, "bases must have shape (K, nb)"
    assert u.shape[0] == nb, "u must have length nb == X.shape[0]"

    C, R = X.shape[1], X.shape[2]
    K = B.shape[0]
    k = min(int(topk), K)
    eps = 1e-12

    u2  = float(np.dot(u, u))
    uTX = np.tensordot(u, X, axes=([0],[0]))            # (C,R)
    uTB = (B * u[None, :]).sum(axis=1)                  # (K,)

    Xp = X - u[:, None, None] * (uTX / u2)[None, :, :]
    Bp = B - (uTB[:, None] / u2) * u[None, :]

    Bp_norm = np.linalg.norm(Bp, axis=1, keepdims=True) + eps
    Bu = (Bp / Bp_norm).astype(np.float32)              # (K, nb)

    Xp_norm = np.sqrt((Xp * Xp).sum(axis=0)) + eps
    Xu = Xp / Xp_norm[None, :, :]

    Scores = (Bu @ Xu.reshape(nb, C * R)).reshape(K, C, R)

    # Unordered top-k then sort descending
    idx_part    = np.argpartition(Scores, -k, axis=0)[-k:, :, :]     # (k,C,R)
    scores_part = np.take_along_axis(Scores, idx_part, axis=0)       # (k,C,R)
    order       = np.argsort(-scores_part, axis=0)                   # (k,C,R)

    best_basis = np.take_along_axis(idx_part,   order, axis=0).astype(np.int16)
    score      = np.take_along_axis(scores_part, order, axis=0).astype(np.float32)

    # alpha* for each candidate: (u^T x - u^T b_k) / (u^T u)
    alpha_star = (uTX[None, :, :] - uTB[best_basis]) / u2
    alpha_star = alpha_star.astype(np.float32)

    return best_basis, alpha_star, score


def match_image_templateu_topk_nnalpha(X, bases, u, topk=3):
    """
    Only selects bases with non-negative alpha.
    X:      (nb, C, R) float32/64
    bases:  (K, nb)    float32/64
    u:      (nb,)      float32/64
    Returns:
      best_basis: (topk, C, R) int16    # -1 where no valid candidate
      alpha_star: (topk, C, R) float32  # NaN where invalid
      score:      (topk, C, R) float32  # NaN where invalid (cosine in u-projected space)
    """
    X = np.asarray(X, dtype=np.float32)
    B = np.asarray(bases, dtype=np.float32)
    u = np.asarray(u, dtype=np.float32)

    nb = X.shape[0]
    assert B.shape[1] == nb, "bases must have shape (K, nb)"
    assert u.shape[0] == nb, "u must have length nb == X.shape[0]"

    C, R = X.shape[1], X.shape[2]
    K = B.shape[0]
    k = min(int(topk), K)
    eps = 1e-12

    # Precompute projections onto u
    u2  = float(np.dot(u, u))
    if u2 <= 0:
        raise ValueError("u must be non-zero")
    uTX = np.tensordot(u, X, axes=([0],[0]))       # (C,R)
    uTB = (B * u[None, :]).sum(axis=1)             # (K,)

    # Project out u for matching scores (shape comparison after removing u)
    Xp = X - u[:, None, None] * (uTX / u2)[None, :, :]
    Bp = B - (uTB[:, None] / u2) * u[None, :]

    # Cosine similarity in projected space
    Bp_norm = np.linalg.norm(Bp, axis=1, keepdims=True) + eps
    Bu = (Bp / Bp_norm).astype(np.float32)         # (K, nb)
    Xp_norm = np.sqrt((Xp * Xp).sum(axis=0)) + eps
    Xu = Xp / Xp_norm[None, :, :]                  # (nb, C, R)
    Scores = (Bu @ Xu.reshape(nb, C * R)).reshape(K, C, R)

    # Compute optimal alpha per basis, per pixel (unconstrained)
    alpha_all = (uTX[None, :, :] - uTB[:, None, None]) / u2   # (K, C, R)

    # Enforce alpha >= 0 by masking out negatives
    mask = (alpha_all >= 0.0)                                 # (K, C, R)
    Scores_masked = np.where(mask, Scores, -np.inf)           # invalid -> -inf so they lose

    # Top-k on masked scores
    idx_part    = np.argpartition(Scores_masked, -k, axis=0)[-k:, :, :]   # (k,C,R)
    scores_part = np.take_along_axis(Scores_masked, idx_part, axis=0)     # (k,C,R)
    order       = np.argsort(-scores_part, axis=0)                         # (k,C,R)

    best_basis = np.take_along_axis(idx_part,   order, axis=0).astype(np.int16)   # (k,C,R)
    score      = np.take_along_axis(scores_part, order, axis=0).astype(np.float32)# (k,C,R)
    alpha_star = np.take_along_axis(alpha_all,   best_basis, axis=0).astype(np.float32)

    # Mark selections that were actually invalid (alpha<0 at those indices)
    selected_valid = np.take_along_axis(mask, best_basis, axis=0)          # (k,C,R)
    invalid = ~selected_valid

    # Set invalid picks to sentinel values
    best_basis[invalid] = -1
    alpha_star[invalid] = np.nan
    score[invalid] = np.nan

    return best_basis, alpha_star, score

import numpy as np

def match_image_linear_bias_fast(X, bases, u, topk=1):
    """
    Solve: for each pixel x, find k, alpha s.t. x ≈ b_k + alpha * u
    by least squares (no normalization).

    X:      (nb, C, R)
    bases:  (K, nb)
    u:      (nb,)
    topk:   number of best matches to return

    Returns:
      best_basis: (topk, C, R) int16         # indices 0..K-1
      alpha_star: (topk, C, R) float32       # alpha in original units
      dist2:      (topk, C, R) float32       # minimal squared residuals
    """
    X = np.asarray(X, np.float32)
    B = np.asarray(bases, np.float32)
    u = np.asarray(u, np.float32)

    nb, C, R = X.shape
    K = B.shape[0]
    k = min(int(topk), K)

    # Precomputations
    u2      = float(np.dot(u, u))                       # scalar
    uTB     = (B * u[None, :]).sum(axis=1)              # (K,)
    Bnorm2  = (B * B).sum(axis=1)                       # (K,)
    Xnorm2  = (X * X).sum(axis=0)                       # (C,R)
    uTX     = np.tensordot(u, X, axes=([0],[0]))        # (C,R)

    # x^T b_k for all k, pixels
    dots = (B @ X.reshape(nb, C*R)).reshape(K, C, R)    # (K,C,R)

    # For each k, alpha_k*(i,j) = (u^T x - u^T b_k) / (u^T u)
    delta_u = uTX[None, :, :] - uTB[:, None, None]      # (K,C,R)
    alpha_k = delta_u / u2                               # (K,C,R)

    # Minimal LS distance for each k:
    # d_k^2 = ||x - b_k||^2 - ((u^T(x - b_k))^2)/||u||^2
    # where ||x - b_k||^2 = ||x||^2 + ||b_k||^2 - 2 x^T b_k
    base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots
    dist2 = base_diff2 - (delta_u * delta_u) / u2       # (K,C,R)

    # Top-k (smallest dist2)
    idx_part = np.argpartition(dist2, k-1, axis=0)[:k, :, :]         # (k,C,R)
    dist_part = np.take_along_axis(dist2, idx_part, axis=0)          # (k,C,R)
    order = np.argsort(dist_part, axis=0)                            # (k,C,R)

    best_basis = np.take_along_axis(idx_part, order, axis=0).astype(np.int16)
    best_dist2 = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)
    alpha_star = np.take_along_axis(alpha_k, best_basis, axis=0).astype(np.float32)

    return best_basis, alpha_star, best_dist2

# Next has been replaced by the one follows with option use_diff
# def match_image_linear_bias_nnalpha(X, bases, u, topk=1):
#     """
#     Non-negative alpha (alpha >= 0) version.
#     For each pixel x, find basis b_k and alpha >= 0 minimizing ||x - (b_k + alpha*u)||^2.

#     X:      (nb, C, R) float32
#     bases:  (K, nb)    float32
#     u:      (nb,)      float32
#     topk:   int        number of best matches to return

#     Returns:
#       best_basis: (topk, C, R) int16
#       alpha_star: (topk, C, R) float32      # alpha >= 0, original units
#       dist2:      (topk, C, R) float32      # minimal squared residuals
#     """
#     X = np.asarray(X, np.float32)
#     B = np.asarray(bases, np.float32)
#     u = np.asarray(u, np.float32)

#     nb, C, R = X.shape
#     K = B.shape[0]
#     k = min(int(topk), K)

#     # Precompute
#     u2      = np.dot(u, u)                          # scalar
#     if u2 <= 0:
#         raise ValueError("u must be non-zero")
#     uTB     = (B * u[None, :]).sum(axis=1)                 # (K,)
#     Bnorm2  = (B * B).sum(axis=1)                          # (K,)
#     Xnorm2  = (X * X).sum(axis=0)                          # (C,R)
#     uTX     = np.tensordot(u, X, axes=([0],[0]))           # (C,R)

#     # x^T b_k for all k, all pixels
#     dots = (B @ X.reshape(nb, C*R)).reshape(K, C, R)       # (K,C,R)

#     # base_diff2 = ||x - b_k||^2
#     base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - np.float32(2.0) * dots  # (K,C,R)

#     # delta_u = u^T(x - b_k)
#     delta_u = uTX[None, :, :] - uTB[:, None, None]         # (K,C,R)

#     # Non-negative alpha: clamp numerator
#     pos = np.maximum(delta_u, np.float32(0.0))                         # (K,C,R)

#     # alpha_k* and constrained minimal distance
#     alpha_k = pos / u2                                     # (K,C,R)  (>=0)
#     dist2   = base_diff2 - (pos * pos) / u2                # (K,C,R)

#     # Top-k (smallest residuals)
#     idx_part  = np.argpartition(dist2, k-1, axis=0)[:k, :, :]   # (k,C,R)
#     dist_part = np.take_along_axis(dist2, idx_part, axis=0)     # (k,C,R)
#     order     = np.argsort(dist_part, axis=0)                   # (k,C,R)

#     best_basis = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
#     best_dist2 = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)
#     alpha_star = np.take_along_axis(alpha_k,  best_basis, axis=0).astype(np.float32)

#     return best_basis, alpha_star, best_dist2

import numpy as np

def match_image_linear_bias_nnalpha(X, bases, u, topk=1, use_diff=False, eps=1e-12):
    """
    Non-negative alpha (alpha >= 0) version.

    If use_diff == False:
        For each pixel x, find b_k and alpha >= 0 minimizing
            ||x - (b_k + alpha * u)||^2

    If use_diff == True:
        Work in interband-difference space:

        Δx ≈ Δb_k + alpha * Δu

        If Δu is (almost) zero (flat u), bias is unobservable in diff space:
            we instead minimize ||Δx - Δb_k||^2 and return alpha_star = 0.

    Parameters
    ----------
    X :      (nb, C, R) float32/64   image
    bases :  (K, nb)    float32/64   basis spectra
    u :      (nb,)      float32/64   bias template
    topk :   int        number of best matches to return
    use_diff : bool     compare interband differences if True
    eps :    float      small constant for numerical safety

    Returns
    -------
    best_basis : (topk, C, R) int16    # basis indices
    alpha_star : (topk, C, R) float32  # alpha >= 0 (0 if unobservable in diff space)
    dist2      : (topk, C, R) float32  # minimal squared residuals
    """
    X = np.asarray(X, np.float32)
    B = np.asarray(bases, np.float32)
    u = np.asarray(u, np.float32)

    nb, C, R = X.shape
    K = B.shape[0]
    if B.shape[1] != nb:
        raise ValueError("bases must have shape (K, nb) with nb == X.shape[0]")
    if u.shape[0] != nb:
        raise ValueError("u must have length nb == X.shape[0]")

    # ----- Optional: interband-difference mode -----
    if use_diff:
        if nb < 2:
            raise ValueError("Need at least 2 bands to use interband differences.")

        Xd = X[1:, :, :] - X[:-1, :, :]   # (nb-1, C, R)
        Bd = B[:, 1:] - B[:, :-1]         # (K, nb-1)
        ud = u[1:] - u[:-1]               # (nb-1,)

        nb_d = nb - 1

        # Check if Δu is (almost) zero => flat u in diff space
        u2_d = float(np.dot(ud, ud))
        if u2_d <= eps:
            # Bias is unobservable in diff space: just match Δx to Δb_k, alpha_star = 0
            # Compute ||Δx - Δb_k||^2 and take top-k
            Xnorm2 = (Xd * Xd).sum(axis=0)                # (C,R)
            Bnorm2 = (Bd * Bd).sum(axis=1)                # (K,)
            dots   = (Bd @ Xd.reshape(nb_d, C*R)).reshape(K, C, R)

            dist2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots  # (K,C,R)

            k = min(int(topk), K)
            idx_part  = np.argpartition(dist2, k-1, axis=0)[:k, :, :]        # (k,C,R)
            dist_part = np.take_along_axis(dist2, idx_part, axis=0)          # (k,C,R)
            order     = np.argsort(dist_part, axis=0)

            best_basis = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
            best_dist2 = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)

            alpha_star = np.zeros_like(best_dist2, dtype=np.float32)        # alpha = 0 (unidentifiable)

            return best_basis, alpha_star, best_dist2

        # Otherwise, use ΔX, ΔB, Δu in the NNLS formulation below
        X = Xd
        B = Bd
        u = ud
        nb = nb_d

    # ----- Standard NNLS with single template u (no diff or diff with non-flat ud) -----
    k = min(int(topk), K)

    u2      = float(np.dot(u, u))                          # scalar
    if u2 <= eps:
        raise ValueError("u must be non-zero (or non-flat if use_diff=True).")

    uTB     = (B * u[None, :]).sum(axis=1)                 # (K,)
    Bnorm2  = (B * B).sum(axis=1)                          # (K,)
    Xnorm2  = (X * X).sum(axis=0)                          # (C,R)
    uTX     = np.tensordot(u, X, axes=([0],[0]))           # (C,R)

    # x^T b_k for all k and all pixels
    dots = (B @ X.reshape(nb, C * R)).reshape(K, C, R)     # (K,C,R)

    # ||x - b_k||^2
    base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots  # (K,C,R)

    # delta_u = u^T(x - b_k)
    delta_u = uTX[None, :, :] - uTB[:, None, None]         # (K,C,R)

    # Non-negative alpha: clamp numerator
    pos = np.maximum(delta_u, 0.0)                         # (K,C,R)

    # α_k* and constrained minimal distance
    alpha_k = pos / u2                                     # (K,C,R)  (>=0)
    dist2   = base_diff2 - (pos * pos) / u2                # (K,C,R)

    # ----- Top-k selection -----
    idx_part  = np.argpartition(dist2, k-1, axis=0)[:k, :, :]       # (k,C,R)
    dist_part = np.take_along_axis(dist2, idx_part, axis=0)         # (k,C,R)
    order     = np.argsort(dist_part, axis=0)                        # (k,C,R)

    best_basis = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
    best_dist2 = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)
    alpha_star = np.take_along_axis(alpha_k,  best_basis, axis=0).astype(np.float32)

    return best_basis, alpha_star, best_dist2


#Example use
#basematch.py

"""
tile processing Core + tiled wrapper 
row, col order corrected to (nb, R, C) from above (nb, C, R)
"""
# def _match_block_linear_bias_nnalpha(X_blk, B, u, u2, uTB, Bnorm2, topk=1):
#     """
#     Inner core: NNLS alpha >= 0 on a single block.

#     X_blk : (nb, Rblk, Cblk)
#     B     : (K, nb)
#     u     : (nb,)
#     u2    : scalar = u^T u
#     uTB   : (K,)
#     Bnorm2: (K,)
#     topk  : int

#     Returns:
#       best_basis_blk: (topk, Rblk, Cblk)
#       alpha_blk     : (topk, Rblk, Cblk)
#       dist2_blk     : (topk, Rblk, Cblk)
#     """
#     nb, Rblk, Cblk = X_blk.shape
#     K = B.shape[0]
#     k = min(int(topk), K)

#     # Per-block stats
#     Xnorm2 = (X_blk * X_blk).sum(axis=0)                # (Rblk,Cblk)
#     uTX    = np.tensordot(u, X_blk, axes=([0],[0]))     # (Rblk,Cblk)

#     # x^T b_k for all k & pixels in block
#     dots = (B @ X_blk.reshape(nb, Rblk * Cblk)).reshape(K, Rblk, Cblk)  # (K,Rblk,Cblk)

#     # ||x - b_k||^2
#     base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots  # (K,Rblk,Cblk)

#     # delta_u = u^T(x - b_k)
#     delta_u = uTX[None, :, :] - uTB[:, None, None]       # (K,Rblk,Cblk)

#     # α >= 0
#     pos  = np.maximum(delta_u, 0.0)                      # (K,Rblk,Cblk)
#     alpha_k = pos / u2                                   # (K,Rblk,Cblk)
#     dist2   = base_diff2 - (pos * pos) / u2              # (K,Rblk,Cblk)

#     # Top-k per pixel
#     idx_part  = np.argpartition(dist2, k-1, axis=0)[:k, :, :]     # (k,Rblk,Cblk)
#     dist_part = np.take_along_axis(dist2, idx_part, axis=0)       # (k,Rblk,Cblk)
#     order     = np.argsort(dist_part, axis=0)                      # (k,Rblk,Cblk)

#     best_basis_blk = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
#     dist2_blk      = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)
#     alpha_blk      = np.take_along_axis(alpha_k,  best_basis_blk, axis=0).astype(np.float32)

#     return best_basis_blk, alpha_blk, dist2_blk

# def match_image_linear_bias_nnalpha_tiled(
#     X, bases, u, topk=1,
#     tile_rows=512,   # number of rows per tile (y-direction)
#     tile_cols=None   # if None: use full cols; else tile in x-direction too
# ):
#     """
#     Memory-friendly NNLS (alpha >= 0) over a big image using tiling.

#     X:      (nb, R, C) float32/64
#     bases:  (K, nb)
#     u:      (nb,)
#     topk:   number of best matches per pixel
#     tile_cols: how many columns to process at once
#     tile_rows: how many rows to process at once (None = all rows)

#     Returns:
#       best_basis: (topk, R, C) int16
#       alpha_star: (topk, R, C) float32
#       dist2:      (topk, R, C) float32
#     """
#     X = np.asarray(X, np.float32)
#     B = np.asarray(bases, np.float32)
#     u = np.asarray(u, np.float32)

#     nb, R, C = X.shape
#     K = B.shape[0]

#     if B.shape[1] != nb:
#         raise ValueError("bases must have shape (K, nb) with nb == X.shape[0]")
#     if u.shape[0] != nb:
#         raise ValueError("u must have length nb == X.shape[0]")

#     # ---- Precompute basis-related quantities ONCE ----
#     u2      = float(np.dot(u, u))
#     if u2 <= 0:
#         raise ValueError("u must be non-zero")

#     uTB     = (B * u[None, :]).sum(axis=1)       # (K,)
#     Bnorm2  = (B * B).sum(axis=1)                # (K,)

#     k = min(int(topk), K)

#     # ---- Allocate outputs for full image ----
#     best_basis = np.empty((k, R, C), dtype=np.int16)
#     alpha_star = np.empty((k, R, C), dtype=np.float32)
#     dist2      = np.empty((k, R, C), dtype=np.float32)

#     if tile_cols is None:
#         tile_cols = C  # one stripe over cols

#     # ---- Loop over tiles ----
#     for r0 in range(0, R, tile_rows):
#         r1 = min(R, r0 + tile_rows)
#         for c0 in range(0, C, tile_cols):
#             c1 = min(C, c0 + tile_cols)

#             # Extract subscene
#             X_blk = X[:, r0:r1, c0:c1]   # (nb, Rblk, Cblk)

#             # Run block solver
#             bb_blk, a_blk, d2_blk = _match_block_linear_bias_nnalpha(
#                 X_blk, B, u, u2, uTB, Bnorm2, topk=k
#             )

#             # Store back into full maps
#             best_basis[:, r0:r1, c0:c1] = bb_blk
#             alpha_star[:, r0:r1, c0:c1] = a_blk
#             dist2[:, r0:r1,      c0:c1] = d2_blk
#             print(f'tile(i,j)=({r0},{c0}) has been processed')
#     return best_basis, alpha_star, dist2

def _match_block_linear_bias_nnalpha(X_blk, B, u, u2, uTB, Bnorm2, topk=1):
    """
    Inner core: NNLS alpha >= 0 on a single block.
    X_blk : (nb, Rblk, Cblk)
    B     : (K, nb)
    u     : (nb,)          OR  (nb, Rblk, Cblk)   pixelwise
    u2    : scalar         OR  (Rblk, Cblk)        pixelwise = u^T u per pixel
    uTB   : (K,)           OR  (K, Rblk, Cblk)     pixelwise
    Bnorm2: (K,)
    topk  : int
    Returns:
      best_basis_blk: (topk, Rblk, Cblk)
      alpha_blk     : (topk, Rblk, Cblk)
      dist2_blk     : (topk, Rblk, Cblk)
    """
    nb, Rblk, Cblk = X_blk.shape
    K = B.shape[0]
    k = min(int(topk), K)

    # ---- Per-block stats (unchanged) ----
    Xnorm2 = (X_blk * X_blk).sum(axis=0)                          # (Rblk, Cblk)
    dots   = (B @ X_blk.reshape(nb, Rblk * Cblk)).reshape(K, Rblk, Cblk)  # (K, Rblk, Cblk)

    # x^T b_k for all k & pixels
    base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots  # (K, Rblk, Cblk)

    # ---- uTX: shape depends on whether u is global or pixelwise ----
    # global u (nb,)           → tensordot gives (Rblk, Cblk)  → broadcast as [None,:,:]
    # pixelwise u (nb,Rb,Cb)   → einsum gives    (Rblk, Cblk)  → broadcast as [None,:,:]
    pixelwise_u = (np.ndim(u) == 3)

    if pixelwise_u:
        uTX = np.einsum('nrc,nrc->rc', u, X_blk)                  # (Rblk, Cblk)
    else:
        uTX = np.tensordot(u, X_blk, axes=([0], [0]))             # (Rblk, Cblk)

    # ---- delta_u = u^T(x - b_k) ----
    # uTB shape: (K,) global  →  uTB[:,None,None] broadcasts to (K,Rblk,Cblk)
    # uTB shape: (K,Rblk,Cblk) pixelwise → already correct
    if pixelwise_u:
        delta_u = uTX[None, :, :] - uTB                           # (K, Rblk, Cblk)
    else:
        delta_u = uTX[None, :, :] - uTB[:, None, None]           # (K, Rblk, Cblk)

    # ---- α = max(delta_u, 0) / u2 ----
    # u2 shape: scalar global  →  divides directly
    # u2 shape: (Rblk,Cblk)   →  need [None,:,:] to broadcast over K
    pos = np.maximum(delta_u, 0.0)                                 # (K, Rblk, Cblk)

    if pixelwise_u:
        alpha_k = pos / u2[None, :, :]                            # (K, Rblk, Cblk)
        dist2   = base_diff2 - (pos * pos) / u2[None, :, :]      # (K, Rblk, Cblk)
    else:
        alpha_k = pos / u2                                         # (K, Rblk, Cblk)
        dist2   = base_diff2 - (pos * pos) / u2                   # (K, Rblk, Cblk)

    # ---- Top-k per pixel (unchanged) ----
    idx_part  = np.argpartition(dist2, k - 1, axis=0)[:k]        # (k, Rblk, Cblk)
    dist_part = np.take_along_axis(dist2,   idx_part, axis=0)    # (k, Rblk, Cblk)
    order     = np.argsort(dist_part, axis=0)                     # (k, Rblk, Cblk)

    best_basis_blk = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
    dist2_blk      = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)
    alpha_blk      = np.take_along_axis(alpha_k,   best_basis_blk.astype(np.intp), axis=0).astype(np.float32)

    return best_basis_blk, alpha_blk, dist2_blk

def match_image_linear_bias_nnalpha_tiled(
    X, bases, u, topk=1,
    tile_rows=512,
    tile_cols=None
):
    """
    Memory-friendly NNLS (alpha >= 0) over a big image using tiling.
    X:      (nb, R, C) float32/64
    bases:  (K, nb)
    u:      (nb,) global bias  OR  (nb, R, C) pixelwise bias
    topk:   number of best matches per pixel
    tile_cols: how many columns to process at once
    tile_rows: how many rows to process at once
    Returns:
      best_basis: (topk, R, C) int16
      alpha_star: (topk, R, C) float32
      dist2:      (topk, R, C) float32
    """
    X = np.asarray(X, np.float32)
    B = np.asarray(bases, np.float32)
    u = np.asarray(u, np.float32)
    nb, R, C = X.shape
    K = B.shape[0]

    if B.shape[1] != nb:
        raise ValueError("bases must have shape (K, nb) with nb == X.shape[0]")

    # ---- Detect pixelwise vs global u ----
    if u.ndim == 1:
        pixelwise_u = False
        if u.shape[0] != nb:
            raise ValueError("u must have length nb == X.shape[0]")
        # Precompute basis-related quantities ONCE (global u)
        u2   = float(np.dot(u, u))
        if u2 <= 0:
            raise ValueError("u must be non-zero")
        uTB  = (B * u[None, :]).sum(axis=1)   # (K,)
        Bnorm2 = (B * B).sum(axis=1)           # (K,)

    elif u.ndim == 3:
        pixelwise_u = True
        if u.shape != (nb, R, C):
            raise ValueError(f"Pixelwise u must have shape (nb, R, C) == {(nb, R, C)}, got {u.shape}")
        # Bnorm2 is still global (depends only on B)
        Bnorm2 = (B * B).sum(axis=1)           # (K,)
        # u2 and uTB will be computed per tile below

    else:
        raise ValueError(f"u must be 1-D (nb,) or 3-D (nb, R, C), got shape {u.shape}")

    k = min(int(topk), K)

    # ---- Allocate outputs ----
    best_basis = np.empty((k, R, C), dtype=np.int16)
    alpha_star = np.empty((k, R, C), dtype=np.float32)
    dist2      = np.empty((k, R, C), dtype=np.float32)

    if tile_cols is None:
        tile_cols = C

    # ---- Loop over tiles ----
    for r0 in range(0, R, tile_rows):
        r1 = min(R, r0 + tile_rows)
        for c0 in range(0, C, tile_cols):
            c1 = min(C, c0 + tile_cols)

            X_blk = X[:, r0:r1, c0:c1]           # (nb, Rblk, Cblk)

            if pixelwise_u:
                u_blk = u[:, r0:r1, c0:c1]        # (nb, Rblk, Cblk)
                # u2:  (Rblk, Cblk)
                u2_blk  = (u_blk * u_blk).sum(axis=0)
                # uTB: (K, Rblk, Cblk)
                uTB_blk = np.tensordot(B, u_blk, axes=([1], [0]))

                bb_blk, a_blk, d2_blk = _match_block_linear_bias_nnalpha(
                    X_blk, B, u_blk, u2_blk, uTB_blk, Bnorm2, topk=k
                )
            else:
                bb_blk, a_blk, d2_blk = _match_block_linear_bias_nnalpha(
                    X_blk, B, u, u2, uTB, Bnorm2, topk=k
                )

            best_basis[:, r0:r1, c0:c1] = bb_blk
            alpha_star[:, r0:r1, c0:c1] = a_blk
            dist2[:, r0:r1,      c0:c1] = d2_blk
            print(f'tile(i,j)=({r0},{c0}) has been processed')

    return best_basis, alpha_star, dist2

def _match_block_linear_bias_fast(X_blk, B, u, u2, uTB, Bnorm2, topk=1):
    """
    Inner core: unconstrained alpha (alpha in R) on a single block.

    Model: x ≈ b_k + alpha * u, alpha can be negative.

    X_blk : (nb, Rblk, Cblk)
    B     : (K, nb)
    u     : (nb,)
    u2    : scalar = u^T u
    uTB   : (K,)
    Bnorm2: (K,)
    topk  : int

    Returns:
      best_basis_blk: (topk, Rblk, Cblk)
      alpha_blk     : (topk, Rblk, Cblk)
      dist2_blk     : (topk, Rblk, Cblk)
    """
    nb, Rblk, Cblk = X_blk.shape
    K = B.shape[0]
    k = min(int(topk), K)

    # Per-block stats
    Xnorm2 = (X_blk * X_blk).sum(axis=0)                # (Rblk,Cblk)
    uTX    = np.tensordot(u, X_blk, axes=([0],[0]))     # (Rblk,Cblk)

    # x^T b_k for all k & pixels in block
    dots = (B @ X_blk.reshape(nb, Rblk * Cblk)).reshape(K, Rblk, Cblk)  # (K,Rblk,Cblk)

    # ||x - b_k||^2
    base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots  # (K,Rblk,Cblk)

    # delta_u = u^T(x - b_k)
    delta_u = uTX[None, :, :] - uTB[:, None, None]       # (K,Rblk,Cblk)

    # Unconstrained alpha (can be negative)
    alpha_k = delta_u / u2                               # (K,Rblk,Cblk)

    # Minimal LS distance:
    # d_k^2 = ||x - b_k||^2 - ( (u^T(x-b_k))^2 / ||u||^2 )
    dist2   = base_diff2 - (delta_u * delta_u) / u2      # (K,Rblk,Cblk)

    # Top-k per pixel
    idx_part  = np.argpartition(dist2, k-1, axis=0)[:k, :, :]     # (k,Rblk,Cblk)
    dist_part = np.take_along_axis(dist2, idx_part, axis=0)       # (k,Rblk,Cblk)
    order     = np.argsort(dist_part, axis=0)                     # (k,Rblk,Cblk)

    best_basis_blk = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
    dist2_blk      = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)
    alpha_blk      = np.take_along_axis(alpha_k,  best_basis_blk, axis=0).astype(np.float32)

    return best_basis_blk, alpha_blk, dist2_blk

def match_image_linear_bias_fast_tiled(
    X, bases, u, topk=1,
    tile_rows=512,   # number of rows per tile (y-direction)
    tile_cols=None   # if None: use full cols; else tile in x-direction too
):
    """
    Memory-friendly version of match_image_linear_bias_fast
    using tiling over a big image.

    Model: x ≈ b_k + alpha * u, alpha ∈ R (unconstrained).

    X:      (nb, R, C) float32/64
    bases:  (K, nb)
    u:      (nb,)
    topk:   number of best matches per pixel
    tile_rows: how many rows to process at once
    tile_cols: how many columns to process at once (None = all columns)

    Returns:
      best_basis: (topk, R, C) int16
      alpha_star: (topk, R, C) float32
      dist2:      (topk, R, C) float32
    """
    X = np.asarray(X, np.float32)
    B = np.asarray(bases, np.float32)
    u = np.asarray(u, np.float32)

    nb, R, C = X.shape
    K = B.shape[0]

    if B.shape[1] != nb:
        raise ValueError("bases must have shape (K, nb) with nb == X.shape[0]")
    if u.shape[0] != nb:
        raise ValueError("u must have length nb == X.shape[0]")

    # ---- Precompute basis-related quantities ONCE ----
    u2      = float(np.dot(u, u))
    if u2 <= 0:
        raise ValueError("u must be non-zero")

    uTB     = (B * u[None, :]).sum(axis=1)       # (K,)
    Bnorm2  = (B * B).sum(axis=1)                # (K,)

    k = min(int(topk), K)

    # ---- Allocate outputs for full image ----
    best_basis = np.empty((k, R, C), dtype=np.int16)
    alpha_star = np.empty((k, R, C), dtype=np.float32)
    dist2      = np.empty((k, R, C), dtype=np.float32)

    if tile_cols is None:
        tile_cols = C  # one stripe over columns

    # ---- Loop over tiles ----
    for r0 in range(0, R, tile_rows):
        r1 = min(R, r0 + tile_rows)
        for c0 in range(0, C, tile_cols):
            c1 = min(C, c0 + tile_cols)

            # Extract subscene
            X_blk = X[:, r0:r1, c0:c1]   # (nb, Rblk, Cblk)

            # Run block solver
            bb_blk, a_blk, d2_blk = _match_block_linear_bias_fast(
                X_blk, B, u, u2, uTB, Bnorm2, topk=k
            )

            # Store back into full maps
            best_basis[:, r0:r1, c0:c1] = bb_blk
            alpha_star[:, r0:r1, c0:c1] = a_blk
            dist2[:,      r0:r1, c0:c1] = d2_blk

            print(f'tile(r,c)=({r0},{c0}) has been processed')

    return best_basis, alpha_star, dist2

