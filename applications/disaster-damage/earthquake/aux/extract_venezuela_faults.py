import subprocess, sys

# geopandas 없으면 설치
try:
    import geopandas as gpd
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "geopandas"])
    import geopandas as gpd

import os
import zipfile
from shapely.geometry import box

# ── 경로 설정 ──────────────────────────────────────────────
BASE = r"<DATA_ROOT>\fault"
GEM_SHP = os.path.join(BASE, "gem-global-active-faults", "shapefile",
                       "gem_active_faults_harmonized.shp")
OUT_DIR = BASE

# ── 1. 데이터 읽기 ──────────────────────────────────────────
print("=== GEM 데이터 로드 중... ===")
gdf = gpd.read_file(GEM_SHP)
print(f"전체 단층 수: {len(gdf)}")
print(f"\n[컬럼 목록]")
print(gdf.columns.tolist())
print(f"\n[좌표계] {gdf.crs}")
print(f"\n[속성 테이블 샘플 (5행)]")
print(gdf.head(5).to_string())

# ── 2. CRS 확인 / EPSG:4326 변환 ───────────────────────────
if gdf.crs and gdf.crs.to_epsg() != 4326:
    print("\nEPSG:4326으로 변환 중...")
    gdf = gdf.to_crs(epsg=4326)

# ── 3. 공간 필터 (Bounding Box: lon -72~-60, lat 9~12) ──────
bbox = box(-72, 9, -60, 12)
gdf_bbox = gdf[gdf.intersects(bbox)].copy()
print(f"\n=== BBOX 필터 결과: {len(gdf_bbox)} 개 단층 ===")

# name 컬럼 확인
name_col = None
for col in ["name", "fault_name", "catalog_nam", "catalog_name"]:
    if col in gdf.columns:
        name_col = col
        break

if name_col:
    print(f"[이름 컬럼: '{name_col}']")
    print(gdf_bbox[[name_col]].to_string())
else:
    print("[이름 컬럼을 찾지 못했습니다. 컬럼 목록을 다시 확인하세요.]")
    name_col = gdf.columns[0]

# ── 4. 이름 기반 필터 ───────────────────────────────────────
targets = ["san sebasti", "el pilar", "bocono", "boconó"]

if name_col in gdf.columns:
    mask = gdf[name_col].str.lower().str.contains(
        "|".join(targets), na=False, regex=True
    )
    gdf_name = gdf[mask].copy()
    print(f"\n=== 이름 필터 결과: {len(gdf_name)} 개 단층 ===")
    print(gdf_name[[name_col]].to_string())

    # BBOX와 이름 필터 합집합 (누락 방지)
    idx_union = gdf_bbox.index.union(gdf_name.index)
    gdf_final = gdf.loc[idx_union].copy()
    print(f"\n=== 최종 (BBOX ∪ 이름 필터): {len(gdf_final)} 개 단층 ===")

    # BBOX에는 없고 이름 필터에만 있는 단층 알림
    only_name = gdf_name.index.difference(gdf_bbox.index)
    if len(only_name) > 0:
        print("[이름 필터에서만 검출된 단층 (BBOX 밖):]")
        print(gdf.loc[only_name, [name_col]].to_string())
    else:
        print("[이름 필터 단층이 모두 BBOX 안에 포함됩니다 — 누락 없음]")
else:
    gdf_final = gdf_bbox.copy()

# ── 5. 저장 ────────────────────────────────────────────────
out_shp  = os.path.join(OUT_DIR, "venezuela_north_faults.shp")
out_geojson = os.path.join(OUT_DIR, "venezuela_north_faults.geojson")

# shapefile 인코딩 명시
gdf_final.to_file(out_shp, driver="ESRI Shapefile", encoding="utf-8")
gdf_final.to_file(out_geojson, driver="GeoJSON")
print(f"\n저장 완료:")
print(f"  SHP     → {out_shp}")
print(f"  GeoJSON → {out_geojson}")

# ── 6. 최종 단층 목록 출력 ─────────────────────────────────
print(f"\n{'='*50}")
print(f"추출된 단층 수: {len(gdf_final)}")
print(f"{'='*50}")
if name_col in gdf_final.columns:
    for i, row in gdf_final.iterrows():
        print(f"  {row[name_col]}")

# ── 7. SHP → ZIP ───────────────────────────────────────────
zip_path = os.path.join(OUT_DIR, "venezuela_north_faults_shp.zip")
shp_exts = [".shp", ".shx", ".dbf", ".prj", ".cpg"]
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for ext in shp_exts:
        fpath = out_shp.replace(".shp", ext)
        if os.path.exists(fpath):
            zf.write(fpath, os.path.basename(fpath))
print(f"\nZIP 생성 완료: {zip_path}")
print(f"포함 파일: {[os.path.basename(out_shp.replace('.shp', e)) for e in shp_exts if os.path.exists(out_shp.replace('.shp', e))]}")
