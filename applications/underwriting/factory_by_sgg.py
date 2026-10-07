#!/usr/bin/env python3
"""GIS건물통합정보(대구)에서 시군구별 전체/주용도=공장 건물 수, 달서구 공장 상위 법정동 집계.
성서산단 소재 법정동(갈산·월암·대천·장동·호산·파호·신당·호림·이곡) 확인용.
사용: python factory_by_sgg.py <AL_D162_27_*.dbf> [<AL_D164_27_*.dbf>]
"""
import sys
from collections import Counter
from osgeo import ogr, gdal
gdal.SetConfigOption("SHAPE_ENCODING", "CP949"); ogr.UseExceptions()
SGG = {"27110": "중구", "27140": "동구", "27170": "서구", "27200": "남구", "27230": "북구",
       "27260": "수성구", "27290": "달서구", "27710": "달성군", "27720": "군위군"}
for p in sys.argv[1:]:
    ds = ogr.Open(p); lyr = ds.GetLayer(0)
    tot, fac = Counter(), Counter()
    dalseo_dong = Counter()
    for f in lyr:
        sgg = f.GetField("A39"); use = f.GetField("A30")   # A39=시군구코드, A30=주용도명
        tot[sgg] += 1
        if use == "공장":
            fac[sgg] += 1
            if sgg == "27290":
                dalseo_dong[f.GetField("A3")] += 1
    print(f"\n===== {p} =====")
    print(f"{'시군구':<8}{'전체':>9}{'용도=공장':>10}")
    for k in sorted(tot, key=lambda x: -tot[x]):
        print(f"{SGG.get(k, k):<8}{tot[k]:>9,}{fac.get(k, 0):>10,}")
    if dalseo_dong:
        print("\n-- 달서구 '공장' 상위 법정동 --")
        for k, v in dalseo_dong.most_common(12):
            print(f"  {v:>6,}  {k}")
