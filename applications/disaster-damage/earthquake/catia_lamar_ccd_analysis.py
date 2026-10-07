"""
Catia La Mar CCD 집중 분석
==========================
1. MS GlobalMLBuildingFootprints 다운로드 (mercantile 없이)
   -> 실패 시 OSM Overpass 사용
2. 전체 건물 대비 위험구역 비율 산정
3. EMSR884 피해건물 교차 분석
4. VV / VH ΔCoh 지도 (ESRI WorldImagery 기반, 빨강=코히런스 감소)

임계치: RISK(위험) ΔCoh>=0.1  |  HIGH(고위험) ΔCoh>=0.4
       ΔCoh<0 제외 — co-event 코히런스 상승 = 피해 신호 아님

[DISCLAIMER] 현장 미검증 예비분석.
"""
import os, sys, io, json, gzip, math, warnings, requests
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.mask import mask as raster_mask
from rasterio.windows import from_bounds as win_from_bounds
from shapely.geometry import shape, box, mapping, Point, Polygon
from shapely.ops import unary_union
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
from matplotlib.colors import TwoSlopeNorm
warnings.filterwarnings("ignore")

matplotlib.rc("font", family="Malgun Gothic")
matplotlib.rcParams["axes.unicode_minus"] = False

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BASE  = Path(r"<DATA_ROOT>")
RIGHT = BASE / "Venezuela" / "right"
OUT   = RIGHT / "output" / "gis"
EMSR  = BASE / "EMSR884_products"

DCOH_VV = RIGHT / "output" / "dcoh_VV.tif"
DCOH_VH = RIGHT / "output" / "dcoh_VH.tif"

BLD_GPKG = OUT / "catia_lamar_ms_buildings.gpkg"

# Catia La Mar AOI
W, S, E, N = -67.075, 10.578, -66.995, 10.618
AOI_BOX = box(W, S, E, N)
AOI_DICT = {"type":"Feature","geometry":mapping(AOI_BOX),"properties":{}}

THR_RISK = 0.1
THR_HIGH = 0.4
NODATA_VAL = -9999.0

CMAP    = "RdBu_r"
NORM    = TwoSlopeNorm(vmin=-0.5, vcenter=0, vmax=0.8)

os.makedirs(OUT, exist_ok=True)

print("="*65)
print("  Catia La Mar CCD Analysis")
print(f"  AOI: W={W} S={S} E={E} N={N}")
print(f"  RISK>=  {THR_RISK}  |  HIGH>= {THR_HIGH}")
print("="*65)

# ── UTIL: quadkey (mercantile 없이) ───────────────────────────────────────────
def _ll_to_tile(lat, lon, zoom):
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(lat_r) + 1/math.cos(lat_r)) / math.pi) / 2 * n)
    y = max(0, min(n-1, y))
    return x, y

def _tile_to_qk(x, y, zoom):
    qk = []
    for i in range(zoom, 0, -1):
        d = 0
        mask = 1 << (i-1)
        if x & mask: d += 1
        if y & mask: d += 2
        qk.append(str(d))
    return "".join(qk)

def get_aoi_quadkeys(zoom=9):
    qks = set()
    for lat in [S, (S+N)/2, N]:
        for lon in [W, (W+E)/2, E]:
            x, y = _ll_to_tile(lat, lon, zoom)
            qks.add(_tile_to_qk(x, y, zoom))
    return qks

