#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Catia La Mar (La Guaira, Venezuela) 건물 footprint 추출 스크립트
=================================================================
- 소스 1순위: Microsoft GlobalMLBuildingFootprints (Azure blob)
- 소스 2순위(fallback): Google Open Buildings v3 (S2 tiles) — 주석 참고
- 출력: EPSG:4326 shapefile (+ GeoPackage) — AOI clip 완료

주의:
  * 이 데이터는 지진 피해등급이 아닌 순수 건물 형상(baseline)입니다.
    지진 초동 보고서에서 사용할 때는 '현장 미검증 예비 baseline'으로 라벨링하세요.
  * 로컬 환경(네트워크 제약 없는 곳)에서 실행하세요.

의존성:
  pip install geopandas shapely mercantile requests pandas pyarrow
"""

import io
import json
import gzip
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape, box
import mercantile

# ── AOI 정의: Catia La Mar 해안 시가지 (좁게) ──────────────────────────
# La Guaira 주 Vargas 자치구, Maiquetía 서편. Caracas 내륙 Catia와 무관.
W, S, E, N = -67.075, 10.578, -66.995, 10.618
AOI = box(W, S, E, N)

OUT_SHP = "catia_la_mar_buildings.shp"
OUT_GPKG = "catia_la_mar_buildings.gpkg"

# ── 1) Microsoft Building Footprints ─────────────────────────────────
MS_INDEX = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"


def fetch_microsoft():
    print("[MS] dataset index 다운로드...")
    links = pd.read_csv(MS_INDEX)
    # Venezuela 국가 필터
    ven = links[links["Location"].str.contains("Venezuela", case=False, na=False)]
    print(f"[MS] Venezuela 링크 {len(ven)}건")

    # AOI를 덮는 z9 quadkey 계산
    tiles = list(mercantile.tiles(W, S, E, N, zooms=9))
    qks = {mercantile.quadkey(t) for t in tiles}
    print(f"[MS] AOI quadkeys(z9): {sorted(qks)}")

    # QuadKey 컬럼을 문자열로 맞춰 매칭
    ven = ven.copy()
    ven["QuadKey"] = ven["QuadKey"].astype(str)
    hit = ven[ven["QuadKey"].isin(qks)]
    if hit.empty:
        print("[MS] 매칭 quadkey 없음 — z9 매칭 실패. 전체 Venezuela 링크에서 좌표 재확인 필요")
        return None

    feats = []
    for _, row in hit.iterrows():
        url = row["Url"]
        print(f"[MS] 타일 다운로드: {row['QuadKey']}")
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        # gzip 또는 plain jsonl 모두 대응
        raw = r.content
        try:
            text = gzip.decompress(raw).decode("utf-8")
        except OSError:
            text = raw.decode("utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            geom = shape(obj["geometry"])
            # AOI 사전 필터 (bbox intersect)
            if geom.intersects(AOI):
                feats.append({"geometry": geom, **obj.get("properties", {})})

    if not feats:
        print("[MS] AOI 내 건물 없음")
        return None
    gdf = gpd.GeoDataFrame(feats, crs="EPSG:4326")
    return gdf


# ── 2) Google Open Buildings v3 (fallback) ───────────────────────────
# MS가 비면 아래 사용. Google은 S2 level-6 tile CSV.gz 제공.
# https://sites.research.google/open-buildings/  → Download 섹션
# tile 좌표 조회 후 아래 패턴으로 받으면 됩니다:
#   https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_6_gzip/<TILE>_buildings.csv.gz
# CSV 컬럼: latitude, longitude, area_in_meters, confidence, geometry(WKT), full_plus_code
def fetch_google(tile_id):
    from shapely import wkt
    url = f"https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_6_gzip/{tile_id}_buildings.csv.gz"
    print(f"[Google] {url}")
    df = pd.read_csv(url, compression="gzip")
    df["geometry"] = df["geometry"].apply(wkt.loads)
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    gdf = gdf[gdf.intersects(AOI)]
    # confidence 필터 권장 (>=0.7)
    if "confidence" in gdf.columns:
        gdf = gdf[gdf["confidence"] >= 0.65]
    return gdf


def main():
    gdf = None
    try:
        gdf = fetch_microsoft()
    except Exception as e:
        print(f"[MS] 실패: {e}")

    if gdf is None or gdf.empty:
        print("[!] Microsoft 실패/빈 결과 → Google fallback 사용 권장.")
        print("    open-buildings 사이트에서 Catia La Mar를 덮는 S2 L6 tile ID 확인 후")
        print("    fetch_google('<TILE_ID>') 호출하세요.")
        return

    # AOI 정밀 clip
    gdf = gpd.clip(gdf, AOI)
    gdf = gdf.reset_index(drop=True)
    gdf["bld_id"] = gdf.index + 1

    print(f"[OK] AOI 내 건물 {len(gdf)}개")
    gdf.to_file(OUT_GPKG, driver="GPKG")
    # shapefile은 컬럼명 10자 제한 → 최소 컬럼만
    keep = ["bld_id", "geometry"]
    gdf[keep].to_file(OUT_SHP, driver="ESRI Shapefile", encoding="utf-8")
    print(f"[OK] 저장: {OUT_SHP}, {OUT_GPKG}")


if __name__ == "__main__":
    main()
