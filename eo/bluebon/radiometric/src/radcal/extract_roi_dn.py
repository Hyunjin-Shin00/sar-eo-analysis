#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BlueBON 8밴드 보정 DN(TIFF)에서 La Crau ROI 통계 추출 + 위치확인용 퀵룩 생성.

- 8밴드 TIFF는 지리참조가 없으므로(L1A 센서기하) ROI는 픽셀 bbox(row0 row1 col0 col1)로 지정.
- 퀵룩: 다운샘플 RGB(Red/Green/Blue = band3/2/1) + 격자·픽셀좌표 오버레이 → 사이트 위치 시각 확인.
- ROI 통계: rasterio window read로 bbox만 읽어 밴드별 mean/std/CV%(균질도) 산출.

밴드 순서: 0=PAN,1=Blue,2=Green,3=Red,4=RE1,5=RE2,6=RE3,7=NIR
"""
import numpy as np
import rasterio
from rasterio.windows import Window

BAND_NAMES = {0: "PAN", 1: "Blue", 2: "Green", 3: "Red",
              4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
RGB_BANDS = (3, 2, 1)   # rasterio 1-based로는 +1


def make_quicklook(tiff_path, out_png, decim=20, pct=(1.0, 99.0), gamma=1.4,
                   grid_step=1000, roi=None):
    """다운샘플 RGB 퀵룩(격자/좌표 오버레이) 생성. roi=(r0,r1,c0,c1) 주면 사각형 표시."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    with rasterio.open(tiff_path) as ds:
        H, W = ds.height, ds.width
        # 데시메이션 읽기(overview 대신 out_shape 사용)
        oh, ow = H // decim, W // decim
        rgb = np.zeros((oh, ow, 3), dtype=np.float32)
        for c, b in enumerate(RGB_BANDS):
            arr = ds.read(b + 1, out_shape=(oh, ow)).astype(np.float32)
            lo, hi = np.nanpercentile(arr, pct)
            v = np.clip((arr - lo) / max(hi - lo, 1e-6), 0, 1) ** (1.0 / gamma)
            rgb[..., c] = v

    fig_h = max(6, oh / 100)
    fig, ax = plt.subplots(figsize=(max(4, ow / 100), fig_h), dpi=100)
    ax.imshow(rgb, extent=[0, W, H, 0], interpolation="nearest")
    ax.set_xticks(np.arange(0, W, grid_step))
    ax.set_yticks(np.arange(0, H, grid_step))
    ax.grid(True, color="yellow", alpha=0.4, lw=0.5)
    ax.set_xlabel("col (px)")
    ax.set_ylabel("row (px)")
    ax.set_title(f"{tiff_path.split('/')[-1]}  ({W}x{H}, decim={decim})")
    if roi is not None:
        r0, r1, c0, c1 = roi
        ax.add_patch(Rectangle((c0, r0), c1 - c0, r1 - r0,
                               ec="red", fc="none", lw=2))
    fig.tight_layout()
    fig.savefig(out_png, dpi=100)
    plt.close(fig)
    print(f"wrote {out_png}  ({ow}x{oh}, full {W}x{H})")
    return out_png


def extract_roi(tiff_path, roi):
    """roi=(row0,row1,col0,col1) 영역의 밴드별 통계를 반환.

    반환: dict[band_idx] = {'mean','std','cv','min','max','n'}
    """
    r0, r1, c0, c1 = roi
    win = Window(col_off=c0, row_off=r0, width=c1 - c0, height=r1 - r0)
    stats = {}
    with rasterio.open(tiff_path) as ds:
        nb = ds.count
        for b in range(nb):
            arr = ds.read(b + 1, window=win).astype(np.float64)
            arr = arr[np.isfinite(arr)]
            # DN 0(무효/외곽)은 제외
            arr = arr[arr > 0]
            if arr.size == 0:
                stats[b] = dict(mean=np.nan, std=np.nan, cv=np.nan,
                                min=np.nan, max=np.nan, n=0)
                continue
            mean = float(arr.mean())
            std = float(arr.std())
            stats[b] = dict(mean=mean, std=std,
                            cv=float(std / mean * 100 if mean else np.nan),
                            min=float(arr.min()), max=float(arr.max()),
                            n=int(arr.size))
    return stats


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="퀵룩 생성 / ROI DN 통계")
    ap.add_argument("tiff")
    ap.add_argument("--quicklook", help="퀵룩 PNG 출력 경로 생성")
    ap.add_argument("--decim", type=int, default=20)
    ap.add_argument("--roi", nargs=4, type=int, metavar=("R0", "R1", "C0", "C1"))
    a = ap.parse_args()

    if a.quicklook:
        make_quicklook(a.tiff, a.quicklook, decim=a.decim, roi=tuple(a.roi) if a.roi else None)
    if a.roi:
        st = extract_roi(a.tiff, tuple(a.roi))
        print(f"=== ROI {a.roi} DN 통계 ===")
        for b in sorted(st):
            d = st[b]
            print(f"  idx{b} {BAND_NAMES.get(b,'?'):5s}: mean={d['mean']:8.2f} "
                  f"std={d['std']:7.2f} CV={d['cv']:5.2f}%  n={d['n']}")