# ── 1. 건물 다운로드 ────────────────────────────────────────────────────────────
def fetch_ms_buildings():
    MS_INDEX = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
    print("\n[1] Microsoft Building Footprints 다운로드")
    try:
        resp_idx = requests.get(MS_INDEX, timeout=60)
        links = pd.read_csv(io.StringIO(resp_idx.text))
        ven = links[links["Location"].str.contains("Venezuela", case=False, na=False)].copy()
        print(f"    Venezuela 링크: {len(ven)}개")
        ven["QuadKey"] = ven["QuadKey"].astype(str)
    except Exception as e:
        print(f"    INDEX 실패: {e}")
        return None

    # 여러 zoom level 시도
    feats = []
    for zoom in [9, 8, 7]:
        qks = get_aoi_quadkeys(zoom)
        print(f"    zoom={zoom} quadkeys: {sorted(qks)}")
        hit = ven[ven["QuadKey"].isin(qks)]
        if not hit.empty:
            print(f"    매칭 {len(hit)}개")
            for _, row in hit.iterrows():
                try:
                    r = requests.get(row["Url"], timeout=120)
                    r.raise_for_status()
                    raw = r.content
                    try: text = gzip.decompress(raw).decode("utf-8")
                    except: text = raw.decode("utf-8")
                    for line in text.splitlines():
                        if not line.strip(): continue
                        obj = json.loads(line)
                        geom = shape(obj["geometry"])
                        if geom.intersects(AOI_BOX):
                            feats.append({"geometry": geom, **obj.get("properties",{})})
                except Exception as e2:
                    print(f"    타일 {row['QuadKey']} 실패: {e2}")
            break

    if not feats:
        print("    AOI 내 건물 없음 (MS)")
        return None
    gdf = gpd.GeoDataFrame(feats, crs="EPSG:4326")
    gdf = gpd.clip(gdf, AOI_BOX).reset_index(drop=True)
    print(f"    MS 건물: {len(gdf)}개")
    return gdf

def fetch_osm_buildings():
    """OSM Overpass fallback"""
    print("\n[1] OSM Overpass 건물 다운로드 (fallback)")
    import urllib.parse
    q = (f"[out:json][timeout:60];"
         f"(way[\"building\"]({S},{W},{N},{E});"
         f"relation[\"building\"][\"type\"=\"multipolygon\"]({S},{W},{N},{E}););"
         f"out geom;")
    # 복수 서버 시도
    for url in ["https://overpass-api.de/api/interpreter",
                "https://overpass.kumi.systems/api/interpreter",
                "https://overpass.private.coffee/api/interpreter"]:
        try:
            resp = requests.get(url, params={"data": q}, timeout=90)
            if resp.status_code == 200:
                break
            print(f"    {url.split('/')[2]}: {resp.status_code}")
        except Exception as e:
            print(f"    {url.split('/')[2]}: {e}")
    try:
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    OSM 실패: {e}")
        return None

    feats = []
    for el in data.get("elements", []):
        if el["type"] == "way" and "geometry" in el:
            coords = [(nd["lon"], nd["lat"]) for nd in el["geometry"]]
            if len(coords) >= 4:
                try:
                    poly = Polygon(coords)
                    if poly.is_valid and poly.intersects(AOI_BOX):
                        feats.append({"osm_id": el["id"], "geometry": poly,
                                     "bld_type": el.get("tags",{}).get("building","yes")})
                except: pass

    if not feats:
        print("    OSM 건물 없음")
        return None
    gdf = gpd.GeoDataFrame(feats, crs="EPSG:4326")
    gdf = gpd.clip(gdf, AOI_BOX).reset_index(drop=True)
    print(f"    OSM 건물: {len(gdf)}개")
    return gdf

# 캐시 확인 후 다운로드
if BLD_GPKG.exists():
    print(f"\n[1] 건물 캐시 로드: {BLD_GPKG.name}")
    ms_bld = gpd.read_file(BLD_GPKG)
    print(f"    {len(ms_bld)}개")
    bld_source = "캐시"
else:
    ms_bld = fetch_ms_buildings()
    bld_source = "MS GlobalMLBuildingFootprints"
    if ms_bld is None or ms_bld.empty:
        ms_bld = fetch_osm_buildings()
        bld_source = "OpenStreetMap Overpass"
    if ms_bld is not None and len(ms_bld) > 0:
        ms_bld.to_file(BLD_GPKG, driver="GPKG")
        print(f"    저장: {BLD_GPKG.name}")
    else:
        print("    [!] 건물 데이터 없음 — EMSR884만 사용")
        ms_bld = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

