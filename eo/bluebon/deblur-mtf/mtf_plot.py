#!/usr/bin/env python3
"""경사 에지 MTF 곡선 그림 (3밴드 x 2방향 스몰 멀티플).

원본은 기준선이므로 중립 회색, alpha 는 순서형 파라미터이므로 파랑 ordinal
램프(250/450/650)로 인코딩한다. 추정 커널 MTF 는 색이 아닌 점선으로 구분해
색이 두 가지 의미를 겸하지 않게 한다.

usage: python3 mtf_plot.py [--n=24]
"""
import json
import os
import sys
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

# 한글 라벨용 폰트. 리눅스측에 한글 폰트가 없어 WSL 에서 보이는 Windows 폰트를 쓴다.
for _f in ("/mnt/c/Windows/Fonts/malgun.ttf",):
    if os.path.exists(_f):
        fm.fontManager.addfont(_f)
        matplotlib.rcParams["font.family"] = fm.FontProperties(
            fname=_f).get_name()
        break
matplotlib.rcParams["axes.unicode_minus"] = False
import numpy as np
import rasterio
from rasterio.windows import Window

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mtf_edge as M

ROOT = M.ROOT
CACHE = f"{ROOT}/output/mtf_rois.json"
FGRID = np.linspace(0.0, 0.55, 112)

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8985"
GRID = "#e6e5e1"
BASE = "#52514e"                                    # 원본(기준선) = 중립 잉크
RAMP = {"1000": "#86b6ef", "3000": "#2a78d6", "5000": "#104281"}


def get_rois(want):
    if os.path.exists(CACHE):
        with open(CACHE) as fh:
            d = json.load(fh)
        if d.get("want") == want:
            return {k: v for k, v in d["rois"].items()}
    rois = {}
    for vertical, dirn in ((True, "across"), (False, "along")):
        rois[dirn] = M.find_rois(2, vertical, want)
    with open(CACHE, "w") as fh:
        json.dump(dict(want=want, rois=rois), fh)
    return rois


def curves(band, tag, rois, vertical):
    w_, h_ = (M.ACROSS, M.ALONG) if vertical else (M.ALONG, M.ACROSS)
    acc = []
    with rasterio.open(M.src_path(band, tag)) as ds:
        for r in rois:
            a = ds.read(1, window=Window(r["x"], r["y"], w_, h_)
                        ).astype(np.float64)
            rr = a if vertical else a.T
            p = M.esf(rr, r["a"], r["b"])       # 기하는 원본 적합값 재사용
            if p is None:
                continue
            out = M.mtf_from_esf(p)
            if out is None:
                continue
            f, F = out
            if np.isnan(F[f <= 0.5]).any():
                continue
            acc.append(np.interp(FGRID, f, F))
    if not acc:
        return None
    A = np.array(acc)
    return (np.median(A, axis=0), np.percentile(A, 25, axis=0),
            np.percentile(A, 75, axis=0), len(A))


def kernel_curve(band, vertical):
    with rasterio.open(f"{ROOT}/output/k31_ms{band}_i5.tif") as s:
        k = s.read(1).astype(np.float64)
    k /= k.sum()
    lsf = k.sum(axis=0) if vertical else k.sum(axis=1)
    n = 512
    p = np.zeros(n)
    p[:len(lsf)] = lsf
    p = np.roll(p, -int(np.argmax(lsf)))
    F = np.abs(np.fft.rfft(p))
    F /= F[0]
    return np.interp(FGRID, np.fft.rfftfreq(n, d=1.0), F)


def main():
    want = 24
    for a in sys.argv[1:]:
        if a.startswith("--n="):
            want = int(a[4:])
    rois = get_rois(want)

    fig, axes = plt.subplots(2, 3, figsize=(13.2, 7.6), sharex=True,
                             sharey=True, facecolor=SURFACE)
    names = {1: "MS1 (Blue)", 2: "MS2 (Green)", 3: "MS3 (Red)"}
    for row, (dirn, vertical, dlabel) in enumerate(
            (("across", True, "across-track (x)"),
             ("along", False, "along-track (y)"))):
        rs = rois[dirn]
        for col, band in enumerate((1, 2, 3)):
            ax = axes[row][col]
            ax.set_facecolor(SURFACE)
            ax.axvline(0.5, color=MUTED, lw=1, ls=(0, (2, 3)), zorder=1)
            ax.plot(FGRID, kernel_curve(band, vertical), color=BASE, lw=1.6,
                    ls=(0, (5, 2)), zorder=3,
                    label="추정 커널 MTF" if row == 0 and col == 0 else None)
            for tag in ["orig", "1000", "3000", "5000"]:
                c = curves(band, tag, rs, vertical)
                if c is None:
                    continue
                med, p25, p75, n = c
                color = BASE if tag == "orig" else RAMP[tag]
                lab = (f"원본 (n={n})" if tag == "orig"
                       else f"deblur α={tag}")
                ax.fill_between(FGRID, p25, p75, color=color, alpha=0.13,
                                lw=0, zorder=2)
                ax.plot(FGRID, med, color=color, lw=2.0, zorder=4,
                        label=lab if (row == 0 and col == 0) else None)
            ax.set_ylim(0, 1.25)
            ax.set_xlim(0, 0.55)
            ax.grid(True, color=GRID, lw=0.8)
            ax.set_axisbelow(True)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
            for sp in ("left", "bottom"):
                ax.spines[sp].set_color(GRID)
            ax.tick_params(colors=INK2, labelsize=9)
            if row == 0:
                ax.set_title(names[band], color=INK, fontsize=11, pad=8)
            if col == 0:
                ax.set_ylabel(f"{dlabel}\nMTF", color=INK2, fontsize=10)
            if row == 1:
                ax.set_xlabel("공간주파수 (cycles/pixel)", color=INK2,
                              fontsize=10)
            ax.text(0.503, 1.19, "Nyquist", color=MUTED, fontsize=8,
                    ha="left", va="top", rotation=90)

    h, l = axes[0][0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=5, frameon=False,
               bbox_to_anchor=(0.5, 0.055), fontsize=10, labelcolor=INK2)
    fig.suptitle("BlueBON MS1/MS2/MS3  경사 에지 MTF — deblurring 전후",
                 color=INK, fontsize=13.5, y=0.985)
    fig.text(0.5, 0.935,
             f"에지 {len(rois['across'])}곳(across) / {len(rois['along'])}곳"
             f"(along)의 중위값, 음영은 사분위 범위. "
             f"점선은 추정 커널에서 계산한 blur MTF.",
             color=MUTED, fontsize=9.5, ha="center")
    fig.tight_layout(rect=[0, 0.085, 1, 0.925])
    out = f"{ROOT}/output/mtf_curves.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main()
