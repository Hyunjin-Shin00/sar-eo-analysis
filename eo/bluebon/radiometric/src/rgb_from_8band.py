#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8밴드 TIFF -> RGB 합성 PNG (원해상도, 이미지만; 축/타이틀/여백 없음).

밴드 순서 : 0=PAN,1=Blue,2=Green,3=Red,4=RE1,5=RE2,6=RE3,7=NIR
RGB 매핑  : R=Red(band3), G=Green(band2), B=Blue(band1)
스트레치  : 채널별 percentile 스트레치 + mild gamma -> uint8
uint16/float32 입력 모두 지원.

사용법:
  python3 rgb_from_8band.py <8band.tiff> [--pct LOW HIGH] [--gamma G] [--out out.png]
예:
  python3 rgb_from_8band.py 260721_075224_regjit_rgbn_rot_8band_u16.tiff
  python3 rgb_from_8band.py .../8band_f32.tiff --pct 2 98 --gamma 1.6 --out rgb.png
"""
import os
import argparse
import numpy as np
import tifffile
from PIL import Image
import matplotlib.pyplot as plt

# RGB = (R,G,B) 에 대응하는 8밴드 인덱스
RGB_IDX = (3, 2, 1)   # Red, Green, Blue


def save_rgb_png(tiff_path, out_path=None, pct=(1.0, 99.0), gamma=1.4):
    Image.MAX_IMAGE_PIXELS = None                       # 대형 이미지 허용

    arr = tifffile.imread(tiff_path)                    # (8,H,W) 또는 (H,W,8)
    arr = np.asarray(arr)
    if arr.ndim != 3:
        raise SystemExit(f"[ERROR] 8밴드 3D 배열이 아님: shape={arr.shape}")
    # band 축을 앞으로 (밴드 수가 가장 작은 축을 band 축으로 간주)
    if arr.shape[0] > arr.shape[-1]:                    # (H,W,B) -> (B,H,W)
        arr = np.moveaxis(arr, -1, 0)
    nb = arr.shape[0]
    if max(RGB_IDX) >= nb:
        raise SystemExit(f"[ERROR] 밴드 수 부족: {nb} (RGB 인덱스 {RGB_IDX} 필요)")

    H, W = arr.shape[1], arr.shape[2]
    out = np.zeros((H, W, 3), dtype=np.uint8)
    for c, bidx in enumerate(RGB_IDX):                  # c=0:R,1:G,2:B
        ch = np.nan_to_num(arr[bidx].astype(np.float32))
        lo, hi = np.nanpercentile(ch, pct)
        v = np.clip((ch - lo) / max(hi - lo, 1e-6), 0, 1) ** (1.0 / gamma)
        out[..., c] = np.rint(v * 255).astype(np.uint8)


    if out_path is None:
        base = tiff_path
        for suf in ("_8band_u16", "_8band_f32", "_8band"):
            if base.endswith(suf + ".tiff"):
                base = base[:-(len(suf) + 5)]; break
        else:
            base = os.path.splitext(tiff_path)[0]
        out_path = base + "_rgb.png"

    Image.fromarray(out).save(out_path)
    #plt.imsave(out_path, out)
    print("wrote %s  (%dx%d, R=band%d G=band%d B=band%d, pct=%s, gamma=%.2f)" % (
        out_path, W, H, RGB_IDX[0], RGB_IDX[1], RGB_IDX[2], tuple(pct), gamma))
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="8밴드 TIFF -> RGB PNG")
    ap.add_argument("tiff", help="8밴드 TIFF 경로 (u16 또는 f32)")
    ap.add_argument("--pct", nargs=2, type=float, default=[1.0, 99.0],
                    metavar=("LOW", "HIGH"), help="채널별 스트레치 percentile (기본 1 99)")
    ap.add_argument("--gamma", type=float, default=1.4, help="감마 (기본 1.4)")
    ap.add_argument("--out", default=None, help="출력 PNG 경로 (기본: <입력>_rgb.png)")
    args = ap.parse_args()
    save_rgb_png(args.tiff, out_path=args.out, pct=tuple(args.pct), gamma=args.gamma)
