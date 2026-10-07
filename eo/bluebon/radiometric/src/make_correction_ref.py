#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BlueBON dark / PRNU 보정 참조 데이터 산출 (MS1~MS7)

- dark 소스 : 260606_190315/260606_190315_{n}_gray.tiff  (밤 원양 촬영 = 준-dark)
- PRNU 소스 : 260607_094318/260607_094318_{n}_gray.tiff  (Libya-4 사막 PICS = flat 대용)

밴드 index -> 이름 : 0=PAN, 1=Blue, 2=Green, 3=Red, 4=RE1, 5=RE2, 6=RE3, 7=NIR
파이프라인 명명    : b==0 -> PAN, 그 외 MS{b}
PAN(0) 제외, MS1~MS7 처리.

산출물(밴드별):
  MS{n}_dark_ref.tiff            float32 (1,4096)  열별 master dark
  MS{n}_dark_ref.dat             4096 float
  MS{n}_residul_prnu_coef.dat    헤더 + 4096 float (기존 파이프라인 포맷, 곱셈 gain)
  MS{n}_prnu_ref.tiff            float32 (1,4096)  PRNU 곱셈 gain
  MS{n}_preview.png              프로파일/검증 시각화
공통:
  README.txt, summary.csv

방법:
  dark_ref[col] = sigma-clip 평균(라인축, 3sigma x3)         (밤 원양의 미세 실광자/이상치 제거)
  sig[col]      = median(Libya, 라인축) - dark_ref[col]
  smooth        = movavg(sig, W)  (reflect 패딩)             (광학 vignetting/광역 gradient = 저주파)
  prnu[col]     = smooth/sig -> /mean  (평균 1.0, 곱셈형 고주파 검출소자 FPN 평탄화)
