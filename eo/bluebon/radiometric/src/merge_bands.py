#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RGBN 중심 정합 결과를 밴드 순서 0~7 로 하나의 멀티밴드 TIFF 로 병합.
  band 순서: 0=PAN, 1=Blue, 2=Green, 3=Red, 4=RE1, 5=RE2, 6=RE3, 7=NIR
  T(평행이동)  -> obs260616_reg_rgbn_8band.tiff
  J(지터보정)  -> obs260616_regjit_rgbn_8band.tiff
출력 shape = (8, H, W) float32 (rasterio 에서 8밴드로 읽힘).
"""
import os
import sys
import argparse
import numpy as np
import tifffile

TEST_DIR = "/mnt/e/bkchoi/prep/data/correction_ref_260606/test_260616"
# (index, 파일 basename prefix)  — 0~7 순서
BAND_FILES = [
    (0, "PAN"), (1, "MS1"), (2, "MS2"), (3, "MS3"),
    (4, "MS4"), (5, "MS5"), (6, "MS6"), (7, "MS7"),
]


def merge(kind, out_name, var):
    """kind: 'reg'(T) or 'regjit'(J).  var: 파일 변형 접미사 (예: '_rgbn', '_rgbn_rot')."""
    arrs = []
    shp = None
    for idx, pref in BAND_FILES:
        p = os.path.join(TEST_DIR, f"{pref}_obs_{kind}{var}.tiff")
        a = tifffile.imread(p).astype(np.float32)
        if shp is None:
            shp = a.shape
        elif a.shape != shp:
            raise SystemExit(f"shape mismatch: {p} {a.shape} != {shp}")
        arrs.append(a)
        print(f"  band{idx} {pref:4s} <- {os.path.basename(p)}  {a.shape}")
    stack = np.stack(arrs, axis=0)                     # (8, H, W)
    out = os.path.join(TEST_DIR, out_name)
    tifffile.imwrite(out, stack, photometric="minisblack", planarconfig="separate")
    print(f"  -> wrote {out}  shape={stack.shape} dtype={stack.dtype}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--var", default="_rgbn", help="변형 접미사 (예: _rgbn, _rgbn_rot)")
    args = ap.parse_args()
    var = args.var
    print("[T] translation merge:")
    merge("reg", f"obs260616_reg{var}_8band.tiff", var)
    print("[J] jitter merge:")
    merge("regjit", f"obs260616_regjit{var}_8band.tiff", var)
    print("DONE. band order 0..7 = PAN,Blue,Green,Red,RE1,RE2,RE3,NIR")


if __name__ == "__main__":
    main()