ms_bld["centroid"] = ms_bld.geometry.centroid
ms_bld_pts = gpd.GeoDataFrame(ms_bld[["centroid"]].rename(columns={"centroid":"geometry"}),
                               crs="EPSG:4326")

# ── 2. EMSR884 데이터 (AOI clip) ──────────────────────────────────────────────
print("\n[2] EMSR884 로드 (Catia La Mar AOI clip)")
BLDP_PATHS = [
    EMSR/"EMSR884_AOI02_GRA_MONIT01_v2"/"EMSR884_AOI02_GRA_MONIT01_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI05_GRA_PRODUCT_v1"/"EMSR884_AOI05_GRA_PRODUCT_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI06_GRA_MONIT01_v2"/"EMSR884_AOI06_GRA_MONIT01_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI08_GRA_MONIT01_v2"/"EMSR884_AOI08_GRA_MONIT01_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_builtUpA_v2.shp",
]
ROAD_PATHS = [
    EMSR/"EMSR884_AOI02_GRA_MONIT01_v2"/"EMSR884_AOI02_GRA_MONIT01_transportationL_v1.shp",
    EMSR/"EMSR884_AOI05_GRA_PRODUCT_v1"/"EMSR884_AOI05_GRA_PRODUCT_transportationL_v1.shp",
    EMSR/"EMSR884_AOI06_GRA_MONIT01_v2"/"EMSR884_AOI06_GRA_MONIT01_transportationL_v1.shp",
    EMSR/"EMSR884_AOI08_GRA_MONIT01_v2"/"EMSR884_AOI08_GRA_MONIT01_transportationL_v2.shp",
    EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_transportationL_v2.shp",
]

emsr_parts = []
for p in BLDP_PATHS:
    if not Path(p).exists(): continue
    g = gpd.read_file(p).to_crs("EPSG:4326")
    if "builtUpA" in str(p):
        g["geometry"] = g.geometry.centroid  # 폴리곤 → 센트로이드
    c = gpd.clip(g, AOI_BOX)
    if len(c) > 0:
        c = c.copy(); c["src"] = Path(p).stem
        emsr_parts.append(c)
        print(f"    {Path(p).stem}: {len(c)}개")

emsr_bld = pd.concat(emsr_parts, ignore_index=True) if emsr_parts else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

road_parts = []
for p in ROAD_PATHS:
    if not Path(p).exists(): continue
    g = gpd.read_file(p).to_crs("EPSG:4326")
    c = gpd.clip(g, AOI_BOX)
    if len(c) > 0:
        road_parts.append(c)
roads_aoi = pd.concat(road_parts, ignore_index=True) if road_parts else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
print(f"    도로 세그먼트: {len(roads_aoi)}개")

# EMSR 피해건물 폴리곤 (AOI12, clip)
emsr_bldA_raw = None
bldA_path = EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_builtUpA_v2.shp"
if bldA_path.exists():
    bldA = gpd.read_file(bldA_path).to_crs("EPSG:4326")
    emsr_bldA_raw = gpd.clip(bldA, AOI_BOX)
    print(f"    EMSR 건물폴리곤(AOI12 clip): {len(emsr_bldA_raw)}개")

# ── 3. ΔCoh TIF 클립 & 샘플링 ────────────────────────────────────────────────
print("\n[3] dcoh TIF 로드 (AOI clip)")

def load_dcoh_clip(tif_path):
    """Return (data_array, extent_4326)"""
    with rasterio.open(tif_path) as src:
        win = win_from_bounds(W, S, E, N, src.transform)
        data = src.read(1, window=win).astype(np.float32)
        wt = src.window_transform(win)
    h, w = data.shape
    x0 = wt.c; y1 = wt.f
    x1 = x0 + w*wt.a; y0 = y1 + h*wt.e
    data[data == NODATA_VAL] = np.nan
    extent = [x0, x1, y0, y1]  # [left, right, bottom, top]
    return data, extent

