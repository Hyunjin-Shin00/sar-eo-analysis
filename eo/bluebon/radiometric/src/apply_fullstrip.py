#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dark/PRNU 참조를 260616_193632 전체 스트립(16000x4096)에 적용해 보정 TIFF 저장.
공식: corr = (raw - dark_ref[col]) * prnu_coef[col]   (float32, 클립 없음)
출력: test_260616/MS{n}_obs_corrected_full.tiff
"""
import os
import numpy as np
import tifffile

OUT_DIR  = "/mnt/e/bkchoi/prep/data/correction_ref_260606"
TEST_DIR = os.path.join(OUT_DIR, "test_260616")
OBS_DIR  = "/mnt/e/bkchoi/prep/data/260616_193632"
OBS_STEM = "260616_193632"
BANDS    = [1, 2, 3, 4, 5, 6, 7]
BAND_NAME = {1: "Blue", 2: "Green", 3: "Red", 4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}


def main():
    os.makedirs(TEST_DIR, exist_ok=True)
    for n in BANDS:
        dark = tifffile.imread(os.path.join(OUT_DIR, f"MS{n}_dark_ref.tiff")).astype(np.float32).ravel()
        prnu = np.loadtxt(os.path.join(OUT_DIR, f"MS{n}_residul_prnu_coef.dat")).astype(np.float32)
        raw  = tifffile.imread(os.path.join(OBS_DIR, f"{OBS_STEM}_{n}_gray.tiff")).astype(np.float32)
        corr = (raw - dark[None, :]) * prnu[None, :]
        corr = np.fliplr(corr)                      # 좌우(across-track) flip
        out = os.path.join(TEST_DIR, f"MS{n}_obs_corrected_full.tiff")
        tifffile.imwrite(out, corr.astype(np.float32))
        print("MS%d %-5s -> %s  min=%.1f max=%.1f mean=%.1f" % (
            n, BAND_NAME[n], os.path.basename(out), corr.min(), corr.max(), corr.mean()), flush=True)
    print("\nDONE.", TEST_DIR)


if __name__ == "__main__":
    main()
