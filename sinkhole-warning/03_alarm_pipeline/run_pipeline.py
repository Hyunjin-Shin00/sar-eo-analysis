# -*- coding: utf-8 -*-
"""싱크홀 사전 알람 파이프라인 0~5단계 일괄 실행 (AOI 한정).
  0 인벤토리(00_inventory_report.md, 사전작성)  1 GIMS 지하수(옵션)
  3 피처(InSAR 3지표+역속도, 지반α)             4 융합→DBSCAN 클러스터 알람(gpkg/csv)
  5 백테스팅(사고리스트=정답, 리드타임/KPI)
사용: run_pipeline.py [--aoi R1,R2] [--date-to YYYYMMDD] [--gims-key K] [--skip-backtest]
⚠️ 임계치·계수 잠정(pcfg/CONFIG). 실행 파이썬 = pyps(3.8), PYTHONPATH 비우고 실행."""
import os; os.environ.pop("PYTHONPATH", None)
import argparse, datetime as dt
import numpy as np, pandas as pd
import pyproj
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir(); os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
import geopandas as gpd

from pcfg import PATHS
from aoi import load_aoi
import fuse_cluster as fc
import gims


def _asof(date_to):
    if not date_to:
        return None
    d = dt.datetime.strptime(date_to, "%Y%m%d").date()
    return d.year + (d - dt.date(d.year, 1, 1)).days / 365.25


def step34_region(region, asof):
    """피처 + 클러스터 알람 산출·저장. 반환 (n_pts, clusters_df)."""
    pts, cl, _ = fc.cluster_alarms(region, asof)
    if pts.empty:
        print(f"  {region}: 데이터 없음"); return 0, cl
    # 피처(상위등급 점만 저장 — 용량)
    elev = pts[pts["score"] >= 1]
    elev.to_csv(os.path.join(PATHS["features"], f"points_{region}.csv"),
                index=False, encoding="utf-8-sig")
    # 알람 클러스터 csv + gpkg(점=중심)
    cl.to_csv(os.path.join(PATHS["alarms"], f"aoi_{region}_alarm.csv"),
              index=False, encoding="utf-8-sig")
    if len(cl):
        gdf = gpd.GeoDataFrame(cl.copy(),
                               geometry=gpd.points_from_xy(cl["cx_lon"], cl["cy_lat"]),
                               crs="EPSG:4326")
        gdf.to_file(os.path.join(PATHS["alarms"], f"aoi_{region}_alarm.gpkg"), driver="GPKG")
    nlv = cl["alarm"].value_counts().to_dict() if len(cl) else {}
    print(f"  {region}: 점 {len(pts):,} | 상위등급 {len(elev):,} | 알람 클러스터 {len(cl)} {nlv}")
    return len(pts), cl


def main():
    ap = argparse.ArgumentParser(description="싱크홀 사전 알람 파이프라인")
    ap.add_argument("--aoi", default=None, help="처리할 region 콤마목록(기본 전체 7)")
    ap.add_argument("--date-from", default=None, help="(예약) 시작일 YYYYMMDD")
    ap.add_argument("--date-to", default=None, help="asof 종료일 YYYYMMDD(기본 전체기간)")
    ap.add_argument("--gims-key", default=os.environ.get("GIMS_KEY"), help="GIMS Decoding 서비스키(옵션)")
    ap.add_argument("--skip-backtest", action="store_true")
    args = ap.parse_args()

    aoi = load_aoi()
    if args.aoi:
        want = set(x.strip() for x in args.aoi.split(","))
        aoi = {k: v for k, v in aoi.items() if k in want}
    asof = _asof(args.date_to)
    print(f"■ 파이프라인 시작 — {len(aoi)}개 AOI, asof={args.date_to or '전체기간'}")

    print("\n[1] GIMS 지하수 방아쇠(옵션)")
    gims.run_all(aoi, args.gims_key)

    print("\n[3-4] InSAR·지반 피처 → 융합 → DBSCAN 클러스터 알람")
    summary = []
    for region in aoi:
        n, cl = step34_region(region, asof)
        summary.append({"region": region, "n_pts": n, "n_alarm": len(cl),
                        "경보": int((cl["alarm"] == "경보").sum()) if len(cl) else 0,
                        "주의": int((cl["alarm"] == "주의").sum()) if len(cl) else 0})
    pd.DataFrame(summary).to_csv(os.path.join(PATHS["alarms"], "_alarm_summary.csv"),
                                 index=False, encoding="utf-8-sig")

    if not args.skip_backtest:
        print("\n[5] 백테스팅")
        import backtest
        backtest.main()
    print("\n■ 완료. 산출물: alarms/, features/, backtest/, 00_inventory_report.md")


if __name__ == "__main__":
    main()
