import geopandas as gpd
import pandas as pd
import numpy as np
import os

SHP_PATH = r"<DATA_ROOT>\00_사업\2026\CLAB\결과\PSInSAR\PSInSAR\results_170\busan170_ps_v.shp"
OUT_CSV  = r"D:\busan170_ps_extract.csv"

# ── Step 1: Read shapefile ──────────────────────────────────────────────────
print("=" * 60)
print("STEP 1: Reading shapefile")
print("=" * 60)

for enc in ["ISO-8859-1", "cp949", "utf-8"]:
    try:
        gdf = gpd.read_file(SHP_PATH, encoding=enc)
        print(f"  Encoding OK: {enc}")
        break
    except Exception as e:
        print(f"  Encoding {enc} failed: {e}")

print(f"\nTotal rows : {len(gdf):,}")
print(f"CRS        : {gdf.crs}")
print(f"\nColumn list (name | dtype):")
for col, dt in zip(gdf.columns, gdf.dtypes):
    print(f"  {col:<25} {dt}")

print("\nTop 5 rows (non-geometry columns):")
non_geom = [c for c in gdf.columns if c != "geometry"]
print(gdf[non_geom].head().to_string())

# ── Step 2: Find velocity field ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2: Velocity field search")
print("=" * 60)

vel_keywords = ["vel", "v_", "_v", "mean", "disp", "rate", "mm", "dsp"]
numeric_cols = gdf[non_geom].select_dtypes(include=[np.number]).columns.tolist()

candidates = []
for col in numeric_cols:
    col_lower = col.lower()
    for kw in vel_keywords:
        if kw in col_lower:
            candidates.append(col)
            break

if not candidates:
    candidates = numeric_cols  # fallback: show all numeric

print(f"Velocity candidate columns: {candidates}\n")
for col in candidates:
    s = gdf[col].dropna()
    nodata_count_999  = int((gdf[col] == 999).sum())
    nodata_count_n999 = int((gdf[col] == -9999).sum())
    print(f"  [{col}]")
    print(f"    count={len(s):,}  NaN={gdf[col].isna().sum():,}")
    print(f"    min={s.min():.4f}  max={s.max():.4f}  mean={s.mean():.4f}  std={s.std():.4f}")
    print(f"    p5={s.quantile(.05):.4f}  p25={s.quantile(.25):.4f}  "
          f"p50={s.quantile(.50):.4f}  p75={s.quantile(.75):.4f}  p95={s.quantile(.95):.4f}")
    if nodata_count_999:
        print(f"    *** nodata(999) count: {nodata_count_999:,}")
    if nodata_count_n999:
        print(f"    *** nodata(-9999) count: {nodata_count_n999:,}")

# ── Step 3: Build output CSV ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3: Building output CSV")
print("=" * 60)

# Extract lon/lat from geometry
gdf["lon"] = gdf.geometry.x
gdf["lat"] = gdf.geometry.y

# Determine columns to keep
keep_cols = ["lon", "lat"]

# Add velocity candidates
keep_cols += candidates

# Add coherence/cumulative displacement/time-series keywords
extra_keywords = ["coh", "cum", "ts", "time", "date", "std", "height", "h", "inc", "az"]
for col in numeric_cols:
    col_lower = col.lower()
    if col in keep_cols:
        continue
    for kw in extra_keywords:
        if kw in col_lower:
            keep_cols.append(col)
            break

# Also include any remaining non-geom columns (string/object might be IDs)
for col in non_geom:
    if col not in keep_cols:
        keep_cols.append(col)

keep_cols = list(dict.fromkeys(keep_cols))  # deduplicate preserving order
print(f"Columns to save: {keep_cols}")

out_df = gdf[keep_cols].copy()
out_df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
print(f"\nSaved: {OUT_CSV}")

# ── Step 4: Verify output ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 4: Verification")
print("=" * 60)

file_mb = os.path.getsize(OUT_CSV) / (1024 * 1024)
print(f"  Rows    : {len(out_df):,}")
print(f"  Columns : {len(out_df.columns)}  ->  {list(out_df.columns)}")
print(f"  File    : {file_mb:.2f} MB")
print("\nDone.")