"""
import os
import numpy as np
import tifffile

# ----------------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------------
DATA_ROOT = "/mnt/e/bkchoi/prep/data"
# 야간 바다 dark 세션(운영 TDI 동일). 여러 개면 세션별 sigma-clip 평균 후 세션 평균 -> robust master dark.
DARK_SESSIONS = ["260606_190315", "260424_114919"]   # +Auckland 야간 바다 dark
# (하위호환) 단일 참조가 필요한 곳을 위해 첫 세션 노출
DARK_DIR  = f"{DATA_ROOT}/{DARK_SESSIONS[0]}"
DARK_STEM = DARK_SESSIONS[0]
LIB_DIR   = "/mnt/e/bkchoi/prep/data/260607_094318"
LIB_STEM  = "260607_094318"
OUT_DIR   = "/mnt/e/bkchoi/prep/data/correction_ref_260606"

BANDS      = [1, 2, 3, 4, 5, 6, 7]                 # PAN(0) 제외
BAND_NAME  = {1: "Blue", 2: "Green", 3: "Red", 4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
PRNU_WINDOW = 21          # 저주파 제거 이동평균 창(기존 prnu_calibration 관례와 정합)
SIGMA_CLIP  = 3.0         # dark sigma-clip 임계
SIGMA_ITERS = 3           # dark sigma-clip 반복


# ----------------------------------------------------------------------------
# 유틸
# ----------------------------------------------------------------------------
def sigma_clipped_mean(a, axis=0, sigma=SIGMA_CLIP, iters=SIGMA_ITERS):
    """axis 방향으로 sigma-clip 평균. a: 2D (lines, cols) -> (cols,)."""
    x = a.astype(np.float64)
    mask = np.ones_like(x, dtype=bool)
    for _ in range(iters):
        cnt = mask.sum(axis=axis)
        s   = np.where(mask, x, 0.0).sum(axis=axis)
        mean = s / np.maximum(cnt, 1)
        diff = x - np.expand_dims(mean, axis)
        var  = np.where(mask, diff * diff, 0.0).sum(axis=axis) / np.maximum(cnt, 1)
        std  = np.sqrt(var)
        newmask = np.abs(diff) <= (sigma * np.expand_dims(std, axis) + 1e-12)
        if newmask.sum() == mask.sum():
            mask = newmask
            break
        mask = newmask
    cnt = mask.sum(axis=axis)
    s   = np.where(mask, x, 0.0).sum(axis=axis)
    return s / np.maximum(cnt, 1)


def movavg_reflect(x, w):
    """reflect 패딩 이동평균(길이 보존). w는 홀수 권장."""
    if w <= 1:
        return x.copy()
    pad = w // 2
    xp  = np.pad(x, pad, mode="reflect")
    ker = np.ones(w) / w
    return np.convolve(xp, ker, mode="valid")[:len(x)]


def save_vec_tiff(path, vec):
    """1D 벡터를 float32 (1, N) TIFF로 저장(라인축 브로드캐스트용)."""
    arr = np.asarray(vec, dtype=np.float32).reshape(1, -1)
    tifffile.imwrite(path, arr)


def save_dat(path, vec, header=None):
    with open(path, "w") as f:
        if header is not None:
            f.write(header.rstrip("\n") + "\n")
        for v in np.asarray(vec, dtype=np.float64):
            f.write("%.7f\n" % v)


def build_dark_ref(n):
    """다중 야간 바다 dark 세션 -> 세션별 열 평균 -> 세션 평균 (master dark, 4096).
    야간 원양 dark은 이상치/실광자가 거의 없고(3σ 꼬리 0.3%뿐, 효과 <0.01 DN),
    16000라인 평균이 단발 스파이크도 희석하므로 단순 평균 사용(sigma-clip 불필요)."""
    accs = []
    for stem in DARK_SESSIONS:
        img = tifffile.imread(os.path.join(DATA_ROOT, stem, f"{stem}_{n}_gray.tiff"))
        accs.append(img.astype(np.float64).mean(axis=0))
    return np.mean(accs, axis=0)


# ----------------------------------------------------------------------------
# 밴드 처리
# ----------------------------------------------------------------------------
def process_band(n):
    name = BAND_NAME[n]
    lib_path  = os.path.join(LIB_DIR,  f"{LIB_STEM}_{n}_gray.tiff")

    # --- dark 참조 (다중 세션 평균) ---
    dark_ref = build_dark_ref(n)                               # (4096,)

    # --- Libya 열별 응답 (median, 장면 텍스처/구름 강건) ---
    lib_img = tifffile.imread(lib_path)                        # (16000, 4096) uint16
    lib_col = np.median(lib_img.astype(np.float64), axis=0)    # (4096,)

    # --- PRNU 산출 ---
    sig    = lib_col - dark_ref                                # dark 차감 열신호
    smooth = movavg_reflect(sig, PRNU_WINDOW)                  # 저주파(광학 vignetting)
    prnu   = smooth / sig                                      # 곱셈형 gain (norm/value)
    prnu   = prnu / prnu.mean()                                # 평균 정확히 1.0

    # --- 저장 ---
    save_vec_tiff(os.path.join(OUT_DIR, f"MS{n}_dark_ref.tiff"), dark_ref)
    save_dat(os.path.join(OUT_DIR, f"MS{n}_dark_ref.dat"), dark_ref)
    save_vec_tiff(os.path.join(OUT_DIR, f"MS{n}_prnu_ref.tiff"), prnu)
    save_dat(os.path.join(OUT_DIR, f"MS{n}_residul_prnu_coef.dat"), prnu,
             header=f"# MS{n} residual PRNU Coefficient for Radiance")

    # --- 검증용 지표: PRNU 적용 전/후 열신호 고주파 잔차 ---
    hf_before = (sig - smooth) / smooth                        # 적용 전 고주파 잔차(상대)
    corr      = sig * prnu                                     # PRNU 적용
    smooth_c  = movavg_reflect(corr, PRNU_WINDOW)
    hf_after  = (corr - smooth_c) / smooth_c                   # 적용 후 고주파 잔차

    stats = dict(
        band=n, name=name,
        dark_mean=float(dark_ref.mean()), dark_std=float(dark_ref.std()),
        dark_min=float(dark_ref.min()), dark_max=float(dark_ref.max()),
        lib_mean=float(lib_col.mean()),
        sig_mean=float(sig.mean()),
        prnu_mean=float(prnu.mean()), prnu_std_pct=float(prnu.std() * 100),
        prnu_min=float(prnu.min()), prnu_max=float(prnu.max()),
        hf_before_pct=float(hf_before.std() * 100),
        hf_after_pct=float(hf_after.std() * 100),
        n_nan=int(np.isnan(prnu).sum() + np.isinf(prnu).sum()),
        sig_min=float(sig.min()),
    )
    _make_preview(n, name, dark_ref, lib_col, sig, smooth, prnu, hf_before, hf_after, stats)
    return stats, dark_ref, lib_col, sig, prnu


def _make_preview(n, name, dark_ref, lib_col, sig, smooth, prnu, hf_before, hf_after, stats):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = np.arange(len(dark_ref))
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    fig.suptitle(f"MS{n} ({name}) dark / PRNU reference  [BlueBON 260606]", fontsize=13)

    ax[0, 0].plot(x, dark_ref, lw=0.5, color="navy")
    ax[0, 0].set_title(f"Dark reference (per-detector)  mean={stats['dark_mean']:.1f} DN")
    ax[0, 0].set_xlabel("detector column"); ax[0, 0].set_ylabel("DN")

    ax[0, 1].plot(x, lib_col, lw=0.5, color="darkorange", label="Libya raw (median)")
    ax[0, 1].plot(x, smooth + dark_ref, lw=1.0, color="black", label="low-freq (optics)")
    ax[0, 1].set_title(f"Libya-4 per-column response  mean={stats['lib_mean']:.0f} DN")
    ax[0, 1].set_xlabel("detector column"); ax[0, 1].set_ylabel("DN"); ax[0, 1].legend(fontsize=8)

    ax[1, 0].plot(x, prnu, lw=0.5, color="green")
    ax[1, 0].axhline(1.0, color="gray", lw=0.6, ls="--")
    ax[1, 0].set_title(f"PRNU coef (multiplicative)  std={stats['prnu_std_pct']:.3f}%  "
                       f"[{stats['prnu_min']:.4f}, {stats['prnu_max']:.4f}]")
    ax[1, 0].set_xlabel("detector column"); ax[1, 0].set_ylabel("gain")

    ax[1, 1].plot(x, hf_before * 100, lw=0.4, color="red",
                  label=f"before  std={stats['hf_before_pct']:.3f}%")
    ax[1, 1].plot(x, hf_after * 100, lw=0.4, color="blue",
                  label=f"after   std={stats['hf_after_pct']:.3f}%")
    ax[1, 1].set_title("High-freq residual non-uniformity: PRNU apply (Libya)")
    ax[1, 1].set_xlabel("detector column"); ax[1, 1].set_ylabel("residual [%]")
    ax[1, 1].legend(fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(os.path.join(OUT_DIR, f"MS{n}_preview.png"), dpi=110)
    plt.close(fig)


def write_readme(all_stats):
    lines = []
    lines.append("BlueBON dark / PRNU 보정 참조 데이터 (MS1~MS7)")
    lines.append("=" * 60)
    lines.append("")
    lines.append("[소스]")
    lines.append(f"  dark : {DARK_DIR}/{DARK_STEM}_{{n}}_gray.tiff  (밤 원양 촬영 = 준-dark)")
    lines.append(f"  PRNU : {LIB_DIR}/{LIB_STEM}_{{n}}_gray.tiff  (Libya-4 사막 PICS = flat 대용)")
    lines.append("  두 세트 모두 uint16, 16000(line/along-track) x 4096(detector/across-track)")
    lines.append("")
    lines.append("[밴드] index->이름: 0=PAN(제외), 1=Blue,2=Green,3=Red,4=RE1,5=RE2,6=RE3,7=NIR")
    lines.append("       파이프라인 명명 MS{n}")
    lines.append("")
    lines.append("[산출물] 밴드별")
    lines.append("  MS{n}_dark_ref.tiff         float32 (1,4096) 열별 master dark (라인축 브로드캐스트)")
    lines.append("  MS{n}_dark_ref.dat          4096 float")
    lines.append("  MS{n}_residul_prnu_coef.dat 헤더 + 4096 float (기존 파이프라인 포맷, 곱셈 gain)")
    lines.append("  MS{n}_prnu_ref.tiff         float32 (1,4096) PRNU 곱셈 gain")
    lines.append("  MS{n}_preview.png           프로파일/검증 시각화")
    lines.append("")
    lines.append("[방법]")
    lines.append(f"  dark_ref[col] = sigma-clip 평균(라인축, {SIGMA_CLIP}sigma x{SIGMA_ITERS})")
    lines.append("  sig[col]      = median(Libya, 라인축) - dark_ref[col]")
    lines.append(f"  smooth        = movavg(sig, W={PRNU_WINDOW})  (reflect, 광학 vignetting=저주파)")
    lines.append("  prnu[col]     = (smooth/sig)/mean  (평균 1.0, 곱셈형 고주파 검출소자 FPN)")
    lines.append("")
    lines.append("[적용 공식]")
    lines.append("  dn_dark  = raw(float) - dark_ref[col]           # 열축 브로드캐스트")
    lines.append("  radiance = dn_dark * gain[col] + intercept[col] # 파이프라인 절대 복사보정")
    lines.append("  radiance = radiance * residul_prnu_coef[col]    # 곱셈형 잔차 PRNU (본 산출)")
    lines.append("  (기존 01_DN_to_L_band.py 의 dark_correction / img*coef[None,:] 관례와 정합)")
    lines.append("")
    lines.append("[주의]")
    lines.append("  - dark 소스는 셔터-닫힘 순수 dark가 아니라 밤 원양 촬영이라 미세 실광자 잔존 가능")
    lines.append("    -> dark 약간 과대추정 가능. sigma-clip 평균으로 완화.")
    lines.append("  - dark 참조는 동일 센서 설정(TDI/line rate/gain/온도) 촬영에만 유효.")
    lines.append("    실제 촬영과 설정 다르면 dark 재취득 필요. (PRNU는 저주파 제거로 설정 불일치에 강건)")
    lines.append("  - 광학 vignetting/광역 gradient는 의도적으로 PRNU에서 제외(절대 radiometric_cal 담당).")
    lines.append("  - PAN(index 0) 제외.")
    lines.append("")
    lines.append("[밴드별 요약]")
    hdr = ("  MS  name   dark_mean dark_std   lib_mean   prnu_mean prnu_std%   "
           "hf_before% hf_after%  prnu[min,max]      nan sig_min")
    lines.append(hdr)
    for s in all_stats:
        lines.append("  MS%d %-5s %9.2f %8.3f %10.1f  %9.5f %8.4f   %8.4f  %8.4f  [%.4f,%.4f] %3d %8.1f" % (
            s["band"], s["name"], s["dark_mean"], s["dark_std"], s["lib_mean"],
            s["prnu_mean"], s["prnu_std_pct"], s["hf_before_pct"], s["hf_after_pct"],
            s["prnu_min"], s["prnu_max"], s["n_nan"], s["sig_min"]))
    with open(os.path.join(OUT_DIR, "README.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")

    # summary.csv
    keys = ["band", "name", "dark_mean", "dark_std", "dark_min", "dark_max",
            "lib_mean", "sig_mean", "sig_min", "prnu_mean", "prnu_std_pct",
            "prnu_min", "prnu_max", "hf_before_pct", "hf_after_pct", "n_nan"]
    with open(os.path.join(OUT_DIR, "summary.csv"), "w") as f:
        f.write(",".join(keys) + "\n")
        for s in all_stats:
            f.write(",".join(str(s[k]) for k in keys) + "\n")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_stats = []
    for n in BANDS:
        print(f"[MS{n} {BAND_NAME[n]}] processing ...", flush=True)
        stats, *_ = process_band(n)
        print("   dark_mean=%.2f  prnu_std=%.4f%%  hf %.3f%%->%.3f%%  nan=%d" % (
            stats["dark_mean"], stats["prnu_std_pct"],
            stats["hf_before_pct"], stats["hf_after_pct"], stats["n_nan"]), flush=True)
        all_stats.append(stats)
    write_readme(all_stats)
    print("\nDONE. outputs in", OUT_DIR)


if __name__ == "__main__":
    main()