dcoh_vv, ext_vv = load_dcoh_clip(DCOH_VV)
dcoh_vh, ext_vh = load_dcoh_clip(DCOH_VH)
print(f"    VV shape={dcoh_vv.shape}  valid={np.isfinite(dcoh_vv).sum()}")
print(f"    VH shape={dcoh_vh.shape}  valid={np.isfinite(dcoh_vh).sum()}")

def sample_dcoh(tif_path, gdf_pts):
    coords = [(p.x, p.y) for p in gdf_pts.geometry]
    if not coords: return np.array([])
    with rasterio.open(tif_path) as src:
        vals = [float(list(src.sample([c]))[0][0]) for c in coords]
    arr = np.array(vals, dtype=np.float32)
    arr[arr == NODATA_VAL] = np.nan
    return arr

# ── 4. 전체 건물 분석 ─────────────────────────────────────────────────────────
print("\n[4] 전체 건물 CCD 분석")
bld_summary = {}

if len(ms_bld_pts) > 0:
    vv_ms = sample_dcoh(DCOH_VV, ms_bld_pts)
    ms_bld["dcoh_vv"] = vv_ms
    ms_bld["cls_vv"] = 0
    ms_bld.loc[ms_bld["dcoh_vv"] >= THR_RISK, "cls_vv"] = 1
    ms_bld.loc[ms_bld["dcoh_vv"] >= THR_HIGH, "cls_vv"] = 2
    ms_bld.loc[ms_bld["dcoh_vv"].isna(), "cls_vv"] = -1

    total = len(ms_bld)
    in_risk = (ms_bld["cls_vv"] >= 1).sum()
    in_high = (ms_bld["cls_vv"] == 2).sum()
    in_nodata = (ms_bld["cls_vv"] == -1).sum()
    print(f"    전체: {total}  RISK+HIGH: {in_risk} ({100*in_risk/total:.1f}%)  "
          f"HIGH: {in_high} ({100*in_high/total:.1f}%)  노데이터: {in_nodata}")
    bld_summary = {"total":total,"in_risk":int(in_risk),"in_high":int(in_high),
                   "pct_risk":round(100*in_risk/total,1),"pct_high":round(100*in_high/total,1),
                   "in_nodata":int(in_nodata)}
else:
    print("    건물 데이터 없음 — EMSR884만 분석")

# ── 5. EMSR884 피해건물 분석 (AOI clip) ──────────────────────────────────────
print("\n[5] EMSR884 피해건물 (Catia La Mar clip) CCD 분석")
emsr_rows = []
DMG_ORDER = ["Destroyed","Damaged","Possibly damaged","No visible damage","Not Analysed"]
DMG_COLOR = {"Destroyed":"#d73027","Damaged":"#fc8d59","Possibly damaged":"#fee08b",
             "No visible damage":"#91cf60","Not Analysed":"#aaaaaa"}

if len(emsr_bld) > 0:
    vv_e = sample_dcoh(DCOH_VV, emsr_bld)
    emsr_bld = emsr_bld.copy()
    emsr_bld["dcoh_vv"] = vv_e
    emsr_bld["cls_vv"] = 0
    emsr_bld.loc[emsr_bld["dcoh_vv"] >= THR_RISK, "cls_vv"] = 1
    emsr_bld.loc[emsr_bld["dcoh_vv"] >= THR_HIGH, "cls_vv"] = 2

    for dmg in DMG_ORDER:
        sub = emsr_bld[emsr_bld["damage_gra"]==dmg]
        if len(sub)==0: continue
        n_r = (sub["cls_vv"]>=1).sum(); n_h=(sub["cls_vv"]==2).sum()
        print(f"    [{dmg}] {n_r}/{len(sub)} RISK  {n_h}/{len(sub)} HIGH")
        emsr_rows.append({"grade":dmg,"n":len(sub),"n_risk":int(n_r),"n_high":int(n_h),
                          "pct_risk":round(100*n_r/len(sub),1),"pct_high":round(100*n_h/len(sub),1)})

