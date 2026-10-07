# -*- coding: utf-8 -*-
"""수령자용 자기검증 — 이 폴더만으로 리드타임 재계산이 되는지 확인. usage: python3 00_selftest.py
의존: numpy 하나뿐. 성공하면 README §3 코드를 그대로 쓰면 됩니다."""
import os, sys, glob, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SER = os.path.join(HERE, "01_input_series")
RES = os.path.join(HERE, "02_rules_results")
FEATS = ["cum1", "cum1a", "cum2", "cum2a", "cumF", "cumFa",
         "vel", "vela", "vtr", "dv", "ivfrac", "ivimm"]
DAYS = 365.25
KR = {"Busan_Sasang_Hadan": "사상", "Yangyang": "양양", "Seoul_Gangdong": "강동",
      "Gyeonggi_Gwangmyeong": "광명", "Incheon_Songdo_DSC": "송도",
      "Seoul_Seodaemun": "서대문", "Busan_Mandeok_Centum": "만덕"}


def first_fire(F, conds, K):
    """conds=[(지표index, 임계)] AND · K회 연속 → 최초 성립 에폭 index(없으면 -1)"""
    ok = np.ones(F.shape[1], bool)
    for f, th in conds:
        ok &= (np.nan_to_num(F[f], nan=-1e18) >= th)
    run = 0
    for i, h in enumerate(ok):
        run = run + 1 if h else 0
        if run >= K:
            return i
    return -1


def evaluate(A, conds, K):
    leads = []
    for a in A:
        j = first_fire(a["F"], conds, K)
        leads.append((a["t_acc"] - a["t"][j]) * DAYS if j >= 0 else None)
    d = [x for x in leads if x is not None]
    det = len(d) / len(A)
    med = float(np.median(d)) if d else None
    viol = sum(1 for a, x in zip(A, leads)
               if x is not None and x < a["gap_d"] - 0.01)
    return det, med, leads, viol


def bg_fire_rate(B, conds, K):
    return sum(1 for (t, F) in B if first_fire(F, conds, K) >= 0) / len(B)


def main():
    fail = 0
    print("=" * 78)
    print("[1/4] 파일 존재 확인")
    n = len(glob.glob(os.path.join(SER, "*__t2k.npz")))
    print(f"  01_input_series/*__t2k.npz : {n}개 " + ("OK" if n == 7 else "★7개여야 함"))
    fail += (n != 7)
    for f in ("op_rule.json", "gate_op.json", "verify/last_section.json"):
        p = os.path.join(RES, f)
        print(f"  02_rules_results/{f:26s}: " + ("OK" if os.path.exists(p) else "★없음"))
        fail += (not os.path.exists(p))

    print("\n[2/4] npz 구조 확인 (사상)")
    z = np.load(os.path.join(SER, "Busan_Sasang_Hadan__t2k.npz"), allow_pickle=True)
    A, B = list(z["A"]), list(z["B"])
    a = A[0]
    print(f"  A(사고) {len(A)}건 · B(배경) {len(B)}점")
    print(f"  A[0] keys : {sorted(a.keys())}")
    print(f"  A[0].F shape {a['F'].shape} (12지표 × 에폭) · t {a['t'].shape}")
    ok_shape = a["F"].shape[0] == 12 and a["F"].shape[1] == len(a["t"])
    print("  형상 정합 : " + ("OK" if ok_shape else "★불일치"))
    fail += (not ok_shape)

    print("\n[3/4] as-of 무결성 — 사고 시계열에 사고일 이후 에폭이 없어야 함")
    tot = bad = 0
    for p in sorted(glob.glob(os.path.join(SER, "*.npz"))):
        for x in list(np.load(p, allow_pickle=True)["A"]):
            tot += 1
            if len(x["t"]) and float(np.max(x["t"])) > x["t_acc"]:
                bad += 1
    print(f"  사고 시계열 {tot}개 중 위반 {bad}개 : " + ("OK" if bad == 0 else "★누출"))
    fail += (bad != 0)

    print("\n[4/4] 기준선 재계산 (cum1 ≥ 20mm · K=2) — gap 위반 0이어야 함")
    print(f"  {'지역':5s}{'사고':>4s}{'배경':>5s}{'탐지':>8s}{'중앙리드':>10s}{'배경발화':>9s}{'gap위반':>8s}")
    tv = 0
    for reg, kr in KR.items():
        p = os.path.join(SER, f"{reg}__t2k.npz")
        if not os.path.exists(p):
            continue
        z = np.load(p, allow_pickle=True)
        A, B = list(z["A"]), list(z["B"])
        det, med, _, viol = evaluate(A, [(FEATS.index("cum1"), 20.0)], 2)
        fp = bg_fire_rate(B, [(FEATS.index("cum1"), 20.0)], 2)
        tv += viol
        print(f"  {kr:5s}{len(A):>4d}{len(B):>5d}{100*det:>7.1f}%"
              f"{('-' if med is None else f'{med:.0f}일'):>10s}{100*fp:>8.1f}%{viol:>8d}")
    print(f"  gap 위반 합계 {tv} : " + ("OK" if tv == 0 else "★위반 발생"))
    fail += (tv != 0)

    print("\n" + "=" * 78)
    if fail == 0:
        print("전부 통과 — README §3 코드로 바로 재계산하십시오.")
        print("참고: 위 기준선(단순 누적침하 조건)은 중앙 리드가 800~1900일로 매우 깁니다.")
        print("      누적침하 지표가 단조증가해 임계를 한 번 넘으면 계속 참이 되기 때문입니다(README §6).")
        print("      개선 방향은 증가량(_dN)·표준화(_zN) 파생지표입니다.")
    else:
        print(f"★ {fail}개 항목 실패 — 파일 누락 또는 손상 여부를 확인하십시오(MANIFEST.json의 md5 대조).")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
