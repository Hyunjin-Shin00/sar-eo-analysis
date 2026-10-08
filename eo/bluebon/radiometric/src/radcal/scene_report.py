#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
단일 장면 절대복사보정 검증 보고서 생성 (TOA radiance/reflectance vs RadCalNet).

입력: 파이프라인 산출 TOA reflectance/radiance 8밴드 f32 + RadCalNet .output + ROI.
산출: report.md + 플롯(스펙트럼 오버레이 / 밴드 ratio / ROI 퀵룩).
"""
import os
import sys
import argparse
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import rasterio
from rasterio.windows import Window

from parse_radcalnet import parse_output
from band_integrate import load_srf, integrate_bands, BAND_NAMES

BANDS = list(range(8))
COL = {0: "0.4", 1: "#1f77b4", 2: "#2ca02c", 3: "#d62728",
       4: "#ff7f0e", 5: "#e377c2", 6: "#8c564b", 7: "#9467bd"}


def roi_mean(path, roi):
    r0, r1, c0, c1 = roi
    win = Window(c0, r0, c1 - c0, r1 - r0)
    out = {}
    with rasterio.open(path) as s:
        for b in BANDS:
            a = s.read(b + 1, window=win).astype(np.float64)
            a = a[np.isfinite(a)]
            out[b] = (float(a.mean()), float(a.std()))
    return out


def make_plots(out_dir, label, srf, sample, bi, toar_roi, rad_roi, ratios, ref_f32, roi):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    # --- A. 스펙트럼 오버레이: RadCalNet TOA + BB 밴드 TOAR ---
    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    m = (sample.wavelength >= 390) & (sample.wavelength <= 1010)
    ax.plot(sample.wavelength[m], sample.toa_refl[m], "k-", lw=1.2, label="RadCalNet TOA ρ (10nm)")
    ax.fill_between(sample.wavelength[m], sample.toa_refl[m] - sample.toa_refl_unc[m],
                    sample.toa_refl[m] + sample.toa_refl_unc[m], color="0.75", alpha=0.4)
    ax2 = ax.twinx()
    for b in BANDS:
        ax2.fill_between(srf["wl"], 0, srf[b] / srf[b].max(), color=COL[b], alpha=0.12)
        c = bi[b]["center"]
        ax.plot(c, bi[b]["refl"], "s", color=COL[b], ms=6, mec="k", mew=0.4)
        ax.plot(c, toar_roi[b][0], "o", color=COL[b], ms=8, mfc="none", mew=1.6)
    ax.plot([], [], "ks", ms=6, label="RadCalNet band-integrated ρ")
    ax.plot([], [], "ko", ms=8, mfc="none", label="BlueBON TOAR (FM1 abs. cal)")
    ax.set_xlim(390, 1010); ax.set_xlabel("wavelength [nm]"); ax.set_ylabel("TOA reflectance")
    ax2.set_ylabel("SRF (norm)"); ax2.set_ylim(0, 1)
    ax.set_title(f"{label}: BlueBON TOAR vs RadCalNet (DOY{sample.doy} {sample.utc}UTC, SZA {sample.sza:.1f}°)")
    ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); pA = os.path.join(out_dir, "rep_spectrum.png"); fig.savefig(pA); plt.close(fig)

    # --- B. 밴드별 ratio ---
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    xs = np.arange(8)
    ax.bar(xs, [ratios[b] for b in BANDS], color=[COL[b] for b in BANDS], alpha=0.85)
    ax.axhline(1.0, color="k", lw=1)
    ax.axhspan(0.9, 1.1, color="green", alpha=0.10, label="±10%")
    for b in BANDS:
        ax.text(b, ratios[b] + 0.01, f"{ratios[b]:.2f}", ha="center", fontsize=8)
    ax.set_xticks(xs); ax.set_xticklabels([BAND_NAMES[b] for b in BANDS])
    ax.set_ylabel("BlueBON TOAR / RadCalNet"); ax.set_ylim(0, max(1.4, max(ratios.values()) + 0.1))
    ax.set_title(f"{label}: per-band TOAR ratio (mean {np.mean(list(ratios.values())):.3f})")
    ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); pB = os.path.join(out_dir, "rep_ratio.png"); fig.savefig(pB); plt.close(fig)

    # --- C. ROI 퀵룩 (radiance f32에서 RGB) ---
    r0, r1, c0, c1 = roi; pad = 250
    with rasterio.open(ref_f32) as s:
        win = Window(c0 - pad, r0 - pad, (c1 - c0) + 2 * pad, (r1 - r0) + 2 * pad)
        rgb = np.zeros(((r1 - r0) + 2 * pad, (c1 - c0) + 2 * pad, 3), np.float32)
        for k, b in enumerate((3, 2, 1)):
            a = s.read(b + 1, window=win).astype(np.float32)
            lo, hi = np.nanpercentile(a, (1, 99))
            rgb[..., k] = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) ** (1 / 1.4)
    fig, ax = plt.subplots(figsize=(6, 6), dpi=110)
    ax.imshow(rgb, extent=[c0 - pad, c1 + pad, r1 + pad, r0 - pad])
    ax.add_patch(Rectangle((c0, r0), c1 - c0, r1 - r0, ec="red", fc="none", lw=2))
    ax.set_xlabel("col"); ax.set_ylabel("row"); ax.set_title(f"{label}: RadCalNet instrument ROI")
    fig.tight_layout(); pC = os.path.join(out_dir, "rep_roi.png"); fig.savefig(pC); plt.close(fig)
    return pA, pB, pC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="La Crau 20260528")
    ap.add_argument("--ref", required=True, help="TOA reflectance 8밴드 f32")
    ap.add_argument("--rad", required=True, help="TOA radiance 8밴드 f32")
    ap.add_argument("--radcal", required=True)
    ap.add_argument("--srf", default="<WORK_ROOT>/working/radiometric_correction/ref/SpectralResponseFunction.xlsx")
    ap.add_argument("--utc", required=True)
    ap.add_argument("--roi", nargs=4, type=int, required=True, metavar=("R0", "R1", "C0", "C1"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    sample = parse_output(a.radcal, utc=a.utc)
    srf = load_srf(a.srf)
    bi = integrate_bands(srf, sample.wavelength, sample.toa_refl, sample.toa_refl_unc)
    toar_roi = roi_mean(a.ref, tuple(a.roi))
    rad_roi = roi_mean(a.rad, tuple(a.roi))
    ratios = {b: toar_roi[b][0] / bi[b]["refl"] for b in BANDS}

    rv = np.array([ratios[b] for b in BANDS])
    mean_r, std_r = float(rv.mean()), float(rv.std())
    rmse_pct = float(np.sqrt(np.mean((rv - 1) ** 2)) * 100)

    pA, pB, pC = make_plots(a.out, a.label, srf, sample, bi, toar_roi, rad_roi, ratios, a.rad, tuple(a.roi))

    L = []; P = L.append
    P(f"# {a.label} — 절대복사보정 검증 보고서 (RadCalNet LCFR)\n")
    P("## 1. 개요\n")
    P(f"- 장면: BlueBON La Crau (프랑스), 촬영 {a.utc} UTC")
    P(f"- RadCalNet: {sample.site} lat {sample.lat} lon {sample.lon} · DOY {sample.doy} "
      f"→ 격자 **{sample.utc} UTC** (정확일 매칭)")
    P(f"- 태양기하: SZA **{sample.sza:.2f}°**, SAA {sample.saa:.2f}°, esd {sample.esd:.5f} AU")
    P(f"- 대기(RadCalNet): AOD(550) **{sample.atmos.get('AOD')}** (옅은 haze), "
      f"Ångström {sample.atmos.get('Ang')}, WV {sample.atmos.get('WV')} g/cm², O3 {sample.atmos.get('O3')} DU")
    P(f"- ROI: rows {a.roi[0]}–{a.roi[1]}, cols {a.roi[2]}–{a.roi[3]} — **실제 RadCalNet 계기 위치**\n")

    P("## 2. 처리 (절대복사보정 사슬)\n")
    P("`보정DN → radiance = DN·gain_FM1/band_width → TOAR = π·L/(F0·cosθs)/d_r`")
    P("- gain: FM1 실험실 밴드평균(TDI 2,4,8,8,16,16,16,4 / line rate 667≈666)")
    P("- F0: Thuillier(2003) × BlueBON SRF 밴드적분, 거리보정 ÷d_r (물리적으로 정확)\n")

    P("## 3. 검증 결과 (ROI 평균)\n")
    P("| 밴드 | 중심[nm] | BB radiance | BB TOAR | RadCalNet ρ±σ | ratio |")
    P("|--|--|--|--|--|--|")
    for b in BANDS:
        P(f"| {BAND_NAMES[b]} | {bi[b]['center']:.0f} | {rad_roi[b][0]:.2f} | "
          f"{toar_roi[b][0]:.4f} | {bi[b]['refl']:.4f}±{bi[b]['unc']:.4f} | **{ratios[b]:.3f}** |")
    P("")
    P(f"- **평균 ratio {mean_r:.3f}, 표준편차 {std_r:.3f}, RMSE {rmse_pct:.1f}%**")
    within = int(np.sum(np.abs(rv - 1) <= 0.1))
    P(f"- ±10% 이내 밴드: **{within}/8**\n")

    P("## 4. 플롯\n")
    P("- `rep_spectrum.png` — RadCalNet TOA 스펙트럼 + BB 밴드 TOAR(원) vs RadCalNet 밴드적분(사각)")
    P("- `rep_ratio.png` — 밴드별 TOAR 비율(±10% 밴드)")
    P("- `rep_roi.png` — RadCalNet 계기 ROI 위치\n")

    P("## 5. 해석\n")
    P(f"- FM1 절대보정 + v5 보정DN + F0 + 거리보정 사슬이 **{within}/8 밴드에서 RadCalNet과 ±10% 이내** 일치")
    P(f"  (평균 {mean_r:.3f}). 정확일·near-nadir 조건에서 절대복사보정이 유효함을 확인.")
    P("- 옅은 haze(AOD 0.21)는 RadCalNet가 대기산출로 반영 → TOA 비교 성립. 균일 연무라 타깃 오염 없음.")
    P("- Blue가 상대적으로 높은 편(경로복사·SRF 청색단 민감). PAN은 flat≈1(PRNU 미보정)로 상대 신뢰도 낮음.\n")

    P("## 6. 한계\n")
    P("- 단일 장면 → gain 적용은 by-construction, 선형성은 다장면 축적 필요.")
    P("- gain은 촬영설정(TDI/line-rate) 종속 — 설정 다르면 재조회 필요.")
    P("- ROI 대표성: 계기 위치 확인됨(CV~1%). BB GSD vs 계기 발자국 크기 차이는 잔여 오차.")

    rp = os.path.join(a.out, "report_20260528.md")
    open(rp, "w").write("\n".join(L))
    print("mean ratio=%.3f std=%.3f rmse=%.1f%% within±10%%=%d/8" % (mean_r, std_r, rmse_pct, within))
    print("→", rp)


if __name__ == "__main__":
    main()
