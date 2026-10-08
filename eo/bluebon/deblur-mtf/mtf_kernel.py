#!/usr/bin/env python3
"""추정된 blur 커널에서 직접 MTF 를 계산한다.

estimate-kernel 이 찾아낸 PSF 의 정규화 진폭 스펙트럼 |FFT(k)| / |FFT(k)|(0) 이
곧 그 blur 의 MTF 다. deblurring 이 보상하려는 열화량을 그대로 나타낸다.

across-track = x 방향(센서 배열 방향), along-track = y 방향(비행 방향).
주파수 단위는 cycles/pixel, Nyquist = 0.5.
"""
import numpy as np
import rasterio
import warnings

warnings.filterwarnings("ignore")
ROOT = "<WORK_ROOT>/working/debulr"
BANDS = {1: "MS1 (Blue)", 2: "MS2 (Green)", 3: "MS3 (Red)"}
PAD = 512   # 주파수 해상도 확보용 제로패딩


def mtf_1d(profile):
    """1D 프로파일의 정규화 MTF 와 주파수축을 돌려준다."""
    n = PAD
    p = np.zeros(n)
    k = len(profile)
    p[:k] = profile
    p = np.roll(p, -np.argmax(profile))       # 피크를 원점으로 (선형위상 제거)
    F = np.abs(np.fft.rfft(p))
    F /= F[0]
    f = np.fft.rfftfreq(n, d=1.0)
    return f, F


def at(f, F, target):
    return float(np.interp(target, f, F))


def mtf50(f, F):
    """MTF 가 0.5 로 떨어지는 주파수 (없으면 nan)."""
    below = np.where(F < 0.5)[0]
    if len(below) == 0:
        return float("nan")
    i = below[0]
    if i == 0:
        return 0.0
    # F 는 감소 구간이므로 선형보간
    f0, f1, y0, y1 = f[i - 1], f[i], F[i - 1], F[i]
    return float(f0 + (0.5 - y0) * (f1 - f0) / (y1 - y0))


print("=== 추정 커널에서 계산한 blur MTF (k=31, iterations=5) ===")
print("주파수 단위 cycles/pixel, Nyquist=0.5\n")
hdr = f"{'밴드':<14s} {'방향':<14s} {'MTF@Nyq':>9s} {'MTF@0.25':>9s} {'MTF50':>8s} {'FWHM':>7s}"
print(hdr)
print("-" * len(hdr.encode('utf-8').decode('utf-8')) )

rows = {}
for b, name in BANDS.items():
    with rasterio.open(f"{ROOT}/k31_ms{b}_i5.tif"
                       if False else f"{ROOT}/output/k31_ms{b}_i5.tif") as s:
        k = s.read(1).astype(np.float64)
    k /= k.sum()
    # 방향별 1D PSF: 직교 방향으로 적분 (line spread function)
    lsf_x = k.sum(axis=0)   # x 방향 LSF -> across-track MTF
    lsf_y = k.sum(axis=1)   # y 방향 LSF -> along-track MTF
    for label, lsf in (("across-track(x)", lsf_x), ("along-track(y)", lsf_y)):
        f, F = mtf_1d(lsf)
        # FWHM (LSF 반치전폭, 픽셀)
        c = lsf / lsf.max()
        idx = np.where(c >= 0.5)[0]
        fwhm = (idx[-1] - idx[0] + 1) if len(idx) else np.nan
        print(f"{name:<14s} {label:<14s} {at(f,F,0.5):9.4f} {at(f,F,0.25):9.4f} "
              f"{mtf50(f,F):8.4f} {fwhm:7.1f}")
        rows[(b, label)] = (f, F)
    print()

# 곡선 저장 (0 ~ Nyquist)
np.save(f"{ROOT}/output/mtf_kernel_curves.npy",
        {f"MS{b}|{d}": (f[f <= 0.5], F[f <= 0.5]) for (b, d), (f, F) in rows.items()},
        allow_pickle=True)
print("곡선 저장: output/mtf_kernel_curves.npy")
