#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""환경·자료 자가진단 — 3초. usage: env -u PYTHONPATH python3 code/check_env.py"""
import os, sys, glob
os.environ.pop("PYTHONPATH", None)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NG = []


def chk(name, cond, note=""):
    if not cond:
        NG.append(name)
    print("  %s %-42s %s" % ("OK  " if cond else "FAIL", name, note))


print("■ 파이썬")
chk("python >= 3.8", sys.version_info >= (3, 8), ".".join(map(str, sys.version_info[:3])))

print("■ 패키지")
for m in ("numpy", "scipy", "pandas", "geopandas", "rasterio", "shapely", "pyproj",
          "matplotlib", "contextily", "weasyprint"):
    try:
        chk(m, True, getattr(__import__(m), "__version__", ""))
    except Exception as e:
        chk(m, False, type(e).__name__)

print("■ 자료")
FILES = [("data/sar/cache_unw.npz", "언래핑 간섭쌍 824개 — SBAS 입력"),
         ("data/sar/geom.npz", "격자 좌표"),
         ("data/sar/meta.json", "촬영일 212개"),
         ("data/rule/rule_grade.json", "판정 규칙 — 선별·경보 임계"),
         ("data/rule/rule_grade_bg.npz", "배경 30곳 분포"),
         ("clab/regions/busan/sbas/sasang_hadan/sweep/coh0.3_tcoh0.7/"
          "Busan_Sasang_Hadan_sbas_ps_v.csv", "SBAS 관측점 (폴백)"),
         ("clab/analysis/sbas_sweep/report_site.py", "보고서 생성 코드"),
         ("clab/analysis/sbas_sweep/out/verify/last_section.json", "규칙 원문"),
         ("clab/auxiliary/subsidence_list/subsidence_accidents_geocoded_update.csv", "사고 이력"),
         ("assets/font/SamsungGothicCondensed-Regular.ttf", "삼성긴고딕"),
         ("code/sf/logo_ci.png", "<고객사> CI")]
for rel, note in FILES:
    p = os.path.join(BASE, rel)
    chk(rel if len(rel) < 42 else "..." + rel[-39:], os.path.exists(p),
        "%s · %.1fMB" % (note, os.path.getsize(p) / 1e6) if os.path.exists(p) else note)

print("■ 보고서 기준일 (격자 캐시 보유)")
ds = sorted(os.path.basename(f)[9:-4] for f in glob.glob(os.path.join(BASE, "data", "zone_cache", "*.npz")))
chk("data/zone_cache/", len(ds) > 0, " ".join(ds))

print()
print("전부 정상" if not NG else "위 FAIL 항목을 먼저 해결하세요.")
sys.exit(1 if NG else 0)
