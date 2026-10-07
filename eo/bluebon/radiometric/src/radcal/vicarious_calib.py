#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
대리복사보정(vicarious calibration) 계수 산출 + 플롯 + 리포트.

입력: RadCalNet 밴드적분 TOA 반사율(ρ_b, σ_b) + ROI 보정 DN 통계(mean, std, CV).
BB v5 산출물은 dark 차감된 상대 DN이므로 offset=0 가정, 원점 통과 선형:
    gain_ρ,b = ρ_b / DN_b        [reflectance / DN]
즉 관측 DN에 gain을 곱하면 밴드별 TOA 반사율이 된다.

불확도(1σ, 상대):
    RadCalNet ρ 불확도  : σ_b / ρ_b
    사이트 공간 대표성   : CV_b/100 (ROI 공간 이질성, 보수적)
    합성                : sqrt(둘의 제곱합)
(참고) 평균의 표준오차 std/(mean·√N)는 무시할 만큼 작아 별도 표기.
"""
import numpy as np

BAND_ORDER = [0, 1, 2, 3, 4, 5, 6, 7]
BAND_NAMES = {0: "PAN", 1: "Blue", 2: "Green", 3: "Red",
              4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}


def compute_gains(band_integ, roi_stats):
    """밴드별 대리보정 계수(반사율 기반)를 산출.

    band_integ: dict[b] = {'refl','unc','center','width','coverage'}  (band_integrate.integrate_bands)
    roi_stats : dict[b] = {'mean','std','cv','n', ...}                (extract_roi_dn.extract_roi)
    반환: dict[b] = {center,width,coverage, rho,rho_unc, dn,dn_std,cv,n,
                     gain, gain_unc, rel_unc_rho, rel_unc_dn, rel_unc}
    """
    out = {}
    for b in BAND_ORDER:
        bi, rs = band_integ[b], roi_stats[b]
        rho, sig = bi["refl"], bi["unc"]
        dn = rs["mean"]
        gain = rho / dn if dn else np.nan
        rel_rho = (sig / rho) if (rho and np.isfinite(sig)) else np.nan
        rel_dn = (rs["cv"] / 100.0) if np.isfinite(rs["cv"]) else np.nan
        rel = float(np.sqrt(np.nansum([rel_rho**2, rel_dn**2]))) if dn else np.nan
        out[b] = dict(
            center=bi["center"], width=bi["width"], coverage=bi["coverage"],
            rho=rho, rho_unc=sig, dn=dn, dn_std=rs["std"], cv=rs["cv"], n=rs["n"],
            gain=gain, gain_unc=gain * rel if np.isfinite(rel) else np.nan,
            rel_unc_rho=rel_rho, rel_unc_dn=rel_dn, rel_unc=rel,
        )
    return out


def write_csv(gains, path):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["band_idx", "name", "center_nm", "fwhm_nm", "srf_coverage",
                    "toa_refl", "toa_refl_unc", "roi_dn_mean", "roi_dn_std", "roi_cv_pct",
                    "n_pix", "gain_refl_per_dn", "gain_unc", "rel_unc_rho", "rel_unc_dn",
                    "rel_unc_total"])
        for b in BAND_ORDER:
            g = gains[b]
            w.writerow([b, BAND_NAMES[b], f"{g['center']:.1f}", f"{g['width']:.1f}",
                        f"{g['coverage']:.3f}", f"{g['rho']:.5f}", f"{g['rho_unc']:.5f}",
                        f"{g['dn']:.2f}", f"{g['dn_std']:.2f}", f"{g['cv']:.2f}", g['n'],
                        f"{g['gain']:.6e}", f"{g['gain_unc']:.6e}",
                        f"{g['rel_unc_rho']:.4f}", f"{g['rel_unc_dn']:.4f}",
                        f"{g['rel_unc']:.4f}"])
    return path


# ---------------------------------------------------------------- 플롯 --------
def plot_srf_spectrum(srf, sample, gains, path):
    """RadCalNet TOA 스펙트럼(400~1000nm) + SRF 오버레이 + 밴드적분점."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {0: "0.4", 1: "#1f77b4", 2: "#2ca02c", 3: "#d62728",
              4: "#ff7f0e", 5: "#e377c2", 6: "#8c564b", 7: "#9467bd"}
    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    m = (sample.wavelength >= 390) & (sample.wavelength <= 1010)
    ax.plot(sample.wavelength[m], sample.toa_refl[m], "k-o", ms=3, lw=1.2,
            label="RadCalNet TOA refl (10nm)")
    ax.fill_between(sample.wavelength[m], sample.toa_refl[m] - sample.toa_refl_unc[m],
                    sample.toa_refl[m] + sample.toa_refl_unc[m], color="0.7", alpha=0.4)
    ax2 = ax.twinx()
    for b in BAND_ORDER:
        ax2.fill_between(srf["wl"], 0, srf[b] / srf[b].max(), color=colors[b], alpha=0.18)
        g = gains[b]
        ax.errorbar(g["center"], g["rho"], yerr=g["rho_unc"], fmt="s",
                    color=colors[b], ms=7, capsize=3,
                    label=f"{BAND_NAMES[b]} ρ={g['rho']:.3f}")
    ax.set_xlim(390, 1010)
    ax.set_xlabel("wavelength [nm]"); ax.set_ylabel("TOA reflectance")
    ax2.set_ylabel("SRF (normalized)"); ax2.set_ylim(0, 1)
    ax.set_title(f"RadCalNet LCFR TOA vs BlueBON SRF  (DOY{sample.doy} {sample.utc}UTC, "
                 f"SZA={sample.sza:.1f}°)")
    ax.legend(fontsize=7, ncol=2, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    return path


def plot_gain_scatter(gains, path):
    """밴드 ρ_TOA vs mean DN 산점 + 밴드별 원점통과 gain 직선."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 6), dpi=120)
    for b in BAND_ORDER:
        g = gains[b]
        ax.errorbar(g["dn"], g["rho"], yerr=g["rho_unc"], xerr=g["dn_std"],
                    fmt="o", ms=6, capsize=2)
        ax.annotate(BAND_NAMES[b], (g["dn"], g["rho"]),
                    textcoords="offset points", xytext=(6, 4), fontsize=8)
    ax.set_xlabel("ROI mean corrected DN"); ax.set_ylabel("RadCalNet band TOA reflectance")
    ax.set_title("Vicarious gain: TOA reflectance vs DN (per band)")
    ax.grid(alpha=0.3)
    ax.set_xlim(0, None); ax.set_ylim(0, None)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    return path


def plot_gain_spectrum(gains, path):
    """도출된 대리보정 gain의 파장 스펙트럼(QA용).

    gain = ρ/DN 은 (태양조도·센서 QE·대역폭)의 역수 성질을 반영하므로 파장에 따라
    부드럽게 변해야 한다. 들쭉날쭉하면 ROI/SRF/밴드정렬 문제를 시사한다.
    MS 밴드(Blue~NIR)만 표시(PAN은 광대역이라 별도).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    bands = [1, 2, 3, 4, 5, 6, 7]
    cen = [gains[b]["center"] for b in bands]
    g = [gains[b]["gain"] for b in bands]
    ge = [gains[b]["gain_unc"] for b in bands]
    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    ax.errorbar(cen, g, yerr=ge, fmt="o-", color="#1f77b4", capsize=3, lw=1.5)
    for b, x, y in zip(bands, cen, g):
        ax.annotate(BAND_NAMES[b], (x, y), textcoords="offset points",
                    xytext=(0, 8), fontsize=8, ha="center")
    # PAN은 참고선으로
    ax.axhline(gains[0]["gain"], color="0.5", ls=":", lw=1,
               label=f"PAN gain={gains[0]['gain']:.2e}")
    ax.set_xlabel("band center [nm]")
    ax.set_ylabel("vicarious gain  [TOA reflectance / DN]")
    ax.set_title("Derived vicarious gain spectrum (QA: expect smooth trend)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set_ylim(0, None)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    return path
