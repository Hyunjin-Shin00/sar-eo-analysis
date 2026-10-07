#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flat 모드 PRNU 계수 생성 (넓은 across-track vignetting 까지 제거).
  gain = mean(sig) / sig          (창 없음 = full-width flat-field)
  sig  = median(Libya, 라인축) - dark_ref
dark_ref 는 기존 생성분 재사용. 출력은 residual 과 구분되는 별도 파일:
  {rn}_prnu_flat_coef.dat  (헤더 + 4096 float, 곱셈)
  {rn}_prnu_flat.tiff      (float32 1x4096)
밴드: 0=PAN..7=NIR (rn = PAN or MS{n})
"""
import os
import numpy as np
import tifffile
from make_correction_ref import save_vec_tiff, save_dat, LIB_DIR, LIB_STEM, OUT_DIR

BAND_NAME = {0: "PAN", 1: "Blue", 2: "Green", 3: "Red", 4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
def ref_name(n): return "PAN" if n == 0 else f"MS{n}"

for n in range(8):
    rn = ref_name(n)
    dark = tifffile.imread(os.path.join(OUT_DIR, f"{rn}_dark_ref.tiff")).astype(np.float64).ravel()
    lib  = np.median(tifffile.imread(os.path.join(LIB_DIR, f"{LIB_STEM}_{n}_gray.tiff")).astype(np.float64), axis=0)
    sig  = lib - dark
    gain = sig.mean() / sig                      # full flat-field (평탄화, 창 없음)
    save_vec_tiff(os.path.join(OUT_DIR, f"{rn}_prnu_flat.tiff"), gain)
    save_dat(os.path.join(OUT_DIR, f"{rn}_prnu_flat_coef.dat"), gain,
             header=f"# {rn} FLAT PRNU (full-width, vignetting 포함) Coefficient")
    print("%-4s %-5s gain mean=%.4f std=%.3f%% range[%.3f,%.3f]  (vignetting까지 평탄화)" % (
        rn, BAND_NAME[n], gain.mean(), gain.std() * 100, gain.min(), gain.max()))
print("DONE ->", OUT_DIR)