# ── 6. 보고서 ─────────────────────────────────────────────────────────────────
print("\n[6] 보고서 생성")

R=[]; r=R.append
r("# Catia La Mar CCD 분석 보고서")
r(f"**AOI**: 경도 {W}~{E}, 위도 {S}~{N} (La Guaira / Catia La Mar 해안 시가지)  ")
r(f"**임계치**: RISK(위험) ΔCoh ≥ {THR_RISK}  |  HIGH(고위험) ΔCoh ≥ {THR_HIGH}  ")
r("**[DISCLAIMER]** 현장 미검증 예비분석. 확정 피해 판정 아님.\n")

r("---"); r("## 1. 임계치 근거 (신뢰도 기반)")
r("")
r("| 구분 | ΔCoh 범위 | 의미 | 신뢰성 |")
r("|------|---------|------|------|")
r("| 제외 | < 0.0 | co-event 코히런스 상승 = 피해 반대 방향 | 피해 신호 없음 |")
r("| 제외 | 0.0 ~ 0.1 | 노이즈 플로어 수준 | 불확실 |")
r(f"| RISK(위험) | {THR_RISK} ~ {THR_HIGH} | 유의미한 코히런스 손실 | 신뢰 |")
r(f"| HIGH(고위험) | ≥ {THR_HIGH} | 강한 코히런스 급락 | 높은 신뢰 |")
r("")
r("**참고**: 이전 분석에서 Destroyed 건물 1개가 ΔCoh=-0.1784 → 이 건물은 co-event 이후 코히런스가 오히려 상승. ")
r("잔해 specular reflection, 측정 노이즈 등으로 CCD false negative 처리. 하한을 -0.2로 낮추는 것은 물리적 근거 없음.")
r("")

if bld_summary:
    r("---"); r("## 2. 전체 건물 기반 피해 비율")
    r("")
    r(f"**건물 데이터**: {bld_source}")
    r(f"**Catia La Mar AOI 내 전체 건물**: {bld_summary['total']}개  ")
    r("")
    r("| 구분 | 건물수 | 비율 |")
    r("|------|------|------|")
    r(f"| 전체 | {bld_summary['total']} | 100% |")
    r(f"| RISK+HIGH (ΔCoh≥{THR_RISK}) | {bld_summary['in_risk']} | {bld_summary['pct_risk']}% |")
    r(f"| HIGH (ΔCoh≥{THR_HIGH}) | {bld_summary['in_high']} | {bld_summary['pct_high']}% |")
    r(f"| 노데이터/장면외 | {bld_summary['in_nodata']} | - |")
    r("")

if emsr_rows:
    r("---"); r("## 3. EMSR884 피해건물 × CCD (Catia La Mar 내)")
    r("")
    r("| 피해등급 | 전체 | RISK+HIGH | 검출률 | HIGH | HIGH검출률 |")
    r("|---------|------|---------|------|------|---------|")
    for row in emsr_rows:
        r(f"| {row['grade']} | {row['n']} | {row['n_risk']} | {row['pct_risk']}% | {row['n_high']} | {row['pct_high']}% |")
    r("")

r("---"); r("## 4. VV vs VH 비교")
r("")
r("| 편파 | 유효픽셀 | 평균 ΔCoh | RISK 픽셀수 | HIGH 픽셀수 |")
r("|-----|--------|--------|---------|---------|")
for pol, arr in [("VV", dcoh_vv), ("VH", dcoh_vh)]:
    fin = arr[np.isfinite(arr)]
    n_r = int((fin >= THR_RISK).sum()); n_h = int((fin >= THR_HIGH).sum())
    r(f"| {pol} | {len(fin):,} | {fin.mean():.4f} | {n_r:,} | {n_h:,} |")
r("")

