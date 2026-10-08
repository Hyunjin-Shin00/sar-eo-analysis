#!/usr/bin/env python3
"""임의 영역을 원본/alpha별로 2x2 격자에 확대 비교.

usage: python3 make_zoom_compare.py x y size [zoom] [outname]
"""
import sys
import warnings

import numpy as np
import rasterio
from PIL import Image, ImageDraw
from rasterio.windows import Window

warnings.filterwarnings("ignore")
ROOT = "<WORK_ROOT>/working/debulr"
ALPHAS = ["1000", "3000", "5000"]

X, Y, S = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
Z = int(sys.argv[4]) if len(sys.argv) > 4 else 3
NAME = sys.argv[5] if len(sys.argv) > 5 else f"zoom_x{X}_y{Y}"


def read(path):
    with rasterio.open(path) as s:
        return s.read(1, window=Window(X, Y, S, S)).astype(np.float32)


def src(b, tag):
    return (f"{ROOT}/input/MS{b}_DN_dark_rc_p.tiff" if tag == "orig"
            else f"{ROOT}/output/de_ms{b}_k31_i5_a{tag}.tiff")


# 스트레치 범위는 원본 크롭 기준으로 고정 -> 밝기 차 없이 선명도만 비교
lims = [np.percentile(read(src(b, "orig")), (1, 99)) for b in (3, 2, 1)]


def panel(tag):
    ch = [np.clip((read(src(b, tag)) - lo) / (hi - lo), 0, 1)
          for b, (lo, hi) in zip((3, 2, 1), lims)]
    im = Image.fromarray((np.dstack(ch) * 255).astype(np.uint8))
    return im.resize((S * Z, S * Z), Image.LANCZOS)


tags = ["orig"] + ALPHAS
# PIL 기본 폰트에 한글 글리프가 없어 라벨은 ASCII 로 둔다
labels = ["original (blurred)"] + [f"deblurred  alpha={a}" for a in ALPHAS]
P, PAD, BAR = S * Z, 4, 20
canvas = Image.new("RGB", (P * 2 + PAD, (P + BAR) * 2 + PAD), (16, 16, 16))
d = ImageDraw.Draw(canvas)
for i, (t, lab) in enumerate(zip(tags, labels)):
    px, py = (i % 2) * (P + PAD), (i // 2) * (P + BAR + PAD)
    canvas.paste(panel(t), (px, py + BAR))
    d.text((px + 6, py + 5), lab, fill=(255, 235, 90))

out = f"{ROOT}/output/{NAME}.png"
canvas.save(out)
print(f"{out}  {canvas.width}x{canvas.height}  (crop {S}px @ x{Z})")
