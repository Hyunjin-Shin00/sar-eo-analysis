#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
밴드별 적응형 δ_persistent 재생성.
  - 각 밴드마다 held-out(leave-one-out)으로 최적 high-pass 창 Whp 자동 선택.
    * 넓은 밴딩이 '지속적'인 밴드(Blue/Green 등) -> 큰 Whp (넓은 성분 포함)
    * 넓은 성분이 '장면(바다)'인 밴드(Red/NIR 등) -> 작은 Whp (고주파만; 실해양 보존)
  - 선택 기준: held-out 잔차 열프로파일의 열 비균일 std(hp 1601, =보이는 열구조) 최소화.
  - δ = 5개 바다 장면의 hp(profile, Whp) 평균 (장면성분 상쇄, 지속 검출기패턴만 잔존).
출력: {rn}_delta_persistent.dat / .tiff  (기존 덮어씀)
"""
import os
import numpy as np
import tifffile

REF = "/mnt/e/bkchoi/prep/data/correction_ref_260606"
DATA = "/mnt/e/bkchoi/prep/data"
SCENES = [
    ("Hormuz",  "20260712_Strait_of_Hormuz_or_UAE_border", "260712_072621"),
    ("GBR",     "20260713_GBR_5_Australia",                "260713_005349"),
    ("Khark",   "20260714_Khark_Island_iran",              "260714_080256"),
    ("Sohae",   "20260721_Sohae_Satellite_Launching_Station_north_korea", "260721_030713"),
    ("Bushehr", "20260721_Bushehr_Nuclear_Power_plant_Iran","260721_075224"),
]
CAND = [51, 151, 401, 801, 1601]
BANDS = list(range(8))
def rn(n): return "PAN" if n == 0 else f"MS{n}"
def sm(x, k):
    if k <= 1: return x.copy()
    ker = np.ones(k)/k; xp = np.pad(x, k//2, mode="reflect"); return np.convolve(xp, ker, mode="valid")[:len(x)]
def hp(x, k): return x - sm(x, k)
def bp(x, lo, hi): return sm(x, lo) - sm(x, hi)


def sea_profile(n, d, st, dref, flat):
    raw = tifffile.imread(os.path.join(DATA, d, f"{st}_{n}_gray.tiff")).astype(np.float64)
    rm = raw.mean(axis=1)
    return np.median(((raw - dref[None, :]) * flat[None, :])[rm <= np.percentile(rm, 12)], axis=0)


def main():
    print("=== 밴드별 적응형 δ 재생성 (held-out 창 선택) ===")
    for n in BANDS:
        dref = tifffile.imread(os.path.join(REF, f"{rn(n)}_dark_ref.tiff")).astype(np.float64).ravel()
        flat = np.loadtxt(os.path.join(REF, f"{rn(n)}_prnu_flat_coef.dat"))
        prof = {nm: sea_profile(n, d, st, dref, flat) for nm, d, st in SCENES}   # 1회 로드/캐시
        names = list(prof)
        # 창 선택: LOO 평균 잔차(hp1601 std) 최소
        def loo_metric(Whp):
            errs = []
            for tst in names:
                others = [prof[o] for o in names if o != tst]
                delta = np.mean([hp(o, Whp) for o in others], axis=0)
                errs.append(hp(prof[tst] - delta, 1601).std())
            return np.mean(errs)
        base = np.mean([hp(prof[t], 1601).std() for t in names])   # δ 없을 때
        scores = {W: loo_metric(W) for W in CAND}
        bestW = min(scores, key=scores.get)
        # 최종 δ (전 장면, bestW)
        delta = np.mean([hp(prof[t], bestW) for t in names], axis=0)
        tifffile.imwrite(os.path.join(REF, f"{rn(n)}_delta_persistent.tiff"), delta.astype(np.float32).reshape(1, -1))
        with open(os.path.join(REF, f"{rn(n)}_delta_persistent.dat"), "w") as f:
            f.write(f"# {rn(n)} persistent additive residual (adaptive Whp={bestW})\n")
            for v in delta: f.write("%.7f\n" % v)
        # Hormuz/GBR held-out 검증 (fine 1-50, broad 200-800)
        rep = {}
        for tst in ("Hormuz", "GBR"):
            others = [prof[o] for o in names if o != tst]
            dlo = np.mean([hp(o, bestW) for o in others], axis=0)
            r = prof[tst] - dlo
            rep[tst] = (bp(prof[tst],1,50).std(), bp(r,1,50).std(), bp(prof[tst],200,800).std(), bp(r,200,800).std())
        print("  %-4s Whp=%-4d (base hp1601 %.2f-> %.2f) | Hormuz 미세%.2f→%.2f 넓은%.2f→%.2f | GBR 미세%.2f→%.2f 넓은%.2f→%.2f" % (
            rn(n), bestW, base, scores[bestW],
            *rep["Hormuz"], *rep["GBR"]))
    print("DONE (δ 덮어씀) ->", REF)


if __name__ == "__main__":
    main()
