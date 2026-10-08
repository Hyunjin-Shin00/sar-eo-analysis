"""
GDrive LEOP 폴더의 2026년 1~3월 영상 히스토그램 생성.
각 날짜 폴더의 level-0/*.tiff 파일들을 밴드별 다른 색으로 하나의 히스토그램 PNG로 저장.

실행방법
conda run -n prep python <WORK_ROOT>/prep/src/plot_histogram_leop.py
"""

import os
import re
import glob
import warnings
import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore', category=NotGeoreferencedWarning)

LEOP_DIR  = os.path.expanduser('~/gdrive/LEOP')
OUT_DIR   = '<WORK_ROOT>/prep/data/cloud/histogram'
BINS      = 256
X_MIN, X_MAX = 0, 4095

COLORS = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231',
    '#911eb4', '#42d4f4', '#f032e6', '#bfef45',
    '#fabed4', '#469990', '#dcbeff', '#9a6324',
]


def get_date_folders():
    """26년 1~3월 날짜 폴더만 반환 (YYMMDD_HHMMSS 형식)."""
    all_folders = sorted(os.listdir(LEOP_DIR))
    return [
        f for f in all_folders
        if re.match(r'^26(01|02|03)\d{2}_\d{6}$', f)
    ]


def plot_histogram(date_key, tiff_files):
    out_path = os.path.join(OUT_DIR, f'{date_key}_histogram.png')
    if os.path.exists(out_path):
        print(f'Skip (already exists): {date_key}')
        return

    fig, ax = plt.subplots(figsize=(12, 6))

    for i, fpath in enumerate(sorted(tiff_files)):
        label = os.path.basename(fpath)
        color = COLORS[i % len(COLORS)]
        with rasterio.open(fpath) as src:
            data = src.read(1).astype(np.float32).ravel()

        data = data[::16]  # 1/16 샘플링 — 히스토그램 정확도 유지하며 16배 속도 향상
        valid = data[(data >= X_MIN) & (data <= X_MAX)]
        counts, edges = np.histogram(valid, bins=BINS, range=(X_MIN, X_MAX))
        centers = (edges[:-1] + edges[1:]) / 2
        ax.plot(centers, counts, color=color, label=label, linewidth=1.2, alpha=0.85)

    ax.set_xlim(X_MIN, X_MAX)
    ax.set_xlabel('Pixel Value', fontsize=12)
    ax.set_ylabel('Count', fontsize=12)
    ax.set_title(f'Histogram — {date_key}', fontsize=14)
    ax.legend(fontsize=8, loc='upper right')
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f'Saved: {out_path}')


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    date_folders = get_date_folders()
    print(f'처리할 폴더 수: {len(date_folders)}개\n')

    for idx, date_key in enumerate(date_folders, 1):
        level0_dir = os.path.join(LEOP_DIR, date_key, 'level-0')
        if not os.path.isdir(level0_dir):
            print(f'[{idx}/{len(date_folders)}] level-0 없음, 건너뜀: {date_key}')
            continue

        tiff_files = glob.glob(os.path.join(level0_dir, '*.tiff'))
        tiff_files += glob.glob(os.path.join(level0_dir, '*.tif'))
        if not tiff_files:
            print(f'[{idx}/{len(date_folders)}] tiff 없음, 건너뜀: {date_key}')
            continue

        print(f'[{idx}/{len(date_folders)}] {date_key} ({len(tiff_files)}개 밴드)...', end=' ', flush=True)
        plot_histogram(date_key, tiff_files)


if __name__ == '__main__':
    main()