r("---"); r("## 5. 지도 출력")
r("")
r("- `catia_lamar_VV.png`: VV 편파 ΔCoh 지도 (ESRI + 건물/도로)")
r("- `catia_lamar_VH.png`: VH 편파 ΔCoh 지도 (ESRI + 건물/도로)")
r("- 컬러바: 빨강=코히런스 감소(피해 의심), 파랑=코히런스 증가(신호 없음), 흰색=변화없음")
r("")
r("---"); r("## 6. 한계사항")
r("")
r("- Catia La Mar AOI가 CCD 장면 가장자리에 위치할 경우 노데이터 비율 증가")
r("- VH 편파는 VV보다 노이즈 높음 — VV 결과 우선 참고")
r("- MS/OSM 건물 데이터는 지진 전 baseline — 붕괴된 건물 미반영")
r("- 단일 co-event pair 기반, 통계적 임계값 검증 불가")
r("")
r("---")
r("*[DISCLAIMER] 현장 미검증 예비분석.*")

rpt = OUT / "catia_lamar_report.md"
with open(rpt, "w", encoding="utf-8") as f: f.write("\n".join(R))
print(f"    저장: {rpt.name}")

# ── 7. 지도 생성 ───────────────────────────────────────────────────────────────
print("\n[7] 지도 생성")

def make_ccd_map(dcoh_arr, extent, pol_name, out_path):
    """
    ESRI WorldImagery 기반 CCD 지도 생성.
    extent = [left, right, bottom, top] in EPSG:4326
    """
    fig, ax = plt.subplots(figsize=(14, 12))
    ax.set_xlim(W, E)
    ax.set_ylim(S, N)
    ax.set_aspect("equal")

    # ESRI 베이스맵 (contextily)
    try:
        import contextily as cx
        cx.add_basemap(ax, crs="EPSG:4326",
                       source=cx.providers.Esri.WorldImagery,
                       zoom="auto", zorder=0)
        print(f"    [{pol_name}] ESRI 베이스맵 추가")
    except Exception as e:
        print(f"    [{pol_name}] 베이스맵 실패(오프라인?): {e}")
        ax.set_facecolor("#c8d7e1")

    # coherence 래스터 오버레이
    data_ma = np.ma.masked_invalid(dcoh_arr)
    im = ax.imshow(data_ma, cmap=CMAP, norm=NORM,
                   extent=extent,          # [left, right, bottom, top]
                   origin="upper",
                   alpha=0.62, zorder=2,
                   interpolation="bilinear")

    # MS 건물 (전체 윤곽선)
    if len(ms_bld) > 0:
        ms_bld.boundary.plot(ax=ax, color="white", lw=0.4, alpha=0.45, zorder=3,
                              label=f"전체건물({bld_source}, {len(ms_bld)}개)")

    # 도로
    if len(roads_aoi) > 0:
        roads_aoi.plot(ax=ax, color="#f0e040", lw=0.7, alpha=0.55, zorder=4,
                       label=f"도로 ({len(roads_aoi)}개)")

    # EMSR884 건물 폴리곤 (AOI12 경계)
    if emsr_bldA_raw is not None and len(emsr_bldA_raw) > 0:
        for dmg, grp in emsr_bldA_raw.groupby("damage_gra"):
            color = DMG_COLOR.get(dmg, "#888888")
            grp.boundary.plot(ax=ax, color=color, lw=1.5, alpha=0.9, zorder=5)

    # EMSR884 포인트 (Destroyed, Damaged)
    if len(emsr_bld) > 0:
        for dmg, grp in emsr_bld.groupby("damage_gra"):
            if dmg not in ["Destroyed","Damaged","Possibly damaged"]: continue
            color = DMG_COLOR.get(dmg, "#888")
            mk = {"Destroyed":"X","Damaged":"^","Possibly damaged":"o"}.get(dmg,"s")
            ms_size = {"Destroyed":120,"Damaged":70,"Possibly damaged":40}.get(dmg,40)
            ax.scatter(grp.geometry.x, grp.geometry.y,
                       c=color, marker=mk, s=ms_size,
                       edgecolors="white" if dmg!="Destroyed" else "none",
                       linewidths=0.8, alpha=0.95, zorder=6,
                       label=f"{dmg} ({len(grp)}개)")

    # 컬러바
    cbar = plt.colorbar(im, ax=ax, shrink=0.55, pad=0.015, aspect=30)
    cbar.set_label(f"ΔCoh = γ_pre − γ_co ({pol_name})", fontsize=11)
    cbar.ax.yaxis.set_tick_params(labelsize=9)
    # 임계치 라인
    for thr, lbl in [(THR_RISK,"RISK"), (THR_HIGH,"HIGH")]:
        cbar.ax.axhline(y=(thr - NORM.vmin)/(NORM.vmax - NORM.vmin),
                         color="black", lw=1.5, ls="--")
        cbar.ax.text(1.05, (thr - NORM.vmin)/(NORM.vmax - NORM.vmin),
                      f"≥{thr} ({lbl})", transform=cbar.ax.transAxes,
                      va="center", fontsize=8)

    # 범례 (건물/도로)
    patches = [
        mpatches.Patch(facecolor="none", edgecolor="white", lw=1.0,
                       label=f"전체 건물({bld_source})"),
        mpatches.Patch(facecolor="#f0e040", label="도로(EMSR884)"),
        mpatches.Patch(facecolor=DMG_COLOR["Destroyed"], label="EMSR Destroyed"),
        mpatches.Patch(facecolor=DMG_COLOR["Damaged"], label="EMSR Damaged"),
        mpatches.Patch(facecolor=DMG_COLOR["Possibly damaged"], label="EMSR Possibly damaged"),
    ]
    ax.legend(handles=patches, loc="lower left", fontsize=8,
              framealpha=0.8, facecolor="white", edgecolor="gray", ncol=1)

    # 라벨
    ax.set_xlabel("경도 (Longitude)", fontsize=10)
    ax.set_ylabel("위도 (Latitude)", fontsize=10)
    ax.set_title(
        f"Catia La Mar / La Guaira — SAR 코히런스 변화({pol_name}편파)\n"
        f"빨강: 코히런스 감소(피해 의심, ΔCoh>0)  |  파랑: 코히런스 증가(신호 없음)  "
        f"|  RISK≥{THR_RISK}  HIGH≥{THR_HIGH}\n"
        f"[DISCLAIMER] 현장 미검증 예비분석",
        fontsize=11, fontweight="bold", pad=12
    )
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"    저장: {out_path.name}  ({out_path.stat().st_size//1024}KB)")

