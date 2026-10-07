#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Nov 12 13:47:14 2025

@author: yp
"""

import numpy as np

def match_image_two_templates_nnalpha_topk(X, bases, U, topk=3, ridge=0.0):
    """
    NNLS with two bias templates (alpha >= 0 elementwise).
    Per pixel, solve:  min_{k, alpha>=0} || x - (b_k + U alpha) ||^2
    Accepts U with shape (2, nb)  <-- NOTE: two rows, nb columns.

    X:      (nb, C, R)   float32/64
    bases:  (K, nb)      float32/64
    U:      (2, nb) or ((nb,2)) or sequence [u1, u2] where each u_i has length nb
    topk:   int
    ridge:  float   (optional Tikhonov on G = U^T U)

    Returns:
      best_basis: (topk, C, R)        int16
      alpha_star:(topk, 2, C, R)      float32   # [alpha1, alpha2] >= 0
      dist2:     (topk, C, R)         float32   # minimal squared residuals
    """
    X = np.asarray(X, np.float32)
    B = np.asarray(bases, np.float32)

    # ---- Handle U in (2, nb) ----
    if isinstance(U, (tuple, list)):
        U = np.stack([np.asarray(u, np.float32) for u in U], axis=0)  # (2, nb) expected
    U = np.asarray(U, np.float32)
    if U.ndim != 2:
        raise ValueError("U must be 2D with shape (2, nb) or (nb, 2)")

    nb, C, R = X.shape
    # If U is (2, nb), transpose to (nb, 2). If already (nb,2), leave it.
    if U.shape == (2, nb):
        U = U.T  # -> (nb, 2)
    elif U.shape != (nb, 2):
        raise ValueError(f"U must have shape (2, nb) or (nb, 2); got {U.shape}")

    K = B.shape[0]
    if B.shape[1] != nb:
        raise ValueError("bases must have shape (K, nb)")
    k = min(int(topk), K)

    # ---- Precompute Gram and invGram (2x2) ----
    u1 = U[:, 0]; u2 = U[:, 1]
    a = float(np.dot(u1, u1))   # u1^T u1
    b = float(np.dot(u1, u2))   # u1^T u2
    c = float(np.dot(u2, u2))   # u2^T u2

    G = np.array([[a, b], [b, c]], dtype=np.float32)
    if ridge > 0:
        G = G + ridge * np.eye(2, dtype=np.float32)
        a, b, c = float(G[0,0]), float(G[0,1]), float(G[1,1])

    det = a*c - b*b
    if det <= 0:
        raise ValueError("U's columns are (near) collinear; pick distinct templates or add ridge.")

    invG = (1.0/det) * np.array([[ c, -b],
                                 [-b,  a]], dtype=np.float32)

    # ---- Sufficient stats ----
    Xnorm2 = (X*X).sum(axis=0)                           # (C,R)
    Bnorm2 = (B*B).sum(axis=1)                           # (K,)
    dots   = (B @ X.reshape(nb, C*R)).reshape(K, C, R)   # (K,C,R)
    base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots  # (K,C,R)

    u1TX = np.tensordot(u1, X, axes=([0],[0]))          # (C,R)
    u2TX = np.tensordot(u2, X, axes=([0],[0]))          # (C,R)
    u1TB = (B * u1[None, :]).sum(axis=1)                # (K,)
    u2TB = (B * u2[None, :]).sum(axis=1)                # (K,)
    s1   = u1TX[None, :, :] - u1TB[:, None, None]       # (K,C,R)
    s2   = u2TX[None, :, :] - u2TB[:, None, None]       # (K,C,R)

    # ---- Candidate active sets ----
    # {}: alpha=[0,0]
    dist2_0 = base_diff2

    # {1}: alpha1 = max(s1/a, 0), alpha2=0
    a_safe  = max(a, 1e-12)
    alpha1_1 = np.maximum(s1, 0.0) / a_safe
    red_1    = (np.maximum(s1, 0.0)**2) / a_safe
    dist2_1  = base_diff2 - red_1

    # {2}: alpha2 = max(s2/c, 0), alpha1=0
    c_safe  = max(c, 1e-12)
    alpha2_2 = np.maximum(s2, 0.0) / c_safe
    red_2    = (np.maximum(s2, 0.0)**2) / c_safe
    dist2_2  = base_diff2 - red_2

    # {1,2}: unconstrained solution, then require both >=0
    alpha1_f = ( invG[0,0]*s1 + invG[0,1]*s2 )
    alpha2_f = ( invG[1,0]*s1 + invG[1,1]*s2 )
    mask_f   = (alpha1_f >= 0.0) & (alpha2_f >= 0.0)
    red_f    = (c*s1*s1 - 2*b*s1*s2 + a*s2*s2) / max(det, 1e-12)
    dist2_f  = np.where(mask_f, base_diff2 - red_f, np.inf)

    # ---- Pick best active set per (k, pixel) ----
    dist2_k = dist2_f.copy()
    a1_best = np.where(mask_f, alpha1_f, 0.0)
    a2_best = np.where(mask_f, alpha2_f, 0.0)

    better = dist2_1 < dist2_k
    dist2_k[better] = dist2_1[better]
    a1_best[better] = alpha1_1[better]
    a2_best[better] = 0.0

    better = dist2_2 < dist2_k
    dist2_k[better] = dist2_2[better]
    a1_best[better] = 0.0
    a2_best[better] = alpha2_2[better]

    better = dist2_0 < dist2_k
    dist2_k[better] = dist2_0[better]
    a1_best[better] = 0.0
    a2_best[better] = 0.0

    # ---- Top-k over bases (smallest residual) ----
    idx_part  = np.argpartition(dist2_k, k-1, axis=0)[:k, :, :]           # (k,C,R)
    dist_part = np.take_along_axis(dist2_k, idx_part, axis=0)             # (k,C,R)
    order     = np.argsort(dist_part, axis=0)                             # (k,C,R)

    best_basis = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
    best_dist2 = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)

    a1_sel = np.take_along_axis(a1_best, best_basis, axis=0)
    a2_sel = np.take_along_axis(a2_best, best_basis, axis=0)
    alpha_star = np.stack([a1_sel, a2_sel], axis=1).astype(np.float32)    # (k,2,C,R)

    return best_basis, alpha_star, best_dist2

