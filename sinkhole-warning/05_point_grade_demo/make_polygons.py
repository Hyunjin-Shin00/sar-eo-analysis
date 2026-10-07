# -*- coding: utf-8 -*-
"""AOI(분석 영역)·관심 지역 폴리곤을 GeoJSON 으로 뽑는다.

전달본(handover_20260827)이 보고서 지도를 그릴 때 쓰는 것과 같은 정의다.
  · 분석 영역 = 판정 격자(50 m)의 바깥 테두리   — 보고서 지도의 흰 점선
  · 관심 지역 = 중심 좌표 기준 한 변 50 m 정사각 — 보고서 지도의 노란 사각형

주의·위험 구역은 이 스크립트가 아니라 보고서 산출 과정에서 나온다.
  env -u PYTHONPATH python3 <전달본>/demo/03_risk/make_report.py --addr "<주소>" --asof <날짜>
  → demo/03_risk/out/report_<날짜>_map_zones.geojson

usage: env -u PYTHONPATH python3 make_polygons.py [--handover DIR] [--addr 주소] [--side 50] [--out DIR]
"""
import os, sys, json, argparse
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--handover", default=os.path.join(os.path.dirname(HERE), "handover_20260827"),
                help="전달본 폴더 (demo/_lib 가 들어 있는 곳)")
ap.add_argument("--addr", default="부산 사상구 새벽로 87")
ap.add_argument("--name", default="사상 새벽로87 신축공사")
ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
ap.add_argument("--side", type=float, default=50.0, help="관심 지역 한 변 (m)")
ap.add_argument("--out", default=HERE)
args = ap.parse_args()

LIB = os.path.join(args.handover, "demo", "_lib")
if not os.path.isdir(LIB):
    sys.exit("전달본을 찾지 못했습니다 - --handover 로 경로를 지정하십시오: %s" % LIB)
os.environ.setdefault("DATA_ROOT", LIB)
sys.path.insert(0, os.path.join(LIB, "analysis", "sbas_sweep"))
sys.path.insert(0, os.path.join(LIB, "analysis", "sinkhole"))
import numpy as np
import report_site as RS
from pyproj import Transformer

os.makedirs(args.out, exist_ok=True)
TRm  = RS.SL.loaders._TR_M
back = Transformer.from_crs(TRm.target_crs, 4326, always_xy=True)

# ── ① 분석 영역(AOI) - zone_danger.py 72~76행 · report_site.py 274~279행과 같은 계산
e, _ = RS.FX.build_entry(RS.REGION, RS.COH, RS.TCOH, RS.KSET)
S_, N_, W_, Eb = e["box"]
xs_, ys_ = TRm.transform([W_, Eb], [S_, N_])
step = 50.0
gx = np.arange(xs_[0], xs_[1] + step, step)
gy = np.arange(ys_[0], ys_[1] + step, step)
hs = step / 2.0
ex_, ey_ = np.r_[gx - hs, gx[-1] + hs], np.r_[gy - hs, gy[-1] + hs]
bx = np.r_[ex_, np.full(len(ey_), ex_[-1]), ex_[::-1], np.full(len(ey_), ex_[0])]
by = np.r_[np.full(len(ex_), ey_[0]), ey_, np.full(len(ex_), ey_[-1]), ey_[::-1]]
alon, alat = back.transform(bx, by)
ring = [[float(a), float(b)] for a, b in zip(alon, alat)]   # 구역 폴리곤과 꼭짓점이 정확히 맞도록 반올림하지 않는다
ring.append(ring[0])

aoi = {"type": "FeatureCollection",
       "note": "분석 영역(AOI) - 보고서 지도의 흰 점선. 50 m 판정 격자의 바깥 테두리",
       "features": [{"type": "Feature",
                     "properties": {"kind": "분석 영역", "region": RS.REGION,
                                    "region_kr": RS.REGION_KR, "grid_m": 50,
                                    "n_cells": int(len(gx) * len(gy)),
                                    "size_km": [round(float(ex_[-1] - ex_[0]) / 1000, 3),
                                                round(float(ey_[-1] - ey_[0]) / 1000, 3)],
                                    "area_km2": round(float((ex_[-1]-ex_[0]) * (ey_[-1]-ey_[0]) / 1e6), 3),
                                    "bbox_report": [round(float(v), 5) for v in e["box"]],
                                    "color": "#ffffff"},
                     "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
p1 = os.path.join(args.out, "AOI_분석영역.geojson")
json.dump(aoi, open(p1, "w"), ensure_ascii=False, indent=1)
print("분석 영역  격자 %d x %d · %.2f x %.2f km · %.2f km²"
      % (len(gx), len(gy), (ex_[-1]-ex_[0])/1000, (ey_[-1]-ey_[0])/1000,
         (ex_[-1]-ex_[0]) * (ey_[-1]-ey_[0]) / 1e6))
print("           → %s" % p1)

# ── ② 관심 지역(공사 범위) - report_site.make_site_shp 와 같은 계산
note = "좌표 직접 입력"
lat, lon = args.lat, args.lon
if lat is None or lon is None:
    lat, lon, note = RS.geocode_by_road(args.addr)
xr, yr = TRm.transform([lon], [lat])
h = args.side / 2.0
sx = [xr[0] - h, xr[0] + h, xr[0] + h, xr[0] - h]
sy = [yr[0] - h, yr[0] - h, yr[0] + h, yr[0] + h]
slon, slat = back.transform(sx, sy)
sring = [[float(a), float(b)] for a, b in zip(slon, slat)]
sring.append(sring[0])

site = {"type": "FeatureCollection",
        "note": "관심 지역(공사 범위) - 중심 좌표 기준 한 변 %.0f m 정사각. 표시·도면용이며 판정 단위가 아니다"
                % args.side,
        "features": [{"type": "Feature",
                      "properties": {"kind": "관심 지역", "name": args.name, "addr": args.addr,
                                     "lat": round(float(lat), 6), "lon": round(float(lon), 6),
                                     "side_m": args.side, "area_m2": args.side * args.side,
                                     "judge_radius_m": RS.R, "geo_note": note,
                                     "color": "#ffe000"},
                      "geometry": {"type": "Polygon", "coordinates": [sring]}}]}
p2 = os.path.join(args.out, "관심지역_%s.geojson"
                  % ("".join(args.addr.split()[-2:]) if args.lat is None else "%.5f_%.5f" % (lat, lon)))
json.dump(site, open(p2, "w"), ensure_ascii=False, indent=1)
print("관심 지역  위도 %.6f · 경도 %.6f · 한 변 %.0f m · %.0f m² · 판정 반경 %.0f m"
      % (lat, lon, args.side, args.side * args.side, RS.R))
print("           위도 %.6f~%.6f · 경도 %.6f~%.6f" % (min(slat), max(slat), min(slon), max(slon)))
print("           → %s" % p2)
