#!/usr/bin/env python3
"""BlueBON MS3(R)/MS2(G)/MS1(B) 컴포짓 미리보기 PNG 생성.

usage: python3 make_rgb.py <alpha|orig> [--full]
       기본은 4x 축소 미리보기, --full 은 원본 해상도.
스트레치는 밴드별 2%~98% 퍼센타일(원본 기준으로 고정)로 통일해
alpha 값끼리 밝기 차이 없이 선명도만 비교할 수 있게 한다.
"""
import sys
import numpy as np
import rasterio
from rasterio.enums import Resampling
from PIL import Image

ROOT = "/mnt/e/bkchoi/working/debulr"
tag = sys.argv[1] if len(sys.argv) > 1 else "orig"
full = "--full" in sys.argv
step = 1 if full else 4

def path(b):
    if tag == "orig":
        return f"{ROOT}/input/MS{b}_DN_dark_rc_p.tiff"
    return f"{ROOT}/output/de_ms{b}_k31_i5_a{tag}.tiff"

# 스트레치 범위는 항상 원본에서 계산해 모든 결과물에 동일 적용
lims = []
for b in (3, 2, 1):
    with rasterio.open(f"{ROOT}/input/MS{b}_DN_dark_rc_p.tiff") as s:
        sub = s.read(1, out_shape=(s.height // 8, s.width // 8),
                     resampling=Resampling.nearest)
    lims.append(np.percentile(sub[sub > 0], (2, 98)))

chans = []
for (b, (lo, hi)) in zip((3, 2, 1), lims):
    with rasterio.open(path(b)) as s:
        a = s.read(1)[::step, ::step].astype(np.float32)
    chans.append(np.clip((a - lo) / (hi - lo), 0, 1))

rgb = (np.dstack(chans) * 255).astype(np.uint8)
out = f"{ROOT}/output/rgb_{tag}{'_full' if full else '_preview'}.png"
Image.fromarray(rgb).save(out)
print(f"{out}  {rgb.shape[1]}x{rgb.shape[0]}")
