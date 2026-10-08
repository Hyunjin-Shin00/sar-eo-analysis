#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
하이브리드 절대복사보정: v5 상대보정 DN → 분광복사휘도(spectral radiance) → TOA 반사율.

권장 방식(기존 pipeline.py 보존, 후처리로 절대 스케일만 부여):
    DN_corr   = v5 산출물 (raw−dark)·flat−δ, 정합·flip 완료된 보정 DN (uint16)
    radiance  = DN_corr · gain_band                  # 밴드당 스칼라(컬럼별 아님) → PRNU 이중처리 회피
    L_spec    = radiance / band_width[b]             # per-nm 분광복사휘도
    TOAR      = π·L_spec / (F0_b · cosθs) / d_r       # d_r=1+0.033cos(2π·doy/365)=1/d² → ÷d_r = ×d²(물리적으로 정확)

- gain_band 기본: FM1 실험실 표(sub/FM1_mean_output_PRNU_check.csv)의 밴드평균 gain
  (BAND×Line rate×TDI 로 조회, 컬럼별 회귀계수의 평균). RadCalNet은 순수 검증기준으로 남김.
- F0_b: Thuillier(2003) 태양 스펙트럼 × BlueBON SRF 밴드적분 (02_L_to_TOAR.py 방식, *10 단위환산).
- 02_L_to_TOAR.py의 거리인자(×d_r²)는 물리적으로 뒤집힌 것으로 판단 → 여기선 ÷d_r 사용.

