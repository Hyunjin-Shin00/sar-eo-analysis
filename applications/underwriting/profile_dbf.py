#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GIS건물통합정보 shapefile 속성(A0~A33) 데이터기반 프로파일링.
필드명이 익명(A#)이므로 실제 값 분포로 의미를 판별한다.
"""
import sys
from collections import Counter
from osgeo import ogr, gdal

gdal.SetConfigOption("SHAPE_ENCODING", "CP949")
ogr.UseExceptions()


def profile(path, sample=None):
    ds = ogr.Open(path)
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    n = lyr.GetFeatureCount()
    names, types = [], []
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        names.append(fd.GetName())
        types.append(f"{fd.GetTypeName()}({fd.GetWidth()}.{fd.GetPrecision()})")

    ctr = [Counter() for _ in names]
    nulls = [0] * len(names)
    lens = [set() for _ in names]
    numrange = [[None, None] for _ in names]
    read = 0
    for feat in lyr:
        read += 1
        for i in range(len(names)):
            if not feat.IsFieldSet(i) or feat.IsFieldNull(i):
                nulls[i] += 1
                continue
            v = feat.GetField(i)
            if isinstance(v, str):
                lens[i].add(len(v))
                if len(ctr[i]) < 4000:
                    ctr[i][v] += 1
                elif v in ctr[i]:
                    ctr[i][v] += 1
            else:
                lo, hi = numrange[i]
                numrange[i] = [v if lo is None else min(lo, v),
                               v if hi is None else max(hi, v)]
                if len(ctr[i]) < 4000:
                    ctr[i][v] += 1
        if sample and read >= sample:
            break

    print("=" * 96)
    print(f"FILE  : {path}")
    print(f"레이어: {lyr.GetName()}   기하: {ogr.GeometryTypeToName(lyr.GetGeomType())}")
    print(f"피처수: {n:,}   (프로파일 대상 {read:,}행)")
    print("=" * 96)
    for i, nm in enumerate(names):
        nullpct = nulls[i] / read * 100
        L = sorted(lens[i])
        lendesc = (f"len={L[0]}" if len(L) == 1 else
                   f"len={L[0]}~{L[-1]}" if L else "")
        uniq = len(ctr[i])
        cap = " (4000캡)" if uniq >= 4000 else ""
        head = f"{nm:>4} {types[i]:<14} 결측{nullpct:5.1f}%  고유{uniq:>5}{cap}  {lendesc}"
        print(head)
        if numrange[i][0] is not None:
            print(f"        범위: {numrange[i][0]:,.2f} ~ {numrange[i][1]:,.2f}")
        for val, cnt in ctr[i].most_common(6):
            s = str(val)
            if len(s) > 60:
                s = s[:57] + "..."
            print(f"        {cnt:>7,}  {s!r}")
        print()


if __name__ == "__main__":
    smp = int(sys.argv[2]) if len(sys.argv) > 2 else None
    profile(sys.argv[1], smp)
