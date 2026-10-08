#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""across-track(좌/중/우) 잔차 진단: 회전(yaw)/keystone 성분 확인. (rgbn, anchor=Red, T버전)"""
import numpy as np, tifffile
from skimage.registration import phase_cross_correlation
from scipy.ndimage import gaussian_filter

TEST = "<WORK_ROOT>/prep/data/correction_ref_260606/test_260616"
def hp(x): x = x.astype(np.float64); return x - gaussian_filter(x, 3)

anc = hp(tifffile.imread(f"{TEST}/MS3_obs_reg_rgbn.tiff"))   # Red anchor
H, W = anc.shape
ny, nx = 10, 5
ys = np.linspace(0, H, ny + 1).astype(int)
xs = np.linspace(0, W, nx + 1).astype(int)
xcen = np.array([(xs[j] + xs[j + 1]) / 2 for j in range(nx)])
c0 = W / 2.0
gstd = anc.std()

for bname, fn in [("Blue", "MS1"), ("Green", "MS2"), ("NIR", "MS7"), ("RE3", "MS6")]:
    b = hp(tifffile.imread(f"{TEST}/{fn}_obs_reg_rgbn.tiff"))
    slopes, left_dy, right_dy = [], [], []
    for i in range(ny):
        dyj = np.full(nx, np.nan)
        for j in range(nx):
            at = anc[ys[i]:ys[i+1], xs[j]:xs[j+1]]
            bt = b[ys[i]:ys[i+1], xs[j]:xs[j+1]]
            if at.std() < gstd * 0.3:
                continue
            s, _, _ = phase_cross_correlation(at, bt, upsample_factor=10)
            if np.max(np.abs(s)) < 8:
                dyj[j] = s[0]
        m = ~np.isnan(dyj)
        if m.sum() >= 3:
            p = np.polyfit(xcen[m] - c0, dyj[m], 1)
            slopes.append(p[0]); left_dy.append(dyj[0]); right_dy.append(dyj[-1])
    theta = np.nanmean(slopes)
    print("%-5s vs Red: dy/dcol(rot) = %+.3e px/px => %+.4f deg | left dy %+.2f  right dy %+.2f  (L-R %+.2f)" % (
        bname, theta, np.degrees(np.arctan(theta)),
        np.nanmean(left_dy), np.nanmean(right_dy), np.nanmean(left_dy) - np.nanmean(right_dy)))
