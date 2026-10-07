#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 12:18:22 2026

@author: yp
"""

import numpy as np

def _match_block_linear_bias_nnalpha(X_blk, B, u, u2, uTB, Bnorm2, topk=1):
    """
    Modified Inner core: Model X = (1-alpha)*B + alpha*u, alpha >= 0
    """
    nb, Rblk, Cblk = X_blk.shape
    K = B.shape[0]
    k = min(int(topk), K)

    # 1. Standard stats
    Xnorm2 = (X_blk * X_blk).sum(axis=0)                                  # (Rblk, Cblk)
    dots   = (B @ X_blk.reshape(nb, Rblk * Cblk)).reshape(K, Rblk, Cblk)  # X^T B: (K, Rblk, Cblk)

    # 2. Compute ||X - B||^2 (The "Base" error if alpha=0)
    # base_diff2 = X^2 + B^2 - 2XB
    base_diff2 = Xnorm2[None, :, :] + Bnorm2[:, None, None] - 2.0 * dots  # (K, Rblk, Cblk)

    # 3. Compute u^T X
    pixelwise_u = (np.ndim(u) == 3)
    if pixelwise_u:
        uTX = np.einsum('nrc,nrc->rc', u, X_blk)                          # (Rblk, Cblk)
    else:
        uTX = np.tensordot(u, X_blk, axes=([0], [0]))                     # (Rblk, Cblk)

    # 4. Compute the Numerator: (X - B)^T (u - B)
    # Expanded: uTX - XTB - uTB + Bnorm2
    if pixelwise_u:
        # uTB is (K, Rblk, Cblk), Bnorm2 is (K,)
        num = uTX[None, :, :] - dots - uTB + Bnorm2[:, None, None]
    else:
        # uTB is (K,), Bnorm2 is (K,)
        num = uTX[None, :, :] - dots - uTB[:, None, None] + Bnorm2[:, None, None]

    # 5. Compute the Denominator: ||u - B||^2
    # Expanded: u^2 + B^2 - 2uTB
    if pixelwise_u:
        Vnorm2 = u2[None, :, :] + Bnorm2[:, None, None] - 2.0 * uTB       # (K, Rblk, Cblk)
    else:
        Vnorm2 = u2 + Bnorm2[:, None, None] - 2.0 * uTB[:, None, None]    # (K, Rblk, Cblk)

    # Avoid division by zero if u == B
    Vnorm2 = np.maximum(Vnorm2, 1e-12)

    # 6. Solve for alpha and final distance
    pos = np.maximum(num, 0.0)
    alpha_k = pos / Vnorm2
    dist2   = base_diff2 - (pos * pos) / Vnorm2

    # ---- Top-k per pixel ----
    idx_part  = np.argpartition(dist2, k - 1, axis=0)[:k]
    dist_part = np.take_along_axis(dist2, idx_part, axis=0)
    order     = np.argsort(dist_part, axis=0)

    best_basis_blk = np.take_along_axis(idx_part,  order, axis=0).astype(np.int16)
    dist2_blk      = np.take_along_axis(dist_part, order, axis=0).astype(np.float32)
    alpha_blk      = np.take_along_axis(alpha_k,   best_basis_blk.astype(np.intp), axis=0).astype(np.float32)

    return best_basis_blk, alpha_blk, dist2_blk

def match_image_linear_bias_nnalpha_tiled(
    X, bases, u, topk=1, tile_rows=512, tile_cols=None
):
    """
    Memory-friendly tiled wrapper for X = (1-alpha)B + alpha*u
    """
    X = np.asarray(X, np.float32)
    B = np.asarray(bases, np.float32)
    u = np.asarray(u, np.float32)
    nb, R, C = X.shape
    K = B.shape[0]

    # Precompute basis-related global quantities
    Bnorm2 = (B * B).sum(axis=1)  # (K,)

    if u.ndim == 1:
        pixelwise_u = False
        u2  = float(np.dot(u, u))
        uTB = (B * u[None, :]).sum(axis=1) # (K,)
    else:
        pixelwise_u = True
        # u2 and uTB computed per tile

    k = min(int(topk), K)
    best_basis = np.empty((k, R, C), dtype=np.int16)
    alpha_star = np.empty((k, R, C), dtype=np.float32)
    dist2      = np.empty((k, R, C), dtype=np.float32)

    if tile_cols is None: tile_cols = C

    for r0 in range(0, R, tile_rows):
        r1 = min(R, r0 + tile_rows)
        for c0 in range(0, C, tile_cols):
            c1 = min(C, c0 + tile_cols)
            X_blk = X[:, r0:r1, c0:c1]

            if pixelwise_u:
                u_blk = u[:, r0:r1, c0:c1]
                u2_blk = (u_blk * u_blk).sum(axis=0)
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
            dist2[:, r0:r1, c0:c1] = d2_blk
            print(f'tile(i,j)=({r0},{c0}) has been processed')

    return best_basis, alpha_star, dist2