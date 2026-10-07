#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 0 - 대구 산업단지 기업 등록현황 CSV 프로파일링.

추측 금지 원칙: 실제 파일에서 읽은 것만 출력한다.
컬럼이 기대와 다르면 가정하지 않고 그대로 리포트하고 해당 항목을 SKIP 한다.
"""
import re
import sys
from collections import Counter

import pandas as pd

ENCODINGS = ["utf-8-sig", "cp949", "euc-kr"]

# 브리프에 명시된 10개 컬럼. 존재 여부는 검증만 하고, 없으면 SKIP.
EXPECTED = ["순번", "단지명", "회사명", "공장대표주소(도로명)", "공장대표주소(지번)",
            "업종명", "관할조직명", "설립구분", "생산품", "주원자재"]

C_COMPLEX, C_NAME = "단지명", "회사명"
C_ADDR_ROAD, C_ADDR_JIBUN = "공장대표주소(도로명)", "공장대표주소(지번)"
C_SECTOR, C_PRODUCT, C_MATERIAL = "업종명", "생산품", "주원자재"


def load(path):
    last = None
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str)
            print(f"[load] encoding={enc}  rows={len(df):,}  cols={len(df.columns)}")
            return df, enc
        except (UnicodeDecodeError, LookupError) as e:
            last = e
            print(f"[load] encoding={enc} 실패: {type(e).__name__}")
    raise SystemExit(f"모든 인코딩 실패: {last}")


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def missing_rate(s):
    """결측 = NaN 또는 공백만 있는 문자열."""
    blank = s.isna() | (s.fillna("").str.strip() == "")
    return blank.mean() * 100, int(blank.sum())


def main(path):
    df, enc = load(path)

    hr("[0] 컬럼 검증")
    actual = list(df.columns)
    print("실제 컬럼:")
    for i, c in enumerate(actual, 1):
        print(f"  {i:2d}. {c!r}")
    extra = [c for c in actual if c not in EXPECTED]
    lack = [c for c in EXPECTED if c not in actual]
    print(f"\n기대 대비 누락: {lack if lack else '없음'}")
    print(f"기대 대비 추가: {extra if extra else '없음'}")
    print(f"총 행 수: {len(df):,}")
    print(f"완전중복 행: {int(df.duplicated().sum()):,}")

    def has(c):
        if c in df.columns:
            return True
        print(f"  !! 컬럼 {c!r} 없음 → SKIP")
        return False

    # ---- 1. 단지명 고유값 전체 ----
    hr("[1] 단지명 고유값 전체 목록 + 행 수")
    if has(C_COMPLEX):
        vc = df[C_COMPLEX].fillna("(결측)").value_counts(dropna=False)
        print(f"고유값 개수: {len(vc)}")
        for k, v in vc.items():
            print(f"  {v:6,}  {k}")

    # ---- 2. 성서 관련 표기 ----
    hr("[2] '성서' 포함 단지명 표기 방식")
    if has(C_COMPLEX):
        s = df[C_COMPLEX].fillna("")
        seongseo = s[s.str.contains("성서", na=False)]
        vc2 = seongseo.value_counts()
        print(f"'성서' 포함 행: {len(seongseo):,} / {len(df):,}  ({len(seongseo)/len(df)*100:.1f}%)")
        print(f"'성서' 포함 고유 표기: {len(vc2)}종")
        for k, v in vc2.items():
            print(f"  {v:6,}  {k!r}")
        print("\n-- 표기 안 문자 패턴 (차수 표기 추출) --")
        pats = Counter()
        for k in vc2.index:
            pats[re.sub(r"[0-9]+", "#", k)] += vc2[k]
        for k, v in pats.most_common():
            print(f"  {v:6,}  {k!r}")

    # ---- 3. 차수별 행 수 ----
    hr("[3] 성서 차수별 행 수")
    if has(C_COMPLEX):
        s = df[C_COMPLEX].fillna("")
        seongseo = s[s.str.contains("성서", na=False)]
        cha = Counter()
        for k, v in seongseo.value_counts().items():
            m = re.search(r"(\d+)\s*차", k)
            cha[m.group(1) + "차" if m else "차수표기없음"] += v
        for k, v in sorted(cha.items()):
            print(f"  {v:6,}  {k}")
        print(f"  {'-'*20}\n  {sum(cha.values()):6,}  성서 합계")

    # ---- 4. 업종명 상위 50 ----
    hr("[4] 업종명 고유값 상위 50 + 빈도 (전체 / 성서)")
    if has(C_SECTOR):
        vc = df[C_SECTOR].fillna("(결측)").value_counts()
        print(f"[전체] 고유 업종명: {len(vc)}종")
        for i, (k, v) in enumerate(vc.head(50).items(), 1):
            print(f"  {i:2d}. {v:6,}  {k}")
        if C_COMPLEX in df.columns:
            sub = df[df[C_COMPLEX].fillna("").str.contains("성서", na=False)]
            vcs = sub[C_SECTOR].fillna("(결측)").value_counts()
            print(f"\n[성서만] 행 {len(sub):,} / 고유 업종명 {len(vcs)}종")
            for i, (k, v) in enumerate(vcs.head(50).items(), 1):
                print(f"  {i:2d}. {v:6,}  {k}")

    # ---- 5. 생산품/주원자재 결측률 ----
    hr("[5] 결측률 (NaN 또는 공백)")
    for c in actual:
        pct, n = missing_rate(df[c])
        mark = " <<<" if c in (C_PRODUCT, C_MATERIAL) else ""
        print(f"  {pct:6.2f}%  ({n:,})  {c}{mark}")
    if C_COMPLEX in df.columns:
        sub = df[df[C_COMPLEX].fillna("").str.contains("성서", na=False)]
        print(f"\n[성서 {len(sub):,}행 기준]")
        for c in [C_PRODUCT, C_MATERIAL, C_SECTOR, C_ADDR_JIBUN, C_ADDR_ROAD]:
            if c in sub.columns:
                pct, n = missing_rate(sub[c])
                print(f"  {pct:6.2f}%  ({n:,})  {c}")

    # ---- 6. 지번주소 표기 패턴 ----
    hr("[6] 공장대표주소(지번) 표기 패턴")
    if has(C_ADDR_JIBUN):
        col = df[C_ADDR_JIBUN].fillna("").str.strip()
        nz = col[col != ""]
        print(f"비어있지 않은 지번주소: {len(nz):,}\n")
        print("-- 샘플 20건 (성서 우선, 부족하면 전체에서 보충) --")
        if C_COMPLEX in df.columns:
            mask = df[C_COMPLEX].fillna("").str.contains("성서", na=False)
            samp = col[mask & (col != "")]
        else:
            samp = nz
        samp = samp.head(20) if len(samp) >= 20 else pd.concat([samp, nz]).head(20)
        for i, v in enumerate(samp.tolist(), 1):
            print(f"  {i:2d}. {v}")

        print("\n-- 시도명 접두 (앞 1토큰) --")
        for k, v in nz.str.split().str[0].value_counts().head(15).items():
            print(f"  {v:6,}  {k!r}")

        print("\n-- '산' 지번 포함 --")
        san = nz.str.contains(r"(?:^|\s)산\s*\d", regex=True, na=False)
        print(f"  {int(san.sum()):,} 건 ({san.mean()*100:.2f}%)")
        for v in nz[san].head(5).tolist():
            print(f"    ex) {v}")

        print("\n-- 부번(하이픈) 형식 --")
        checks = {
            "공백없는 하이픈 123-4": r"\d+-\d+",
            "공백있는 하이픈 123 - 4": r"\d+\s+-\s*\d+|\d+\s*-\s+\d+",
            "'번지' 포함": r"번지",
            "괄호 포함": r"[()]",
            "쉼표 포함": r",",
            "본번만(하이픈 없음)": r"^(?!.*\d-\d).*\d\s*$",
        }
        for label, pat in checks.items():
            m = nz.str.contains(pat, regex=True, na=False)
            print(f"  {int(m.sum()):6,} ({m.mean()*100:5.2f}%)  {label}")
            for v in nz[m].head(3).tolist():
                print(f"        ex) {v}")

        print("\n-- 끝부분 토큰 패턴 (숫자→#) 상위 15 --")
        tail = nz.str.split().str[-1].map(lambda x: re.sub(r"\d+", "#", x))
        for k, v in tail.value_counts().head(15).items():
            print(f"  {v:6,}  {k!r}")

    # ---- 7. 주소 중복도 ----
    hr("[7] 주소 중복도 (같은 지번에 여러 업체)")
    for label, c in [("지번", C_ADDR_JIBUN), ("도로명", C_ADDR_ROAD)]:
        if c not in df.columns:
            continue
        for scope, d in [("전체", df)] + ([("성서", df[df[C_COMPLEX].fillna("").str.contains("성서", na=False)])]
                                          if C_COMPLEX in df.columns else []):
            col = d[c].fillna("").str.strip()
            nz = col[col != ""]
            if not len(nz):
                continue
            g = nz.value_counts()
            multi = g[g > 1]
            rows_in_multi = int(multi.sum())
            print(f"\n[{scope}/{label}] 유효주소 {len(nz):,}건 → 고유주소 {len(g):,}개")
            print(f"  고유주소당 평균 업체수: {len(nz)/len(g):.2f}")
            print(f"  2개 이상 업체 주소: {len(multi):,}개 ({len(multi)/len(g)*100:.1f}% of 고유)")
            print(f"  그 주소에 속한 레코드: {rows_in_multi:,}건 ({rows_in_multi/len(nz)*100:.1f}% of 유효)")
            print("  최다 집중 주소 top5:")
            for k, v in g.head(5).items():
                print(f"    {v:4,}개사  {k}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: profile_phase0.py <csv_path>")
    main(sys.argv[1])