make_ccd_map(dcoh_vv, ext_vv, "VV", OUT/"catia_lamar_VV.png")
make_ccd_map(dcoh_vh, ext_vh, "VH", OUT/"catia_lamar_VH.png")

# ── 8. 비교 그림 (VV / VH 나란히) ────────────────────────────────────────────
print("\n[8] VV / VH 비교 그림")

try:
    import contextily as cx
    has_cx = True
except:
    has_cx = False

fig, axes = plt.subplots(1, 2, figsize=(24, 11))

for ax, arr, ext, pol in [(axes[0], dcoh_vv, ext_vv, "VV"),
                           (axes[1], dcoh_vh, ext_vh, "VH")]:
    ax.set_xlim(W, E); ax.set_ylim(S, N); ax.set_aspect("equal")

    if has_cx:
        try:
            cx.add_basemap(ax, crs="EPSG:4326",
                           source=cx.providers.Esri.WorldImagery, zoom="auto", zorder=0)
        except: ax.set_facecolor("#c8d7e1")
    else:
        ax.set_facecolor("#c8d7e1")

    data_ma = np.ma.masked_invalid(arr)
    im = ax.imshow(data_ma, cmap=CMAP, norm=NORM, extent=ext,
                   origin="upper", alpha=0.62, zorder=2, interpolation="bilinear")

    if len(ms_bld) > 0:
        ms_bld.boundary.plot(ax=ax, color="white", lw=0.35, alpha=0.4, zorder=3)
    if len(roads_aoi) > 0:
        roads_aoi.plot(ax=ax, color="#f0e040", lw=0.6, alpha=0.5, zorder=4)
    if emsr_bldA_raw is not None and len(emsr_bldA_raw)>0:
        for dmg, grp in emsr_bldA_raw.groupby("damage_gra"):
            grp.boundary.plot(ax=ax, color=DMG_COLOR.get(dmg,"#888"), lw=1.4, alpha=0.9, zorder=5)
    if len(emsr_bld) > 0:
        for dmg, grp in emsr_bld.groupby("damage_gra"):
            if dmg not in ["Destroyed","Damaged"]: continue
            mk = "X" if dmg=="Destroyed" else "^"
            sz = 100 if dmg=="Destroyed" else 60
            ax.scatter(grp.geometry.x, grp.geometry.y,
                       c=DMG_COLOR[dmg], marker=mk, s=sz,
                       edgecolors="white" if dmg!="Destroyed" else "none",
                       linewidths=0.7, alpha=0.95, zorder=6)

    cbar = plt.colorbar(im, ax=ax, shrink=0.55, pad=0.01, aspect=25)
    cbar.set_label(f"ΔCoh ({pol})", fontsize=10)
    ax.set_title(
        f"【{pol}】 코히런스 변화 — 빨강: 감소(피해 의심)  파랑: 증가",
        fontsize=11, fontweight="bold"
    )
    ax.set_xlabel("경도"); ax.set_ylabel("위도"); ax.tick_params(labelsize=8)

    # 건물 통계 텍스트
    if bld_summary:
        ax.text(0.02, 0.97,
                f"전체건물: {bld_summary['total']}개\n"
                f"RISK+HIGH: {bld_summary['in_risk']}개 ({bld_summary['pct_risk']}%)\n"
                f"HIGH: {bld_summary['in_high']}개 ({bld_summary['pct_high']}%)",
                transform=ax.transAxes, va="top", fontsize=9,
                bbox=dict(boxstyle="round,pad=0.4", fc="white", alpha=0.85), zorder=10)

