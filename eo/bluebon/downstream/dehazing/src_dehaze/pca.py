#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Nov  8 22:59:43 2025

@author: yp
"""

import numpy as np
from typing import Optional, Dict

def pca_svd(X: np.ndarray, n_components: Optional[int] = None, center: bool = True) -> Dict[str, np.ndarray]:
    """
    PCA via SVD for small/mid datasets. Rows = samples, cols = features.

    Returns keys:
      mean_ : (d,)
      components_ : (d, k)  # columns are unit principal axes
      explained_variance_ : (k,)            # eigenvalues of covariance
      explained_variance_ratio_ : (k,)
      singular_values_ : (k,)
      scores_ : (n, k)      # X centered and projected onto PCs
    """
    X = np.asarray(X, dtype=float)
    n, d = X.shape
    if n_components is None:
        k = min(n, d)
    else:
        k = int(n_components)
        if not (1 <= k <= min(n, d)):
            raise ValueError(f"n_components must be in [1, {min(n, d)}]")

    mean_ = X.mean(axis=0) if center else np.zeros(d)
    Xc = X - mean_

    # Xc = U S Vt
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    V = Vt.T  # (d, d)

    components_ = V[:, :k]                # (d, k)
    singular_values_ = S[:k]              # (k,)
    # Eigenvalues of covariance = S^2 / (n-1)
    explained_variance_ = (singular_values_**2) / max(n - 1, 1)
    total_var = (S**2).sum() / max(n - 1, 1)
    explained_variance_ratio_ = explained_variance_ / (total_var + 1e-18)

    scores_ = Xc @ components_            # (n, k)

    return dict(
        mean_=mean_,
        components_=components_,
        explained_variance_=explained_variance_,
        explained_variance_ratio_=explained_variance_ratio_,
        singular_values_=singular_values_,
        scores_=scores_,
    )

def pca_project(X_new, fit):
    Xn = np.asarray(X_new, dtype=float)
    Xn = np.atleast_2d(Xn)                 # promote 1D -> (1, d)
    return (Xn - fit["mean_"]) @ fit["components_"]

def pca_reconstruct(scores: np.ndarray, fit: Dict[str, np.ndarray]) -> np.ndarray:
    """Reconstruct from scores (m, k) back to feature space (m, d)."""
    return scores @ fit["components_"].T + fit["mean_"]

import numpy as np
import matplotlib.pyplot as plt

def plot_pc_loadings(components: np.ndarray, pcs=None, title=None):
    """
    Plot multiple principal components' loadings on one graph.

    Parameters
    ----------
    components : array, shape (n_features, n_components)
        Columns are PCs (as returned by many PCA implementations).
    pcs : list[int] or None
        1-based PC indices to plot (e.g., [1,2,3]). If None, plots all.
    title : str or None
        Figure title.
    """
    n_features, n_components = components.shape
    x = np.arange(1, n_features + 1)  # x-axis: [1, 2, ..., d]

    if pcs is None:
        pcs = list(range(1, n_components + 1))

    plt.figure(figsize=(10, 5))
    for pc_idx in pcs:
        if not (1 <= pc_idx <= n_components):
            raise ValueError(f"pc index {pc_idx} out of range 1..{n_components}")
        v = components[:, pc_idx - 1]  # column = that PC’s loadings
        plt.plot(x, v, label=f"PC{pc_idx}")

    plt.axhline(0, linewidth=1)   # zero reference
    plt.xlabel("Feature index")
    plt.ylabel("Loading value")
    if title:
        plt.title(title)
    else:
        plt.title("Principal Component Loadings")
    plt.legend()
    plt.tight_layout()
    plt.show()


def project_one_pc_grid(
    X: np.ndarray,          # shape (d, nrow, ncols)
    res: Dict[str, np.ndarray],
    pc_index: int = 0,      # 0 -> PC1, 1 -> PC2, ...
    out_dtype=np.float32,
) -> np.ndarray:
    """
    Project a (d, nrow, ncols) stack onto a single PC.
    Returns an image of shape (nrow, ncols) with the PC score per pixel.
    """
    X = np.asarray(X, dtype=np.float64, order="C")
    d, nrow, ncols = X.shape

    mean = np.asarray(res["mean_"], dtype=np.float64)              # (d,)
    v = np.asarray(res["components_"][:, pc_index], np.float64)    # (d,)

    # Center per band and project: score(r,c) = (X[:,r,c] - mean) · v
    Xc = X - mean[:, None, None]                                   # (d, nrow, ncols)
    scores = np.tensordot(v, Xc, axes=(0, 0))                      # (nrow, ncols)

    return scores.astype(out_dtype, copy=False)


def project_k_pcs_grid(
    X: np.ndarray,          # shape (d, nrow, ncols)
    res: Dict[str, np.ndarray],
    k: Optional[int] = None,
    out_dtype=np.float32,
) -> np.ndarray:
    """
    Project a (d, nrow, ncols) stack onto the first k PCs.
    Returns an array of shape (k, nrow, ncols).
    """
    X = np.asarray(X, dtype=np.float64, order="C")
    d, nrow, ncols = X.shape

    mean = np.asarray(res["mean_"], dtype=np.float64)              # (d,)
    comps = np.asarray(res["components_"], np.float64)             # (d, k_all)

    if k is None:
        k = comps.shape[1]
    comps = comps[:, :k]                                           # (d, k)

    Xc = X - mean[:, None, None]                                   # (d, nrow, ncols)
    # For each pixel, scores = comps^T @ (d-vector). Vectorized with tensordot:
    scores = np.tensordot(comps.T, Xc, axes=(1, 0))                # (k, nrow, ncols)

    return scores.astype(out_dtype, copy=False)


def reconstruct_from_k_pcs_grid(
    scores: np.ndarray,     # shape (k, nrow, ncols)
    res: Dict[str, np.ndarray],
) -> np.ndarray:
    """
    Reconstruct the (d, nrow, ncols) stack from k PC score maps.
    """
    scores = np.asarray(scores, np.float64)
    k, nrow, ncols = scores.shape

    comps = np.asarray(res["components_"][:, :k], np.float64)      # (d, k)
    mean = np.asarray(res["mean_"], np.float64)                    # (d,)

    # reshape to (k, nrow*ncols), then back
    S = scores.reshape(k, -1)                                      # (k, npix)
    Xrec = (comps @ S).reshape(comps.shape[0], nrow, ncols)        # (d, nrow, ncols)
    Xrec += mean[:, None, None]

    return Xrec

# res = pca_svd(X_samples, n_components=k)  # from your earlier fit; components_: (d, k)
# pc1_map = project_one_pc_grid(X_grid, res, pc_index=0)         # (nrow, ncols)
# top3_maps = project_k_pcs_grid(X_grid, res, k=3)               # (3, nrow, ncols)

# # Reconstruct the stack using those top-3 PC maps
# Xrec = reconstruct_from_k_pcs_grid(top3_maps, res)             # (d, nrow, ncols)
import pcaX    
if __name__=="__main__":
    X0=pcaX.dataX()
    X=np.array(X0)#[:,[0,1,2,3,7,8,9]]
    res = pca_svd(X)
    
    PCs = res["components_"]                     # (d, 5)
    plot_pc_loadings(PCs, pcs=[1,2,3,4], title="Top-3 PC Loadings")
    scores = res["scores_"]                      # (n, 5)
    var_ratio = res["explained_variance_ratio_"] # (5,)
    
    # Decompose a single vector x into PC components (its coordinates in PC space)
    x = X[-1]
    x_scores = pca_project(x, res)  # (5,)

    x3 = pca_reconstruct(x_scores[:3][None, :], {
    **res, "components_": res["components_"][:, :3]
    })[0]