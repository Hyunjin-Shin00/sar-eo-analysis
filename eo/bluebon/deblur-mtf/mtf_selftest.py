#!/usr/bin/env python3
"""경사 에지 MTF 측정 코드의 자체 검증.

알려진 가우시안 PSF(sigma)로 흐린 합성 경사 에지를 만들어 측정하고,
해석해 MTF(f) = exp(-2 pi^2 sigma^2 f^2) 와 비교한다.
측정 코드가 맞다면 상대오차가 수 % 이내여야 한다.
"""
import warnings

import numpy as np
from scipy.ndimage import gaussian_filter

warnings.filterwarnings("ignore")
import mtf_edge as M


def synth(sigma, angle_deg, h=M.ALONG, w=M.ACROSS, lo=500.0, hi=1500.0,
          noise=0.0, sup=8, seed=0):
    """경사 에지를 sup배 초해상으로 만들고 흐린 뒤 다운샘플링."""
    H, Wd = h * sup, w * sup
    a = np.tan(np.radians(angle_deg))
    rr, cc = np.mgrid[0:H, 0:Wd]
    # 초해상 격자에서의 에지: 중심 통과
    d = (cc - Wd / 2.0) - a * (rr - H / 2.0)
    img = np.where(d > 0, hi, lo).astype(np.float64)
    img = gaussian_filter(img, sigma * sup, mode="nearest")
    # 픽셀 적분 = sup x sup 블록 평균
    img = img.reshape(h, sup, w, sup).mean(axis=(1, 3))
    if noise:
        rng = np.random.default_rng(seed)
        img = img + rng.normal(0, noise, img.shape)
    return img


def analytic(f, sigma):
    """가우시안 PSF + 픽셀 적분(sinc) 을 합친 이론 MTF."""
    return np.exp(-2 * np.pi ** 2 * sigma ** 2 * f ** 2) * np.abs(np.sinc(f))


print("=== 경사 에지 MTF 측정 자체 검증 ===")
print("합성 경사 에지(가우시안 PSF + 픽셀 적분) 측정값 vs 이론값\n")
print(f"{'sigma':>6s} {'각도':>6s} {'노이즈':>7s} "
      f"{'f=0.25 측정/이론':>22s} {'f=0.5 측정/이론':>22s}")
print("-" * 70)

for sigma in (0.6, 1.0, 1.4):
    for ang in (3.0, 5.0, 8.0):
        for noise in (0.0, 5.0):
            img = synth(sigma, ang, noise=noise)
            fit = M.fit_edge(img)
            if fit is None:
                print(f"{sigma:6.2f} {ang:6.1f} {noise:7.1f}   적합 실패")
                continue
            p = M.esf(img, fit["a"], fit["b"])
            if p is None:
                print(f"{sigma:6.2f} {ang:6.1f} {noise:7.1f}   ESF 실패")
                continue
            f, F = M.mtf_from_esf(p)
            m = []
            for t in (0.25, 0.5):
                meas = float(np.interp(t, f, F))
                th = analytic(t, sigma)
                m.append((meas, th, (meas - th) / th * 100))
            print(f"{sigma:6.2f} {ang:6.1f} {noise:7.1f}   "
                  f"{m[0][0]:.4f}/{m[0][1]:.4f} ({m[0][2]:+6.1f}%)   "
                  f"{m[1][0]:.4f}/{m[1][1]:.4f} ({m[1][2]:+6.1f}%)")
    print()