밴드 index 0..7 = PAN,Blue,Green,Red,RE1,RE2,RE3,NIR.
"""
import os
import re
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from band_integrate import load_srf, SRF_BAND_COLS, BAND_NAMES  # noqa: E402

# ---- 상수 -------------------------------------------------------------------
FM1_CSV = "<WORK_ROOT>/prep/src/03_code/sub/FM1_mean_output_PRNU_check.csv"
THUILLIER = "<WORK_ROOT>/prep/src/03_code/sub/Thuillier_F0.dat"
BAND_WIDTH = {0: 250, 1: 65, 2: 35, 3: 30, 4: 15, 5: 15, 6: 20, 7: 115}  # nm (01_DN_to_L.py)
# La Crau 촬영 실제 설정: band 0..7 순 TDI, line rate (사용자 확인).
# 두 La Crau 장면(20260704, 20260528) 동일. line rate 667 ≈ FM1표의 666 (동일 nominal).
DEFAULT_TDI = {0: 2, 1: 4, 2: 8, 3: 8, 4: 16, 5: 16, 6: 16, 7: 4}
DEFAULT_LP = 666   # 표에 667 없음 → 최근접 666 사용


# ---- FM1 밴드평균 gain -------------------------------------------------------
def compute_fm1_band_gains(csv=FM1_CSV, tdi=DEFAULT_TDI, lp=DEFAULT_LP, bands=range(8)):
    """FM1 참조표에서 밴드평균 gain(radiance/DN)과 intercept를 산출(01_DN_to_L.py 로직 재현)."""
    import pandas as pd
    from sklearn.linear_model import LinearRegression
    df = pd.read_csv(csv)
    d2 = df.to_numpy()
    gains, intercepts = {}, {}
    for b in bands:
        bi = "PAN" if b == 0 else f"MS{b}"
        t = tdi[b]
        cutch = np.where((df["BAND"] == bi) & (df["Line rate"] == lp) & (df["TDI"] == t))[0]
        cutch0 = np.where((df["BAND"] == bi) & (df["Line rate"] == lp) & (df["TDI"] == t)
                          & (df["lmap_level"] == 0))[0]
        I = d2[cutch, 6].reshape(-1, 1)          # radiance (band-integrated)
        dn = d2[cutch, 10:]                        # per-column DN
        i = 0
        for i in range(len(cutch) - 1):            # 선두 plateau 트림 (01과 동일)
            if d2[cutch[i + 1], 9] - d2[cutch[i], 9] != 0:
                break
        if i == 0:
            Ich, dnch = I[:-1], dn[:-1]
        else:
            Ich, dnch = I[(i + 1):-1], dn[(i + 1):-1]
        dark = d2[cutch0, 10:]
        dnd = dnch - dark
        coefs, ints = [], []
        for c in range(dnd.shape[1]):
            m = LinearRegression().fit(dnd[:, c].reshape(-1, 1), Ich)
            coefs.append(m.coef_[0, 0]); ints.append(m.intercept_[0])
        gains[b] = float(np.mean(coefs))
        intercepts[b] = float(np.mean(ints))
    return gains, intercepts


# ---- Thuillier F0 → 밴드 F0 --------------------------------------------------
def read_thuillier_f0(path=THUILLIER):
    rows = []
    for line in open(path, "rt", encoding="Latin-1").read().splitlines():
        s = line.strip()
        if s == "" or re.match(r"^[/!]", s):
            continue
        rows.append(s.split())
    a = np.array(rows, float)
    return a[:, 0], a[:, 1]                        # wave[nm], F0


def compute_band_F0(srf, thuillier=THUILLIER):
    """SRF × Thuillier F0(*10) 밴드적분 → 밴드별 분광조도 F0_b (02_L_to_TOAR.py 방식)."""
    wl_t, f0_t = read_thuillier_f0(thuillier)
    f0_on_srf = np.interp(srf["wl"], wl_t, f0_t * 10.0)
    F0 = {}
    for b in SRF_BAND_COLS:
        r = srf[b]
        F0[b] = float(np.sum(f0_on_srf * r) / np.sum(r))
    return F0


# ---- 변환 -------------------------------------------------------------------
def earth_sun_flux_factor(doy):
    """d_r = 1+0.033cos(2π·doy/365) = (1AU/d)² (일사 플럭스 인자)."""
    return 1.0 + 0.033 * np.cos(2.0 * np.pi * doy / 365.0)


def dn_to_spectral_radiance(dn, gain_b, bw_b):
    return dn.astype(np.float64) * gain_b / bw_b


def spectral_radiance_to_toar(L, F0_b, sza_deg, doy):
    """TOAR = π·L / (F0·cosθs) / d_r  (÷d_r = ×d², 물리적으로 정확한 거리보정)."""
    cth = np.cos(np.radians(sza_deg))
    d_r = earth_sun_flux_factor(doy)
    return np.pi * L / (F0_b * cth) / d_r


# ---- 편의: 밴드 스칼라로 ROI/전체 변환 ---------------------------------------
def convert_bands(dn_by_band, gains, F0, sza_deg, doy, bw=BAND_WIDTH):
    """dn_by_band: dict[b]=DN(ndarray or scalar). 반환 radiance/TOAR dict."""
    rad, toar = {}, {}
    for b in dn_by_band:
        L = dn_to_spectral_radiance(np.asarray(dn_by_band[b], float), gains[b], bw[b])
        rad[b] = L
        toar[b] = spectral_radiance_to_toar(L, F0[b], sza_deg, doy)
    return rad, toar


def convert_scene(tiff_8band, out_path_radiance, sza_deg, doy, srf_path,
                  out_path_toar=None, tdi=DEFAULT_TDI, lp=DEFAULT_LP):
    """v5 8밴드 DN TIFF → 8밴드 스택 분광복사휘도(float32) [+ 8밴드 TOAR(float32)].
    DN 파일과 동일 형식(8밴드 스택, band순 0..7, INTERLEAVE=BAND). 밴드별 스트리밍(저메모리)."""
    import rasterio
    from rasterio.transform import Affine
    gains, _ints = compute_fm1_band_gains(tdi=tdi, lp=lp)
    srf = load_srf(srf_path)
    F0 = compute_band_F0(srf)

    src = rasterio.open(tiff_8band)
    assert src.count == 8, f"8밴드 아님: count={src.count}"
    H, W = src.height, src.width
    prof = dict(driver="GTiff", width=W, height=H, count=8, dtype="float32",
                transform=Affine(1, 0, 0, 0, -1, 0), crs=None,
                compress="deflate", predictor=3, interleave="band")

    dst_L = rasterio.open(out_path_radiance, "w", **prof)
    dst_T = rasterio.open(out_path_toar, "w", **prof) if out_path_toar else None
    summary = []
    for b in range(8):
        dn = src.read(b + 1).astype(np.float64)
        L = dn * gains[b] / BAND_WIDTH[b]                        # 분광복사휘도 W/m²/sr/nm
        dst_L.write(L.astype(np.float32), b + 1)
        row = dict(band=BAND_NAMES[b], gain=gains[b], L_mean=float(np.nanmean(L)))
        if dst_T is not None:
            toar = spectral_radiance_to_toar(L, F0[b], sza_deg, doy).astype(np.float32)
            dst_T.write(toar, b + 1)
            row["TOAR_mean"] = float(np.nanmean(toar))
        summary.append(row)
        del dn, L
    for b in range(8):
        dst_L.set_band_description(b + 1, BAND_NAMES[b])
        if dst_T is not None:
            dst_T.set_band_description(b + 1, BAND_NAMES[b])
    dst_L.close(); src.close()
    if dst_T is not None:
        dst_T.close()
    return summary


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="v5 DN → 분광복사휘도/TOAR (또는 gain/F0 점검)")
    ap.add_argument("--srf", default="<WORK_ROOT>/working/radiometric_correction/ref/SpectralResponseFunction.xlsx")
    ap.add_argument("--lp", type=int, default=DEFAULT_LP)
    ap.add_argument("--convert", help="v5 8밴드 DN TIFF 경로 (지정 시 8밴드 radiance/TOAR 산출)")
    ap.add_argument("--out-radiance", help="8밴드 radiance float32 출력 경로")
    ap.add_argument("--out-toar", help="8밴드 TOAR float32 출력 경로(선택)")
    ap.add_argument("--sza", type=float, help="태양천정각(deg)")
    ap.add_argument("--doy", type=int, help="scene day-of-year")
    ap.add_argument("--tdi", default=None, help="band0..7 TDI 콤마구분 (기본 La Crau 2,4,8,8,16,16,16,4)")
    a = ap.parse_args()

    if a.convert:
        assert a.out_radiance and a.sza is not None and a.doy, "--convert 시 --out-radiance/--sza/--doy 필요"
        tdi = DEFAULT_TDI if a.tdi is None else {i: int(x) for i, x in enumerate(a.tdi.split(","))}
        s = convert_scene(a.convert, a.out_radiance, a.sza, a.doy, a.srf,
                          out_path_toar=a.out_toar, tdi=tdi, lp=a.lp)
        for r in s:
            print(f"  {r['band']:5s} gain={r['gain']:.4e} L_mean={r['L_mean']:.4f}"
                  + (f" TOAR_mean={r.get('TOAR_mean'):.4f}" if 'TOAR_mean' in r else ""))
        print("→ radiance:", a.out_radiance, "| toar:", a.out_toar)
    else:
        gains, ints = compute_fm1_band_gains(lp=a.lp)
        srf = load_srf(a.srf); F0 = compute_band_F0(srf)
        print(f"{'band':6s}{'TDI':>4s}{'gain(rad/DN)':>14s}{'intercept':>12s}{'band_width':>11s}{'F0_b':>10s}")
        for b in range(8):
            print(f"{BAND_NAMES[b]:6s}{DEFAULT_TDI[b]:4d}{gains[b]:14.5e}{ints[b]:12.4f}"
                  f"{BAND_WIDTH[b]:11d}{F0[b]:10.4f}")
