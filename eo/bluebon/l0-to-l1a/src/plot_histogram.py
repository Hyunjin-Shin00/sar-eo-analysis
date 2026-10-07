"""
data 폴더의 tiff 파일들을 타임스탬프별로 그룹화하여 히스토그램 PNG를 생성.
각 파일(밴드)은 다른 색으로 표시, x축은 0~4095로 고정.

실행방법
conda run -n prep python /mnt/e/bkchoi/prep/src/plot_histogram.py

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
from collections import defaultdict

DATA_DIR = '/mnt/e/bkchoi/prep/data'
BINS = 256
X_MIN, X_MAX = 0, 4095

COLORS = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231',
    '#911eb4', '#42d4f4', '#f032e6', '#bfef45',
    '#fabed4', '#469990', '#dcbeff', '#9a6324',
]


def group_tiffs_by_prefix(data_dir):
    """타임스탬프(YYMMDD_HHMMSS) 기준으로 tiff 파일 그룹화."""
    tiff_files = sorted(glob.glob(os.path.join(data_dir, '*.tif*')))
    groups = defaultdict(list)
    for f in tiff_files:
        name = os.path.basename(f)
        m = re.match(r'(\d{6}_\d{6})', name)
        key = m.group(1) if m else 'others'
        groups[key].append(f)
    return groups


def plot_histogram(group_key, file_list, out_dir):
    fig, ax = plt.subplots(figsize=(12, 6))

    for i, fpath in enumerate(file_list):
        label = os.path.basename(fpath)
        color = COLORS[i % len(COLORS)]
        with rasterio.open(fpath) as src:
            data = src.read(1).astype(np.float32).ravel()

        valid = data[(data >= X_MIN) & (data <= X_MAX)]
        counts, edges = np.histogram(valid, bins=BINS, range=(X_MIN, X_MAX))
        centers = (edges[:-1] + edges[1:]) / 2
        ax.plot(centers, counts, color=color, label=label, linewidth=1.2, alpha=0.85)

    ax.set_xlim(X_MIN, X_MAX)
    ax.set_xlabel('Pixel Value', fontsize=12)
    ax.set_ylabel('Count', fontsize=12)
    ax.set_title(f'Histogram — {group_key}', fontsize=14)
    ax.legend(fontsize=8, loc='upper right')
    ax.grid(True, alpha=0.3)

    out_path = os.path.join(out_dir, f'{group_key}_histogram.png')
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f'Saved: {out_path}')


def main():
    groups = group_tiffs_by_prefix(DATA_DIR)
    if not groups:
        print('tiff 파일을 찾을 수 없습니다.')
        return

    for key, files in groups.items():
        print(f'[{key}] {len(files)}개 파일 처리 중...')
        plot_histogram(key, files, DATA_DIR)


if __name__ == '__main__':
    main()
