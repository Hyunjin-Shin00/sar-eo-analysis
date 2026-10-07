#!/usr/bin/env python3
"""주소(지번) → 공장등록현황 업종명 → 한국표준산업분류(KSIC 11차) 대·중분류 연결.

연결 사슬:  건물/주소 ─①공간중첩→ 필지(PNU) ─②PNU해석→ 지번 ─③공장등록현황→ 업종명 ─④KSIC연계표→ 표준분류
매칭 단위는 개별 건물이 아니라 '필지(지번)'. 한 필지에 공장이 여럿이면 업종도 여럿 나온다.

입력
- 공장등록현황 CSV (cp949, 10컬럼; data.go.kr 「대구광역시_제조업체(공장등록업체)현황」)
- KSIC 11차 연계표 정제본 CSV (utf-8-sig; 대·중·소·세·세세분류 코드/명 10컬럼)

사용
  python ksic_link.py <factory.csv> <ksic.csv> "대구 달서구 호산동 702-5"     # 지번 1건 조회
  python ksic_link.py <factory.csv> <ksic.csv> --coverage 성서                # 단지 전체 매칭률

함정(실측)
1. 지번이 '702-5번지 (3차단지79B 7-1L)'처럼 꼬리표가 붙어 정확일치는 0건 → 본번-부번까지만 정규화해 부분매칭
2. 복수업종은 '… 외 N 종' 꼴 → KSIC 매칭 전 제거
3. 공백 차이('자동측정' vs '자동 측정') → 공백 무시 비교
4. 필지/대장에 대응 안 되는 건물은 억지 매칭 금지 → '업종 미상'
"""
import argparse
import re
from collections import Counter

import pandas as pd


def norm(s):
    return re.sub(r"\s+", "", str(s))


def load(fac_path, ksic_path):
    fac = pd.read_csv(fac_path, encoding="cp949", dtype=str).fillna("")
    ksic = pd.read_csv(ksic_path, dtype=str).fillna("")
    key = lambda col: dict(zip(ksic[col].map(norm),
                               zip(ksic["대분류코드"], ksic["중분류코드"], ksic["중분류명"])))
    return fac, key("세세분류명"), key("세분류명")   # 일부 업종명은 세분류 레벨


def parse_jibun(addr):
    m = re.search(r"([가-힣]+동)\s*(\d+)(?:-(\d+))?", addr)
    if not m:
        return None
    return m.group(1), f"{int(m.group(2))}-{int(m.group(3) or 0)}"


def lookup_upjong(fac, dong, bunji):
    # 부번 0 은 원문에 '702번지' 처럼 부번 없이 적히므로 본번만으로 찾는다
    b = bunji[:-2] if bunji.endswith("-0") else bunji
    pat = re.compile(rf"{re.escape(dong)}\s*{re.escape(b)}(?:번지|[^0-9-]|$)")
    hit = fac[fac["공장대표주소(지번)"].str.contains(pat, na=False)]
    return [(r["회사명"], r["업종명"]) for _, r in hit.iterrows()]


def upjong_to_ksic(upjong, n2k, se2k):
    base = re.sub(r"\s*외\s*\d+\s*종\s*$", "", upjong).strip()
    hit = n2k.get(norm(base)) or se2k.get(norm(base))
    if not hit:
        return base, None
    dae, jung, jungnm = hit
    return base, f"{dae}{jung} {jungnm}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("factory_csv"); ap.add_argument("ksic_csv")
    ap.add_argument("address", nargs="?")
    ap.add_argument("--coverage", help="단지명 부분문자열 (예: 성서) — 해당 단지 업종의 KSIC 매칭률")
    a = ap.parse_args()
    fac, n2k, se2k = load(a.factory_csv, a.ksic_csv)

    if a.address:
        dong, bunji = parse_jibun(a.address)
        hits = lookup_upjong(fac, dong, bunji)
        print(f"{dong} {bunji}: 등록 공장 {len(hits)}개")
        for comp, up in hits:
            print(f"  {comp} | {up} → {upjong_to_ksic(up, n2k, se2k)[1]}")

    if a.coverage:
        sub = fac[fac["단지명"].str.contains(a.coverage, na=False)]
        res = [upjong_to_ksic(u, n2k, se2k)[1] for u in sub["업종명"]]
        ok = sum(r is not None for r in res)
        print(f"[{a.coverage}] {len(sub):,}행 중 KSIC 매칭 {ok:,} ({ok / len(sub):.1%})")
        for k, v in Counter(r for r in res if r).most_common(15):
            print(f"  {v:5d}  {k}")
        miss = Counter(re.sub(r'\s*외\s*\d+\s*종\s*$', '', u).strip()
                       for u, r in zip(sub["업종명"], res) if r is None)
        print("미매칭 상위:", miss.most_common(8))


if __name__ == "__main__":
    main()
