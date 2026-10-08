#!/usr/bin/env python3
"""원본 vs alpha별 결과를 100% 확대 크롭으로 나란히 비교하는 PNG 생성.

usage: python3 make_crop_compare.py [x y size]
좌표 미지정 시 분산이 가장 큰(=디테일이 많은) 타일을 자동으로 고른다.
"""
import sys
import numpy as np
import rasterio
from PIL import Image, ImageDraw

ROOT = "<WORK_ROOT>/working/debulr"
ALPHAS = ["1000", "3000", "5000"]
SIZE = 512

def read(path, x, y, s):
    with rasterio.open(path) as src:
        return src.read(1, window=((y, y + s), (x, x + s))).astype(np.float32)

if len(sys.argv) >= 4:
    X, Y, SIZE = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
else:
    # MS2(밝은 밴드)에서 후보 타일을 훑어 표준편차 최대 지점 선택
    with rasterio.open(f"{ROOT}/input/MS2_DN_dark_rc_p.tiff") as src:
        W, H = src.width, src.height
        best, X, Y = -1, 0, 0
        for y in range(0, H - SIZE, 1000):
            for x in range(0, W - SIZE, 800):
                t = src.read(1, window=((y, y + SIZE), (x, x + SIZE)))
                if (t == 0).mean() > 0.01:
                    continue
                v = t.std()
                if v > best:
                    best, X, Y = v, x, y
    print(f"auto crop: x={X} y={Y} size={SIZE} std={best:.1f}")

# 스트레치는 원본 크롭 기준으로 고정
lims = []
for b in (3, 2, 1):
    t = read(f"{ROOT}/input/MS{b}_DN_dark_rc_p.tiff", X, Y, SIZE)
    lims.append(np.percentile(t, (2, 98)))

def rgb(tag):
    ch = []
    for b, (lo, hi) in zip((3, 2, 1), lims):
        p = (f"{ROOT}/input/MS{b}_DN_dark_rc_p.tiff" if tag == "orig"
             else f"{ROOT}/output/de_ms{b}_k31_i5_a{tag}.tiff")
        ch.append(np.clip((read(p, X, Y, SIZE) - lo) / (hi - lo), 0, 1))
    return (np.dstack(ch) * 255).astype(np.uint8)

tags = ["orig"] + ALPHAS
labels = ["original"] + [f"alpha={a}" for a in ALPHAS]
canvas = Image.new("RGB", (SIZE * len(tags), SIZE + 22), (0, 0, 0))
d = ImageDraw.Draw(canvas)
for i, (t, lab) in enumerate(zip(tags, labels)):
    canvas.paste(Image.fromarray(rgb(t)), (i * SIZE, 22))
    d.text((i * SIZE + 6, 6), lab, fill=(255, 255, 0))

out = f"{ROOT}/output/compare_x{X}_y{Y}.png"
canvas.save(out)
print(f"{out}  {canvas.width}x{canvas.height}")
