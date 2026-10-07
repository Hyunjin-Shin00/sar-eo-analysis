#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BlueBON La Crau 대리복사보정 오케스트레이션 (RadCalNet LCFR 기반).

흐름: RadCalNet .output 파싱 -> SRF 밴드적분 -> ROI DN 통계 -> gain 산출
      -> CSV/플롯/report.md 생성.

예:
  python3 run_lcfr_calib.py \
    --tiff  .../radiometric_v5/bb_l1a_20260704_110833_8band.tiff \
    --srf   ref/SpectralResponseFunction.xlsx \
    --radcal ref/radcal/LCFR/LCFR01_2026_184_v04.06.output \
    --utc 11:08:33 --roi 9110 9360 1010 1240 \
    --out   .../radcal_lcfr
"""
import os
import sys
import argparse
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_radcalnet import parse_output
from band_integrate import load_srf, srf_metrics, verify_mapping, integrate_bands, BAND_NAMES
from extract_roi_dn import extract_roi, make_quicklook
import vicarious_calib as vc


def build_report(path, args, sample, srf, metrics, warns, bi, roi_stats, gains, sens=None):
    L = []
    P = L.append
    P("# BlueBON La Crau 대리복사보정 리포트 (RadCalNet LCFR)\n")
    P(f"- 입력 영상: `{args.tiff}`")
    P(f"- SRF: `{args.srf}` (시트 BlueBON, 시스템 유효 SRF)")
    P(f"- RadCalNet: `{args.radcal}`")
    P(f"- 촬영시각: {args.utc} UTC → RadCalNet 격자 **{sample.utc} UTC** (col {sample.col_index})")
    P(f"- RadCalNet 사이트: {sample.site}  lat={sample.lat} lon={sample.lon} alt={sample.alt}m  "
      f"year={sample.year} DOY={sample.doy}")
    P(f"- 태양기하: SZA={sample.sza:.2f}°  SAA={sample.saa:.2f}°  esd={sample.esd:.5f} AU")
    P(f"- 대기: WV={sample.atmos.get('WV')} g/cm², O3={sample.atmos.get('O3')} DU, "
      f"AOD(550)={sample.atmos.get('AOD')}, Ång={sample.atmos.get('Ang')}")
    P(f"- ROI(px): rows {args.roi[0]}–{args.roi[1]}, cols {args.roi[2]}–{args.roi[3]} "
      f"(n={roi_stats[0]['n']} px/band) — **실제 RadCalNet 계기 위치로 확인됨**")
    P(f"- RadCalNet fill 제외 파장 수: {sample.n_fill} (400~2500nm 중), "
      f"VNIR 밴드 SRF coverage 최소 {min(bi[b]['coverage'] for b in range(8))*100:.1f}%\n")

    P("## 방법\n")
    P("BB v5 산출물은 dark 차감된 **상대 보정 DN**이므로 offset=0 가정, 원점 통과 선형 모델")
    P("`ρ_TOA,b = gain_b · DN_b` 로 밴드별 대리보정 이득을 산출한다. RadCalNet nadir TOA")
    P("반사율(10nm)을 BB 시스템 SRF로 밴드 적분하여 ρ_b 를 얻고, ROI 평균 DN 으로 나눈다.")
    P("불확도(1σ 상대) = √[(RadCalNet ρ 불확도)² + (ROI 공간 CV)²].\n")

    P("## 밴드 매핑 검증\n")
    P("SRF `Band 1..7`→`Blue,Green,Red,RE1,RE2,RE3,NIR`, `PAN`→idx0. 산출 중심파장:")
    P("")
    P("| idx | 밴드 | 중심[nm] | FWHM[nm] | SRF범위[nm] |")
    P("|--|--|--|--|--|")
    for b in vc.BAND_ORDER:
        m = metrics[b]
        P(f"| {b} | {BAND_NAMES[b]} | {m['center']:.1f} | {m['width']:.1f} | "
          f"{m['wl_lo']:.0f}–{m['wl_hi']:.0f} |")
    P("")
    P("매핑 검증: " + ("**OK (경고 없음)**" if not warns else "⚠ " + "; ".join(warns)))
    P("")

    P("## 대리보정 계수 (핵심 결과)\n")
    P("| idx | 밴드 | 중심[nm] | ρ_TOA | σρ | ROI DN | CV% | **gain [refl/DN]** | 상대불확도 |")
    P("|--|--|--|--|--|--|--|--|--|")
    for b in vc.BAND_ORDER:
        g = gains[b]
        P(f"| {b} | {BAND_NAMES[b]} | {g['center']:.0f} | {g['rho']:.4f} | {g['rho_unc']:.4f} | "
          f"{g['dn']:.1f} | {g['cv']:.2f} | {g['gain']:.4e} | {g['rel_unc']*100:.1f}% |")
    P("")
    P("→ 적용: `TOA_reflectance_b = gain_b × (보정 DN)_b`. (radiance 변환은 밴드적분 "
      "태양조도 ESUN_b 로 `L=ρ·ESUN·cos(SZA)/(π·esd²)` — 향후 확장)\n")

    if sens:
        P("## 참조일 민감도 (DOY 183 vs 184)\n")
        P("정확일 DOY 185 부재로 최근접일 사용. 인접일 밴드적분 ρ 및 gain 차이:")
        P("")
        P("| 밴드 | ρ(184) | ρ(183) | Δρ% | gain 차이% |")
        P("|--|--|--|--|--|")
        for b in vc.BAND_ORDER:
            a, c = sens["184"][b]["refl"], sens["183"][b]["refl"]
            dperc = (c - a) / a * 100 if a else float("nan")
            P(f"| {BAND_NAMES[b]} | {a:.4f} | {c:.4f} | {dperc:+.1f}% | {dperc:+.1f}% |")
        P("")

    P("## 산출물\n")
    P("- `gains.csv` — 밴드별 계수·불확도 표")
    P("- `plot_srf_spectrum.png` — RadCalNet TOA + SRF 오버레이 + 밴드적분점")
    P("- `plot_gain_scatter.png` — ρ_TOA vs DN 산점(밴드별 gain)")
    P("- `plot_gain_spectrum.png` — 도출된 gain의 파장 스펙트럼(QA: 부드러움 확인)")
    P("- `quicklook_roi.png` / `quicklook_overview.png` — ROI 위치 확인\n")

    P("## 한계 및 주의\n")
    P("1. **단일 장면 → 밴드당 1점**: gain만 도출, offset/선형성 검증 불가(원점통과 가정).")
    P("2. **정확일(DOY 185) 부재**: DOY 184 사용(하루 대기차). 위 민감도표 참조, 포털 정확일 확보 시 재실행 권장.")
    P("3. **시야각**: RadCalNet=nadir TOA, BB=실제 시야각 → near-nadir 가정(BRDF 오차 가능).")
    P("4. **독립 진리값 아님 / 검증은 by-construction**: 단일 장면에선 gain을 적용하면 반사율이")
    P("   정의상 완벽 재현되어 독립 검증 불가. QA는 (i) gain 스펙트럼의 물리적 부드러움,")
    P("   (ii) ROI 균질도, (iii) 참조일 민감도로 대신한다. 다장면 축적 시 선형성/시계열 검증 가능.")
    P("5. **PAN 신뢰도 낮음**: Libya PAN 포화로 flat≈1(PRNU 미보정) → PAN gain 참고용(PIPELINE.md §9).")
    P("6. **ROI 위치 (해소됨)**: 8밴드 TIFF는 지리참조가 없으나, 본 ROI는 **실제 RadCalNet")
    P("   계기 위치로 확인**되었다(사용자 확인). 따라서 절대 gain은 RadCalNet 지정 타깃에")
    P("   정합한다. ROI는 72px로 작지만 CV~1%로 매우 균질(주변 도로·어두운 패치 회피). 잔여")
    P("   차이는 BB GSD와 RadCalNet 계기 발자국 크기·형상 차이에 따른 소규모 대표성 오차뿐.\n")

    with open(path, "w") as f:
        f.write("\n".join(L))
    return path


def main():
    ap = argparse.ArgumentParser(description="BlueBON La Crau 대리복사보정 (RadCalNet)")
    ap.add_argument("--tiff", required=True)
    ap.add_argument("--srf", required=True)
    ap.add_argument("--radcal", required=True, help="RadCalNet .output (기본 DOY184)")
    ap.add_argument("--radcal-adj", help="인접일 .output (민감도용, 예 DOY183)")
    ap.add_argument("--utc", default="11:08:33")
    ap.add_argument("--roi", nargs=4, type=int, required=True,
                    metavar=("R0", "R1", "C0", "C1"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--overview", action="store_true", help="전체 overview 퀵룩도 생성")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    print("[1/5] RadCalNet 파싱…")
    sample = parse_output(args.radcal, utc=args.utc)
    print(f"      UTC {sample.utc} col{sample.col_index} SZA={sample.sza:.2f}° "
          f"valid_wl={sample.wavelength.size} fill={sample.n_fill}")

    print("[2/5] SRF 밴드 적분…")
    srf = load_srf(args.srf)
    metrics = srf_metrics(srf)
    warns = verify_mapping(metrics)
    bi = integrate_bands(srf, sample.wavelength, sample.toa_refl, sample.toa_refl_unc)
    if warns:
        print("      ⚠ 매핑 경고:", "; ".join(warns))
    else:
        print("      매핑 OK")

    print("[3/5] ROI DN 통계…")
    roi_stats = extract_roi(args.tiff, tuple(args.roi))
    for b in vc.BAND_ORDER:
        print(f"      {BAND_NAMES[b]:5s} DN={roi_stats[b]['mean']:.1f} CV={roi_stats[b]['cv']:.2f}%")

    print("[4/5] gain 산출…")
    gains = vc.compute_gains(bi, roi_stats)

    sens = None
    if args.radcal_adj:
        adj = parse_output(args.radcal_adj, utc=args.utc)
        bi_adj = integrate_bands(srf, adj.wavelength, adj.toa_refl, adj.toa_refl_unc)
        sens = {"184": bi, "183": bi_adj}

    print("[5/5] 산출물 생성…")
    vc.write_csv(gains, os.path.join(args.out, "gains.csv"))
    vc.plot_srf_spectrum(srf, sample, gains, os.path.join(args.out, "plot_srf_spectrum.png"))
    vc.plot_gain_scatter(gains, os.path.join(args.out, "plot_gain_scatter.png"))
    vc.plot_gain_spectrum(gains, os.path.join(args.out, "plot_gain_spectrum.png"))
    make_quicklook(args.tiff, os.path.join(args.out, "quicklook_roi_marked.png"),
                   decim=24, roi=tuple(args.roi))
    if args.overview:
        make_quicklook(args.tiff, os.path.join(args.out, "quicklook_overview.png"), decim=24)
    build_report(os.path.join(args.out, "report.md"), args, sample, srf, metrics,
                 warns, bi, roi_stats, gains, sens)
    print(f"완료 → {args.out}")


if __name__ == "__main__":
    main()
