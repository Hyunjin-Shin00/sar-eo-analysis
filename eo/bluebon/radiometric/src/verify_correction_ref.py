#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
저장된 dark/PRNU 참조를 재로드해 독립 검증 (MS1~MS7).

- 산출 파일 포맷/shape/dtype 확인
- Libya 원본에 (raw - dark_ref) * prnu_coef 적용 -> 고주파 잔차 비균일 감소 확인
- sanity: prnu 평균~1.0, NaN/Inf 없음, dark 차감 후 전열 양수
"""
import os
import numpy as np
import tifffile

OUT_DIR  = "<WORK_ROOT>/prep/data/correction_ref_260606"
LIB_DIR  = "<WORK_ROOT>/prep/data/260607_094318"
LIB_STEM = "260607_094318"
BANDS    = [1, 2, 3, 4, 5, 6, 7]
BAND_NAME = {1: "Blue", 2: "Green", 3: "Red", 4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
W = 21


def movavg_reflect(x, w):
    if w <= 1:
        return x.copy()
    pad = w // 2
    xp = np.pad(x, pad, mode="reflect")
    return np.convolve(xp, np.ones(w) / w, mode="valid")[:len(x)]


def load_dat(path):
    return np.loadtxt(path)  # '#' 주석 자동 무시


def check(cond, msg, fails):
    tag = "OK  " if cond else "FAIL"
    if not cond:
        fails.append(msg)
    print(f"    [{tag}] {msg}")
    return cond


def main():
    all_ok = True
    for n in BANDS:
        print(f"[MS{n} {BAND_NAME[n]}]")
        fails = []
        dark_tif = os.path.join(OUT_DIR, f"MS{n}_dark_ref.tiff")
        prnu_tif = os.path.join(OUT_DIR, f"MS{n}_prnu_ref.tiff")
        prnu_dat = os.path.join(OUT_DIR, f"MS{n}_residul_prnu_coef.dat")

        # --- 포맷 확인 ---
        dark = tifffile.imread(dark_tif)
        prnu = tifffile.imread(prnu_tif)
        check(dark.shape == (1, 4096) and dark.dtype == np.float32,
              f"dark_ref.tiff shape/dtype = {dark.shape}/{dark.dtype}", fails)
        check(prnu.shape == (1, 4096) and prnu.dtype == np.float32,
              f"prnu_ref.tiff shape/dtype = {prnu.shape}/{prnu.dtype}", fails)
        with open(prnu_dat) as f:
            nlines = sum(1 for _ in f)
        check(nlines == 4097, f".dat line count = {nlines} (expect 4097: header+4096)", fails)
        with open(prnu_dat) as f:
            hdr = f.readline().strip()
        check(hdr == f"# MS{n} residual PRNU Coefficient for Radiance",
              f".dat header = {hdr!r}", fails)

        dark = dark.ravel().astype(np.float64)
        prnu_d = load_dat(prnu_dat)
        prnu_t = prnu.ravel().astype(np.float64)
        check(np.allclose(prnu_d, prnu_t, atol=1e-4),
              ".dat 와 prnu_ref.tiff 값 일치", fails)

        # --- sanity ---
        check(abs(prnu_d.mean() - 1.0) < 1e-3, f"prnu mean = {prnu_d.mean():.6f} (~1.0)", fails)
        check(np.isfinite(prnu_d).all(), "prnu 유한값(NaN/Inf 없음)", fails)
        check(prnu_d.min() > 0.85 and prnu_d.max() < 1.15,
              f"prnu 범위 [{prnu_d.min():.4f}, {prnu_d.max():.4f}]", fails)

        # --- end-to-end: Libya 원본에 적용 ---
        lib = tifffile.imread(os.path.join(LIB_DIR, f"{LIB_STEM}_{n}_gray.tiff")).astype(np.float64)
        lib_col = np.median(lib, axis=0)
        sig = lib_col - dark
        check(sig.min() > 0, f"dark 차감 후 Libya 전열 양수 (min={sig.min():.1f})", fails)

        corr = sig * prnu_d
        hf_before = ((sig - movavg_reflect(sig, W)) / movavg_reflect(sig, W)).std() * 100
        hf_after = ((corr - movavg_reflect(corr, W)) / movavg_reflect(corr, W)).std() * 100
        check(hf_after < hf_before,
              f"고주파 잔차 비균일 감소: {hf_before:.3f}% -> {hf_after:.3f}%", fails)

        if fails:
            all_ok = False
            print(f"    => {len(fails)} FAIL")
        else:
            print("    => ALL PASS")
        print()

    print("=" * 50)
    print("VERIFY RESULT:", "ALL BANDS PASS" if all_ok else "SOME CHECKS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
