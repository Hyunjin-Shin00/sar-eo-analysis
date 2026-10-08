#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dark/PRNU 참조를 실관측 RAW(260616_193632)에 적용해 열 고정패턴(stripe) 제거 검증.

적용 공식(참조 데이터 부분):  corr = (raw - dark_ref[col]) * prnu_coef[col]
(파이프라인의 절대 radiometric gain/intercept 는 여기 미적용 — 참조데이터 효과만 확인)

FPN 정량화:
  실장면을 16000라인 평균하면 장면성분은 매끈해지고 열 고정패턴(vertical stripe)만
  고주파로 잔존. 열평균 프로파일에서 (profile - movavg)/movavg 의 std 로 FPN[%] 측정.
  raw vs raw-dark vs corrected 비교.
"""
import os
import numpy as np
import tifffile

REF_DIR = "<WORK_ROOT>/prep/data/correction_ref_260606"
OUT_DIR  = "<WORK_ROOT>/prep/data"
TEST_DIR = os.path.join(OUT_DIR, "20260721_Sohae_Satellite_Launching_Station_north_korea/radiometric")
OBS_DIR  = "<WORK_ROOT>/prep/data/20260721_Sohae_Satellite_Launching_Station_north_korea"
OBS_STEM = "260721_030713"
BANDS    = [1, 2, 3, 4, 5, 6, 7]
BAND_NAME = {1: "Blue", 2: "Green", 3: "Red", 4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
W = 21
CROP_ROWS = (7000, 7500)     # 시각화용 along-track 크롭
CROP_COLS = (1800, 2200)     # 시각화용 across-track 크롭
SAT = 4095                   # 12bit 포화값


def movavg_reflect(x, w):
    if w <= 1:
        return x.copy()
    pad = w // 2
    xp = np.pad(x, pad, mode="reflect")
    return np.convolve(xp, np.ones(w) / w, mode="valid")[:len(x)]


def hf_std_pct(colprof):
    lf = movavg_reflect(colprof, W)
    return float(((colprof - lf) / lf).std() * 100)


def preview(n, name, raw, corr, prof_raw, prof_dark, prof_corr, stats):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    r0, r1 = CROP_ROWS
    c0, c1 = CROP_COLS
    fig, ax = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(f"MS{n} ({name}) dark+PRNU applied to observation 260616  "
                 f"(FPN {stats['fpn_raw']:.3f}%->{stats['fpn_corr']:.3f}%)", fontsize=13)

    # 열평균 고주파 성분 비교(장면성분 제거 위해 movavg 뺀 값)
    x = np.arange(len(prof_raw))
    ax[0, 0].plot(x, (prof_raw - movavg_reflect(prof_raw, W)), lw=0.4, color="red",
                  label=f"raw  ({stats['fpn_raw']:.3f}%)")
    ax[0, 0].plot(x, (prof_corr - movavg_reflect(prof_corr, W)), lw=0.4, color="blue",
                  label=f"corrected ({stats['fpn_corr']:.3f}%)")
    ax[0, 0].set_title("Column-mean high-freq (fixed-pattern) : full swath")
    ax[0, 0].set_xlabel("detector column"); ax[0, 0].set_ylabel("DN residual")
    ax[0, 0].legend(fontsize=8)

    ax[0, 1].plot(x[c0:c1], (prof_raw - movavg_reflect(prof_raw, W))[c0:c1], lw=0.7, color="red", label="raw")
    ax[0, 1].plot(x[c0:c1], (prof_corr - movavg_reflect(prof_corr, W))[c0:c1], lw=0.7, color="blue", label="corrected")
    ax[0, 1].set_title(f"same, zoom col {c0}-{c1}")
    ax[0, 1].set_xlabel("detector column"); ax[0, 1].set_ylabel("DN residual"); ax[0, 1].legend(fontsize=8)

    # 이미지 크롭 (stripe 시각). 동일 스케일.
    craw = raw[r0:r1, c0:c1].astype(np.float64)
    ccor = corr[r0:r1, c0:c1]
    vmin = np.percentile(craw, 2); vmax = np.percentile(craw, 98)
    ax[1, 0].imshow(craw, cmap="gray", vmin=vmin, vmax=vmax, aspect="auto")
    ax[1, 0].set_title(f"raw crop [{r0}:{r1}, {c0}:{c1}]")
    ax[1, 1].imshow(ccor, cmap="gray", vmin=vmin, vmax=vmax, aspect="auto")
    ax[1, 1].set_title("corrected crop (same scale)")
    for a in (ax[1, 0], ax[1, 1]):
        a.set_xlabel("column"); a.set_ylabel("line")

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(os.path.join(TEST_DIR, f"MS{n}_test_preview.png"), dpi=110)
    plt.close(fig)


def process(n):
    name = BAND_NAME[n]
    dark = tifffile.imread(os.path.join(REF_DIR, f"MS{n}_dark_ref.tiff")).astype(np.float64).ravel()  # (4096,)
    prnu = np.loadtxt(os.path.join(REF_DIR, f"MS{n}_residul_prnu_coef.dat"))                            # (4096,)

    raw = tifffile.imread(os.path.join(OBS_DIR, f"{OBS_STEM}_{n}_gray.tiff")).astype(np.float64)        # (16000,4096)
    corr = (raw - dark[None, :]) * prnu[None, :]

    # 포화픽셀 제외한 열평균(포화 stripe가 지표 오염 방지)
    valid = raw < SAT
    def col_mean_valid(img):
        s = np.where(valid, img, 0.0).sum(axis=0)
        c = valid.sum(axis=0)
        return s / np.maximum(c, 1)
    prof_raw  = col_mean_valid(raw)
    prof_dark = col_mean_valid(raw - dark[None, :])
    prof_corr = col_mean_valid(corr)

    stats = dict(band=n, name=name,
                 fpn_raw=hf_std_pct(prof_raw),
                 fpn_dark=hf_std_pct(prof_dark),
                 fpn_corr=hf_std_pct(prof_corr),
                 sat_pct=float((~valid).mean() * 100),
                 obs_mean=float(raw.mean()))

    # 보정 crop TIFF 저장(경량, float32)
    r0, r1 = CROP_ROWS
    tifffile.imwrite(os.path.join(TEST_DIR, f"MS{n}_obs_corrected_crop.tiff"),
                     corr[r0:r1].astype(np.float32))
    preview(n, name, raw, corr, prof_raw, prof_dark, prof_corr, stats)
    return stats


def main():
    os.makedirs(TEST_DIR, exist_ok=True)
    rows = []
    for n in BANDS:
        print(f"[MS{n} {BAND_NAME[n]}] applying ...", flush=True)
        s = process(n)
        print("   FPN raw=%.3f%%  raw-dark=%.3f%%  corrected=%.3f%%  (sat %.2f%%)" % (
            s["fpn_raw"], s["fpn_dark"], s["fpn_corr"], s["sat_pct"]), flush=True)
        rows.append(s)
    keys = ["band", "name", "obs_mean", "sat_pct", "fpn_raw", "fpn_dark", "fpn_corr"]
    with open(os.path.join(TEST_DIR, "test_summary.csv"), "w") as f:
        f.write(",".join(keys) + "\n")
        for s in rows:
            f.write(",".join(str(s[k]) for k in keys) + "\n")
    print("\nDONE. test outputs in", TEST_DIR)


if __name__ == "__main__":
    main()