# 공통 범례
patches2 = [
    mpatches.Patch(fc="none", ec="white", lw=1, label="전체 건물(MS/OSM)"),
    mpatches.Patch(fc="#f0e040", label="도로(EMSR884)"),
    mpatches.Patch(fc=DMG_COLOR["Destroyed"], label="EMSR Destroyed (✕)"),
    mpatches.Patch(fc=DMG_COLOR["Damaged"], label="EMSR Damaged (▲)"),
]
fig.legend(handles=patches2, loc="lower center", fontsize=9,
           ncol=4, framealpha=0.85, bbox_to_anchor=(0.5, 0.0))

fig.suptitle(
    f"Catia La Mar / La Guaira SAR 코히런스 변화 비교 (VV vs VH)\n"
    f"RISK≥{THR_RISK}  HIGH≥{THR_HIGH}  |  [DISCLAIMER] 현장 미검증 예비분석",
    fontsize=12, fontweight="bold", y=1.01
)
plt.tight_layout(rect=[0, 0.05, 1, 1])
comp_path = OUT / "catia_lamar_compare.png"
fig.savefig(comp_path, dpi=200, bbox_inches="tight", facecolor="white")
plt.close()
print(f"    저장: {comp_path.name}  ({comp_path.stat().st_size//1024}KB)")

# ── 최종 요약 ──────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  완료")
if bld_summary:
    print(f"  전체 건물: {bld_summary['total']}개")
    print(f"  위험구역(RISK+HIGH): {bld_summary['in_risk']}개 ({bld_summary['pct_risk']}%)")
    print(f"  고위험(HIGH): {bld_summary['in_high']}개 ({bld_summary['pct_high']}%)")
for row in emsr_rows:
    print(f"  EMSR {row['grade']}: {row['n_risk']}/{row['n']} RISK ({row['pct_risk']}%)")
print()
for f in sorted(OUT.glob("catia_lamar*")):
    print(f"    {f.name:<48} {f.stat().st_size//1024:>5}KB")
print("="*65)
print("[DISCLAIMER] 현장 미검증 예비분석.")
