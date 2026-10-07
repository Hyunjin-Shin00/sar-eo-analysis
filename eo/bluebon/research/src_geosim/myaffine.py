#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug 30 17:31:49 2025
@author: yp, chatgpt5
"""

import numpy as np

def affine_from_points(src_pts, dst_pts):
    """
    Compute transform from src_pts -> dst_pts.
    
    If len(src_pts)==2:  axis-aligned scale + translation (no rotation).
    If len(src_pts)>=3: full affine transform (rotation/skew allowed).
    
    src_pts, dst_pts: arrays of shape (N,2)
    Returns (A, b) such that dst ≈ A @ src + b
    """
    src_pts = np.asarray(src_pts, dtype=float)
    dst_pts = np.asarray(dst_pts, dtype=float)
    N = src_pts.shape[0]

    if N == 2:
        # --- No rotation: x/y scale + translation ---
        (i1, j1), (i2, j2) = src_pts
        (u1, v1), (u2, v2) = dst_pts

        if np.isclose(i2 - i1, 0) or np.isclose(j2 - j1, 0):
            raise ValueError("Need two distinct points with different i and j values")

        sx = (u2 - u1) / (i2 - i1)
        sy = (v2 - v1) / (j2 - j1)
        tx = u1 - sx * i1
        ty = v1 - sy * j1

        A = np.array([[sx, 0],
                      [0,  sy]])
        b = np.array([tx, ty])

        return A, b

    elif N >= 3:
        # --- Full affine ---
        # Build linear system
        M = np.zeros((2*N, 6))
        rhs = dst_pts.reshape(-1)
        for k in range(N):
            x, y = src_pts[k]
            M[2*k,   0:2] = [x, y]
            M[2*k,   2]   = 1
            M[2*k+1, 0:2] = [0, 0]
            M[2*k+1, 3:5] = [x, y]
            M[2*k+1, 5]   = 1
        # Solve least squares
        params, *_ = np.linalg.lstsq(M, rhs, rcond=None)
        a11, a12, tx, a21, a22, ty = params
        A = np.array([[a11, a12],
                      [a21, a22]])
        b = np.array([tx, ty])
        return A, b

    else:
        raise ValueError("Need at least 2 points")

def apply_affine(A, b, pts):
    pts = np.asarray(pts, dtype=float)
    return (A @ pts.T).T + b

if __name__=="__main__":
    # Case 1: 2 points (no rotation, only scale + translation)
    src2 = np.array([[0,0],[10,20]])
    dst2 = np.array([[100,200],[120,260]])
    A2, b2 = affine_from_points(src2, dst2)
    print("2-point A, b:\n", A2, b2)
    print("Mapped:", apply_affine(A2, b2, [[5,10]]))
    
    # Case 2: 4 points (full affine)
    src4 = np.array([[0,0],[1,0],[1,1],[0,1]])
    dst4 = np.array([[2,3],[3.2,3.1],[3.3,4.1],[2.1,4.0]])
    A4, b4 = affine_from_points(src4, dst4)
    print("4-point A, b:\n", A4, b4)
    print("Mapped:", apply_affine(A4, b4, [[0.5,0.5]]))



    