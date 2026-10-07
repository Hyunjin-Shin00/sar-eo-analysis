#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""애매한 필드 정밀 검증: ID 유일성, A15 관계, A35 형식, 면적/율 관계식."""
import sys
from collections import Counter, defaultdict
from osgeo import ogr, gdal
gdal.SetConfigOption("SHAPE_ENCODING", "CP949")

path = sys.argv[1]
ds = ogr.Open(path); lyr = ds.GetLayer(0)
n = lyr.GetFeatureCount()
print(f"### {path}  피처 {n:,}  필드 {lyr.GetLayerDefn().GetFieldCount()}\n")

uniq = {k: set() for k in ["A0", "A1", "A7", "A13", "A14"]}
a15_by_a2 = defaultdict(set)      # A15 <-> 법정동코드(A2)
a15_len = Counter()
a35_len = Counter()
a34_len = Counter()
bc_ok = bc_bad = 0                # 건폐율 = A23/A22
fa_ok = fa_bad = 0                # 용적률 = A24/A22
park = 0
rows = 0
for f in lyr:
    rows += 1
    for k in uniq:
        v = f.GetField(k)
        if v is not None:
            uniq[k].add(v)
    a2, a15 = f.GetField("A2"), f.GetField("A15")
    if a15 is not None:
        a15_len[len(a15)] += 1
        a15_by_a2[a2].add(a15)
    for fld, ctr in (("A35", a35_len), ("A34", a34_len)):
        v = f.GetField(fld)
        if v:
            ctr[len(v)] += 1
    A22, A23, A24, A25, A26 = (f.GetField(x) for x in ("A22","A23","A24","A25","A26"))
    if A22 and A22 > 0:
        if A23 is not None and abs(A23 / A22 * 100 - (A26 or -1)) < 0.06: bc_ok += 1
        else: bc_bad += 1
        if A24 is not None and abs(A24 / A22 * 100 - (A25 or -1)) < 0.06: fa_ok += 1
        else: fa_bad += 1
    A36, A37 = f.GetField("A36"), f.GetField("A37")
    if A36 and A37 and abs(A37 - A36 * 11.5) < 0.01:
        park += 1

print("-- ID 후보 유일성 --")
for k, s in uniq.items():
    print(f"  {k}: 고유 {len(s):,} / {rows:,}   {'★유일키' if len(s)==rows else ''}")
print(f"\n-- A15 길이 분포 --\n  {dict(a15_len)}")
multi = sum(1 for v in a15_by_a2.values() if len(v) > 1)
print(f"-- A15 vs A2(법정동코드) --")
print(f"  법정동코드 {len(a15_by_a2):,}개 중 A15가 2개 이상 대응: {multi:,}")
for a2, s in list(a15_by_a2.items())[:6]:
    print(f"    A2={a2} → A15={sorted(s)[:6]}")
print(f"\n-- A34 길이(사용승인일 후보) --\n  {dict(a34_len)}")
print(f"-- A35 길이 --\n  {dict(a35_len)}")
print(f"\n-- 관계식 검증 (A22>0 인 행) --")
print(f"  A26 == A23/A22*100 (건폐율)   : 일치 {bc_ok:,} / 불일치 {bc_bad:,}")
print(f"  A25 == A24/A22*100 (용적률)   : 일치 {fa_ok:,} / 불일치 {fa_bad:,}")
print(f"  A37 == A36*11.5 (주차면적)    : 일치 {park:,}")
