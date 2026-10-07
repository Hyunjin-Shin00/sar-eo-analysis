# -*- coding: utf-8 -*-
"""시기별 공사현황 선형(shapefile)에서 누적 연장과 군사분계선까지 최단거리를 산출한다.

디지타이징은 QGIS 에서 손으로 했고, 이 스크립트는 그 결과를 미터 단위로 재는 역할만 한다.
경위도(EPSG:4326)에서 길이를 그대로 재면 위도에 따라 오차가 생기므로,
반드시 투영좌표계(EPSG:5179, Korea 2000 Unified CS)로 변환한 뒤 계산한다.

입력
  --works   시기별 공사현황 shapefile 이 든 디렉터리 (파일명이 YYYYMMDD.shp)
  --mdl     군사분계선 선형 shapefile (예: OpenStreetMap 추출본)
출력
  표준출력에 시기별 누적 연장(km) · 증가분(km) · MDL 최단거리(m)
  --csv 를 주면 같은 내용을 CSV 로 저장
"""
import argparse, glob, os
import geopandas as gpd

CRS_M = 5179  # Korea 2000 / Unified CS — 국내 거리·면적 계산 표준


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--works", required=True, help="시기별 공사현황 shapefile 디렉터리")
    ap.add_argument("--mdl", required=True, help="군사분계선 shapefile")
    ap.add_argument("--csv", help="결과 CSV 경로")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.works, "*.shp")))
    if not files:
        raise SystemExit(f"shapefile 을 찾지 못했다: {a.works}")
    mdl = gpd.read_file(a.mdl).to_crs(CRS_M)

    rows, prev = [], 0.0
    print(f"{'date':10s} {'n':>3s} {'누적 km':>9s} {'증가 km':>9s} {'MDL m':>9s}")
    for f in files:
        g = gpd.read_file(f).to_crs(CRS_M)
        length = g.geometry.length.sum() / 1000.0
        dist = min(mdl.distance(geom).min() for geom in g.geometry)
        date = os.path.basename(f)[:8]
        print(f"{date:10s} {len(g):3d} {length:9.2f} {length-prev:+9.2f} {dist:9.0f}")
        rows.append({"date": date, "features": len(g), "cum_km": round(length, 3),
                     "delta_km": round(length - prev, 3), "mdl_dist_m": round(dist, 1)})
        prev = length

    if a.csv:
        import pandas as pd
        pd.DataFrame(rows).to_csv(a.csv, index=False, encoding="utf-8-sig")
        print(f"\n저장: {a.csv}")


if __name__ == "__main__":
    main()
