#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BlueBON SRF 파싱 + RadCalNet TOA 스펙트럼의 밴드 적분.

SRF 소스: ref/SpectralResponseFunction.xlsx (시트 BlueBON)
  - 파장 400~1000nm @ 1nm (내림차순 저장, 601행)
  - 우측 블록 "Total optical transmission x QE x ff [%]" = 시스템 유효 SRF
    (필터 x 광학 x QE x fill-factor). 이 값을 상대 분광응답으로 사용.
  - 컬럼 위치(0-based): 14=wave(nm), 15..21=Band1..7, 22=PAN

밴드 매핑(병합 8밴드 index):
  SRF Band 1..7 -> 1=Blue,2=Green,3=Red,4=RE1,5=RE2,6=RE3,7=NIR ; PAN -> 0
"""
import numpy as np
import pandas as pd

# SRF 시트 컬럼 이름(pandas 기본) -> 병합 밴드 index / 이름
#   우측 시스템 SRF 블록: 파장=col14, Band1..7=col15..21, PAN=col22
SRF_WL_COL = 14
SRF_BAND_COLS = {          # merged band index -> sheet column position
    1: 15,  # Blue   (SRF Band 1)
    2: 16,  # Green  (SRF Band 2)
    3: 17,  # Red    (SRF Band 3)
    4: 18,  # RE1    (SRF Band 4)
    5: 19,  # RE2    (SRF Band 5)
    6: 20,  # RE3    (SRF Band 6)
    7: 21,  # NIR    (SRF Band 7)
    0: 22,  # PAN
}
BAND_NAMES = {0: "PAN", 1: "Blue", 2: "Green", 3: "Red",
              4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
# 매핑 검증용 대략 기대 중심파장 [nm]
EXPECTED_CENTER = {0: 650, 1: 475, 2: 560, 3: 660, 4: 705, 5: 740, 6: 783, 7: 842}


def load_srf(xlsx_path, sheet="BlueBON"):
    """SRF xlsx를 파싱하여 {'wl': ndarray(오름차순), band_idx: ndarray} 딕셔너리 반환.

    반환 SRF는 음수/노이즈를 0으로 클립하고 파장 오름차순으로 정렬한 시스템 응답(단위 무관, 상대값).
    """
    raw = pd.read_excel(xlsx_path, sheet_name=sheet, header=None)
    wl_col = raw.iloc[:, SRF_WL_COL]
    wl = pd.to_numeric(wl_col, errors="coerce")
    mask = wl.notna() & (wl >= 300) & (wl <= 1100)
    idx = np.where(mask.values)[0]
    wl_v = wl.values[idx].astype(float)

    srf = {"wl": wl_v}
    for b, col in SRF_BAND_COLS.items():
        resp = pd.to_numeric(raw.iloc[:, col], errors="coerce").values[idx].astype(float)
        resp = np.nan_to_num(resp, nan=0.0)
        resp = np.clip(resp, 0.0, None)          # 음수 노이즈 제거
        srf[b] = resp

    # 파장 오름차순 정렬
    order = np.argsort(srf["wl"])
    srf["wl"] = srf["wl"][order]
    for b in SRF_BAND_COLS:
        srf[b] = srf[b][order]
    return srf


def srf_metrics(srf):
    """밴드별 SRF 가중 중심파장/대역폭(FWHM 근사)/유효범위를 계산."""
    wl = srf["wl"]
    out = {}
    for b in SRF_BAND_COLS:
        r = srf[b]
        s = r.sum()
        if s <= 0:
            out[b] = dict(center=np.nan, width=np.nan, wl_lo=np.nan, wl_hi=np.nan)
            continue
        center = float((wl * r).sum() / s)
        # FWHM: 최대의 50% 이상 구간 폭
        half = r.max() * 0.5
        above = wl[r >= half]
        fwhm = float(above.max() - above.min()) if above.size else np.nan
        # 유효 범위: 최대의 1% 이상
        thr = wl[r >= r.max() * 0.01]
        out[b] = dict(center=center, width=fwhm,
                      wl_lo=float(thr.min()), wl_hi=float(thr.max()))
    return out


def verify_mapping(metrics, tol=40.0):
    """산출 중심파장을 기대값과 대조하여 매핑 타당성 경고 리스트를 반환."""
    warns = []
    # 순서 단조성: Blue<Green<Red<RE1<RE2<RE3<NIR
    ms = [metrics[b]["center"] for b in (1, 2, 3, 4, 5, 6, 7)]
    if not all(np.diff(ms) > 0):
        warns.append(f"밴드 중심파장 단조증가 위반: {['%.0f'%m for m in ms]}")
    for b, exp in EXPECTED_CENTER.items():
        c = metrics[b]["center"]
        if np.isfinite(c) and abs(c - exp) > tol:
            warns.append(f"{BAND_NAMES[b]}(idx{b}) center={c:.0f}nm, 기대~{exp}nm "
                         f"(차이 {c-exp:+.0f})")
    return warns


def integrate_bands(srf, wl_toa, refl, refl_unc=None):
    """RadCalNet TOA 스펙트럼을 SRF로 밴드 적분.

    wl_toa/refl : RadCalNet 파장[nm]/TOA 반사율 (fill 이미 제외됨, 임의 간격)
    반환: dict[band_idx] = {'refl','unc','center','width','coverage'}
      coverage = SRF 응답 중 RadCalNet 유효 파장이 덮은 비율(0~1). 낮으면 신뢰 저하.
    """
    wl_srf = srf["wl"]
    metrics = srf_metrics(srf)
    # RadCalNet를 SRF 1nm 격자에 선형보간(범위 밖은 NaN)
    order = np.argsort(wl_toa)
    wl_s, refl_s = wl_toa[order], refl[order]
    refl_i = np.interp(wl_srf, wl_s, refl_s, left=np.nan, right=np.nan)
    if refl_unc is not None:
        unc_s = refl_unc[order]
        unc_i = np.interp(wl_srf, wl_s, unc_s, left=np.nan, right=np.nan)
    else:
        unc_i = np.full_like(wl_srf, np.nan)

    out = {}
    for b in SRF_BAND_COLS:
        r = srf[b]
        valid = np.isfinite(refl_i) & (r > 0)
        w = r[valid]
        total_w = r.sum()
        cov = float(w.sum() / total_w) if total_w > 0 else 0.0
        if w.sum() <= 0:
            out[b] = dict(refl=np.nan, unc=np.nan, coverage=0.0, **metrics[b])
            continue
        rho = float((w * refl_i[valid]).sum() / w.sum())
        # 불확도: 상관 가정 없이 가중평균(보수적으로 밴드 내 완전상관 근사 -> 가중평균)
        if np.isfinite(unc_i[valid]).all():
            unc = float((w * unc_i[valid]).sum() / w.sum())
        else:
            unc = np.nan
        out[b] = dict(refl=rho, unc=unc, coverage=cov, **metrics[b])
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="SRF 파싱 + 밴드 적분 점검")
    ap.add_argument("--srf", default="ref/SpectralResponseFunction.xlsx")
    ap.add_argument("--radcal", default="ref/radcal/LCFR/LCFR01_2026_184_v04.06.output")
    ap.add_argument("--utc", default="11:08:33")
    a = ap.parse_args()

    srf = load_srf(a.srf)
    metrics = srf_metrics(srf)
    print("=== SRF 밴드 metrics ===")
    for b in (0, 1, 2, 3, 4, 5, 6, 7):
        m = metrics[b]
        print(f"  idx{b} {BAND_NAMES[b]:5s}: center={m['center']:6.1f}nm "
              f"FWHM={m['width']:5.1f}nm  range={m['wl_lo']:.0f}~{m['wl_hi']:.0f}nm")
    warns = verify_mapping(metrics)
    print("=== 매핑 검증 ===")
    print("  OK (경고 없음)" if not warns else "\n".join("  ! " + w for w in warns))

    from parse_radcalnet import parse_output
    s = parse_output(a.radcal, utc=a.utc)
    bi = integrate_bands(srf, s.wavelength, s.toa_refl, s.toa_refl_unc)
    print("=== 밴드 적분 TOA 반사율 ===")
    for b in (0, 1, 2, 3, 4, 5, 6, 7):
        d = bi[b]
        print(f"  idx{b} {BAND_NAMES[b]:5s}: rho={d['refl']:.4f} "
              f"±{d['unc']:.4f}  coverage={d['coverage']*100:.1f}%")
