#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PAN(band 0) dark/PRNU 참조 생성 — make_correction_ref.py 와 동일 방법 재사용.
   dark: 260606_190315_0 (밤 원양),  PRNU: 260607_094318_0 (Libya-4).
   출력: PAN_dark_ref.tiff/.dat, PAN_prnu_ref.tiff, PAN_residul_prnu_coef.dat"""
import os
import numpy as np
import tifffile
from make_correction_ref import (build_dark_ref, movavg_reflect, save_vec_tiff, save_dat,
                                  LIB_DIR, LIB_STEM, OUT_DIR, PRNU_WINDOW)

n = 0
dark_ref = build_dark_ref(n)                                    # 다중 세션 평균
lib_col  = np.median(tifffile.imread(os.path.join(LIB_DIR, f"{LIB_STEM}_{n}_gray.tiff")).astype(np.float64), axis=0)

sig    = lib_col - dark_ref
smooth = movavg_reflect(sig, PRNU_WINDOW)
prnu   = smooth / sig
prnu   = prnu / prnu.mean()

save_vec_tiff(os.path.join(OUT_DIR, "PAN_dark_ref.tiff"), dark_ref)
save_dat(os.path.join(OUT_DIR, "PAN_dark_ref.dat"), dark_ref)
save_vec_tiff(os.path.join(OUT_DIR, "PAN_prnu_ref.tiff"), prnu)
save_dat(os.path.join(OUT_DIR, "PAN_residul_prnu_coef.dat"), prnu,
         header="# PAN residual PRNU Coefficient for Radiance")

hf_b = ((sig - smooth) / smooth).std() * 100
corr = sig * prnu
hf_a = ((corr - movavg_reflect(corr, PRNU_WINDOW)) / movavg_reflect(corr, PRNU_WINDOW)).std() * 100
print("PAN dark_mean=%.2f  lib_mean=%.1f  prnu_std=%.4f%%  hf %.3f%%->%.3f%%  nan=%d  sig_min=%.1f" % (
    dark_ref.mean(), lib_col.mean(), prnu.std() * 100, hf_b, hf_a,
    int(np.isnan(prnu).sum() + np.isinf(prnu).sum()), sig.min()))
print("saved PAN_dark_ref.tiff/.dat, PAN_prnu_ref.tiff, PAN_residul_prnu_coef.dat ->", OUT_DIR)
