#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
지속 가산 잔차 δ_persistent 생성 (dark 보강용).
  flat 보정 후에도 장면간 반복되는 열 고정 줄무늬(가산) = 여러 바다 장면의
  '어두운 영역 열잔차 고주파'를 평균 -> 검출기 고정패턴만 남고 장면성분 상쇄.
  적용: corrected = (raw - dark)*flat - δ[col]   (raw 검출기-열 공간, 정합 이전)

출력: {rn}_delta_persistent.dat / .tiff  (밴드별 4096, 고주파 열패턴)
"""
import os
import numpy as np
import tifffile

REF = "/mnt/e/bkchoi/prep/data/correction_ref_260606"
DATA = "/mnt/e/bkchoi/prep/data"
# δ 생성용 바다(어두운 물) 포함 2026 장면
SCENES = [
    ("20260712_Strait_of_Hormuz_or_UAE_border", "260712_072621"),
    ("20260713_GBR_5_Australia",                "260713_005349"),
    ("20260714_Khark_Island_iran",              "260714_080256"),
    ("20260721_Sohae_Satellite_Launching_Station_north_korea", "260721_030713"),
    ("20260721_Bushehr_Nuclear_Power_plant_Iran", "260721_075224"),
]
BANDS = list(range(8))
def rn(n): return "PAN" if n == 0 else f"MS{n}"
def sm(x, k=51):
    ker = np.ones(k)/k; xp = np.pad(x, k//2, mode="reflect"); return np.convolve(xp, ker, mode="valid")[:len(x)]
def hp(x, k=51): return x - sm(x, k)


def scene_residual(n, d, st):
    """장면의 flat 보정 후 어두운영역 열잔차 고주파 (raw 열공간)."""
    dref = tifffile.imread(os.path.join(REF, f"{rn(n)}_dark_ref.tiff")).astype(np.float64).ravel()
    flat = np.loadtxt(os.path.join(REF, f"{rn(n)}_prnu_flat_coef.dat"))
    raw = tifffile.imread(os.path.join(DATA, d, f"{st}_{n}_gray.tiff")).astype(np.float64)
    corr = (raw - dref[None, :]) * flat[None, :]
    rm = corr.mean(axis=1)
    dk = corr[rm <= np.percentile(rm, 12)]                 # 어두운(바다) 영역
    return hp(np.median(dk, axis=0))                        # 고주파 열패턴


def build_delta(n, scenes):
    return np.mean([scene_residual(n, d, st) for d, st in scenes], axis=0)


def main():
    print("=== δ_persistent 생성 + leave-one-out 교차검증 (NIR 예시로 검증) ===")
    for n in BANDS:
        # 전 장면 평균 δ (배포용)
        delta = build_delta(n, SCENES)
        tifffile.imwrite(os.path.join(REF, f"{rn(n)}_delta_persistent.tiff"),
                         delta.astype(np.float32).reshape(1, -1))
        with open(os.path.join(REF, f"{rn(n)}_delta_persistent.dat"), "w") as f:
            f.write(f"# {rn(n)} persistent additive residual (DSNU 보강, high-freq)\n")
            for v in delta: f.write("%.7f\n" % v)
        # leave-one-out 검증: 각 장면을 나머지로 만든 δ로 제거 -> 어두운영역 stripe 감소
        red = []
        for i, (d, st) in enumerate(SCENES):
            others = [s for j, s in enumerate(SCENES) if j != i]
            dlo = build_delta(n, others)                    # held-out δ
            r = scene_residual(n, d, st)                    # 그 장면 잔차(고주파)
            before = r.std(); after = (r - dlo).std()
            red.append((before, after))
        red = np.array(red)
        print("  %-4s δ std=%.3f | held-out 어두운영역 stripe: 평균 %.3f -> %.3f (%.0f%%↓)" % (
            rn(n), delta.std(), red[:, 0].mean(), red[:, 1].mean(),
            (1 - red[:, 1].mean()/red[:, 0].mean())*100))
    print("DONE ->", REF)


if __name__ == "__main__":
    main()
