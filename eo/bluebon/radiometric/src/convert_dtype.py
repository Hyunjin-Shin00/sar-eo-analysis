#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""최종 결과물 2종(회전보정 RGBN 병합 8밴드 T/J)을 float32 / uint16 로 각각 저장.
uint16: 값이 이미 DN 범위(213~3902)라 스케일 없이 round + clip[0,65535] (DN 보존)."""
import os
import numpy as np
import tifffile

TEST = "/mnt/e/bkchoi/prep/data/correction_ref_260606/test_260616"
SRCS = [
    ("obs260616_reg_rgbn_rot_8band.tiff",    "reg(T, 평행이동)"),
    ("obs260616_regjit_rgbn_rot_8band.tiff", "regjit(J, 지터+회전)"),
]

for fn, desc in SRCS:
    a = tifffile.imread(os.path.join(TEST, fn)).astype(np.float32)
    base = fn[:-5]  # strip .tiff
    # float32
    f32 = os.path.join(TEST, base + "_f32.tiff")
    tifffile.imwrite(f32, a, photometric="minisblack", planarconfig="separate")
    # uint16 (round + clip, 스케일 없음)
    u16arr = np.clip(np.rint(np.nan_to_num(a, nan=0.0)), 0, 65535).astype(np.uint16)
    u16 = os.path.join(TEST, base + "_u16.tiff")
    tifffile.imwrite(u16, u16arr, photometric="minisblack", planarconfig="separate")
    print("%-22s: f32 min=%.1f max=%.1f | u16 min=%d max=%d" % (
        desc, float(a.min()), float(a.max()), int(u16arr.min()), int(u16arr.max())))
    print("   ->", os.path.basename(f32))
    print("   ->", os.path.basename(u16))
print("DONE. band order 0..7 = PAN,Blue,Green,Red,RE1,RE2,RE3,NIR")
