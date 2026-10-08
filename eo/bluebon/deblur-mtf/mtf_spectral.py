#!/usr/bin/env python3
"""스펙트럼 비율로 deblur 의 주파수별 이득 G(f) 와 시스템 MTF 를 추정한다.

관측 O = S * k + n (S=실제 장면, k=PSF, n=노이즈), 출력 D = deblur(O).
deblur 를 준선형 필터로 보면 G(f) = <|D(f)|> / <|O(f)|> 이고,
장면->출력 시스템 MTF 는  MTF_sys(f) = MTF_k(f) x G(f) 로 쓸 수 있다.

수백 개 타일을 평균하므로 경사 에지법보다 분산이 훨씬 작다. 다만 고주파에서
원본은 이미 노이즈가 지배하므로, 그 대역의 G 는 신호 전달이 아니라 노이즈
증폭을 상당 부분 반영한다. 두 지표를 함께 봐야 한다.

usage: python3 mtf_spectral.py [--tiles=200] [--size=256]
"""
import sys
import warnings

import numpy as np
import rasterio
from rasterio.windows import Window

warnings.filterwarnings("ignore")
ROOT = "<WORK_ROOT>/working/debulr"
ALPHAS = ["1000", "3000", "5000"]


def src_path(b, tag):
    return (f"{ROOT}/input/MS{b}_DN_dark_rc_p.tiff" if tag == "orig"
            else f"{ROOT}/output/de_ms{b}_k31_i5_a{tag}.tiff")


def tile_positions(W, H, S, n):
    """이미지 전체에 고르게 분포한 타일 좌표 (난수 미사용, 격자 샘플)."""
    ny = int(np.ceil(np.sqrt(n * H / W)))
    nx = max(1, int(np.ceil(n / ny)))
    xs = np.linspace(0, W - S, nx).astype(int)
    ys = np.linspace(0, H - S, ny).astype(int)
    return [(x, y) for y in ys for x in xs][:n]


def mean_spectrum(path, pos, S, win):
    """타일별 진폭 스펙트럼의 평균과 유효 타일 수."""
    acc = np.zeros((S, S))
    k = 0
    with rasterio.open(path) as ds:
        for x, y in pos:
            a = ds.read(1, window=Window(x, y, S, S)).astype(np.float64)
            if a.shape != (S, S) or (a <= 0).any():
                continue
            a = a - a.mean()
            acc += np.abs(np.fft.fft2(a * win))
            k += 1
    return (acc / k if k else None), k


def kernel_mtf_axis(b, S):
    """커널 MTF 를 축방향으로 S 격자 주파수에 맞춰 계산."""
    with rasterio.open(f"{ROOT}/output/k31_ms{b}_i5.tif") as s:
        k = s.read(1).astype(np.float64)
    k /= k.sum()
    K = np.zeros((S, S))
    kh, kw = k.shape
    K[:kh, :kw] = k
    K = np.roll(np.roll(K, -(kh // 2), 0), -(kw // 2), 1)
    A = np.abs(np.fft.fft2(K))
    A /= A[0, 0]
    return A


def main():
    opt = {}
    for a in sys.argv[1:]:
        if a.startswith("--"):
            key, _, v = a[2:].partition("=")
            opt[key] = v
    S = int(opt.get("size", 256))
    n = int(opt.get("tiles", 200))
    win = np.outer(np.hanning(S), np.hanning(S))
    half = S // 2
    f = np.fft.fftfreq(S)[:half]        # cycles/pixel, 0 ~ 0.5 직전
    show = [0.125, 0.25, 0.375, 0.5]

    with rasterio.open(src_path(1, "orig")) as s:
        W, H = s.width, s.height
    pos = tile_positions(W, H, S, n)
    print(f"타일 {len(pos)}개 x {S}x{S} (Hann 창), 전체 {W}x{H} 에 격자 배치\n")

    out = {}
    for b in (1, 2, 3):
        spec = {}
        for tag in ["orig"] + ALPHAS:
            sp, k = mean_spectrum(src_path(b, tag), pos, S, win)
            if sp is None:
                print(f"MS{b} {tag}: 유효 타일 없음")
                continue
            spec[tag] = sp
        if "orig" not in spec:
            continue
        Ak = kernel_mtf_axis(b, S)
        for tag in ALPHAS:
            if tag not in spec:
                continue
            R = spec[tag] / np.maximum(spec["orig"], 1e-12)
            # 축방향 단면: across-track = 행 0 (x 주파수), along-track = 열 0
            gx = R[0, :half]
            gy = R[:half, 0]
            kx = Ak[0, :half]
            ky = Ak[:half, 0]
            out[(b, tag)] = dict(gx=gx, gy=gy, kx=kx, ky=ky)

    print("=== deblur 주파수 이득 G(f) 와 시스템 MTF = MTF_kernel x G ===")
    print("(across-track = x 방향, along-track = y 방향, Nyquist = 0.5 cyc/px)\n")
    for dirn, gk, kk in (("across-track(x)", "gx", "kx"),
                         ("along-track(y)", "gy", "ky")):
        print(f"--- {dirn} ---")
        hdr = f"{'밴드':<5s} {'영상':<8s}" + "".join(
            f"{'f='+str(t):>26s}" for t in show)
        print(hdr)
        print(f"{'':14s}" + "".join(f"{'G / MTF_sys':>26s}" for _ in show))
        for b in (1, 2, 3):
            k_ = None
            for tag in ALPHAS:
                if (b, tag) not in out:
                    continue
                d = out[(b, tag)]
                k_ = d[kk]
                g = d[gk]
                cells = ""
                for t in show:
                    gi = float(np.interp(t, f, g))
                    ki = float(np.interp(t, f, k_))
                    cells += f"{gi:11.2f}x /{ki*gi:9.4f}   "
                print(f"MS{b:<4d} a={tag:<6s}" + cells)
            if k_ is not None:
                cells = "".join(
                    f"{'-':>11s}  /{float(np.interp(t,f,k_)):9.4f}   "
                    for t in show)
                print(f"MS{b:<4d} {'원본':<7s}" + cells)
            print()

    np.save(f"{ROOT}/output/mtf_spectral.npy",
            dict(f=f, data=out), allow_pickle=True)
    print("곡선 저장: output/mtf_spectral.npy")


if __name__ == "__main__":
    main()
