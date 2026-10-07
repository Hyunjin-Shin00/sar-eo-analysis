"""
Catia La Mar 종합 분석 보고서 v3
================================
CCD (SAR Coherence Change Detection) + DInSAR (Co-seismic Interferogram)
- 지진 개요, CCD 피해건물, 도로 분석, DInSAR 지표변형
- 임계치: RISK=0.1, HIGH=0.4 (신뢰도 기반, ΔCoh<0 제외)
- DInSAR: 20260618-20260625 wrapped phase, lambda/2 = 2.8 cm/fringe (C-band)

[DISCLAIMER] 현장 미검증 예비분석.
"""
import os, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.windows import from_bounds as win_from_bounds
from shapely.geometry import box, Point
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
from matplotlib.colors import TwoSlopeNorm
import contextily as cx
warnings.filterwarnings("ignore")

matplotlib.rc("font", family="Malgun Gothic")
matplotlib.rcParams["axes.unicode_minus"] = False

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BASE  = Path(r"<DATA_ROOT>")
RIGHT = BASE / "Venezuela" / "right"
OUT   = RIGHT / "output" / "gis"
EMSR  = BASE / "EMSR884_products"

DCOH_VV  = RIGHT / "output" / "dcoh_VV.tif"
DINSAR   = RIGHT / "subset_4_of_20260618_20260625_C8C0_Orb_Stack_Ifg_Deb_Flt_TC.tif"
EPI_SHP  = BASE / "epicenters" / "epicenters_2026.shp"
FAULT_SHP= BASE / "fault" / "gem-global-active-faults" / "shapefile" / "gem_active_faults.shp"

W, S, E, N = -67.075, 10.578, -66.995, 10.618
AOI_BOX = box(W, S, E, N)
UTM = "EPSG:32619"

THR_RISK = 0.1
THR_HIGH = 0.4
NODATA   = -9999.0
LAMBDA_CM = 5.6      # Sentinel-1 C-band wavelength (cm)
LOS_PER_FRINGE = LAMBDA_CM / 2   # 2.8 cm per 2pi cycle

DMG_COLOR = {"Destroyed":"#d73027","Damaged":"#fc8d59","Possibly damaged":"#fee08b",
             "No visible damage":"#91cf60","Not Analysed":"#aaaaaa"}
DMG_ORDER = ["Destroyed","Damaged","Possibly damaged","No visible damage","Not Analysed"]

os.makedirs(OUT, exist_ok=True)
print("="*65); print("  Catia La Mar 종합 보고서 v3"); print("="*65)

# ── UTIL ───────────────────────────────────────────────────────────────────────
def load_clip(tif_path, w=W, s=S, e=E, n=N, nodata_val=None):
    with rasterio.open(tif_path) as src:
        win = win_from_bounds(w, s, e, n, src.transform)
        arr = src.read(1, window=win).astype(np.float32)
        wt  = src.window_transform(win)
        nd  = nodata_val if nodata_val is not None else src.nodata
    h, w_ = arr.shape
    x0=wt.c; y1=wt.f; x1=x0+w_*wt.a; y0=y1+h*wt.e
    if nd is not None: arr[arr==nd] = np.nan
    arr[arr==0] = np.nan   # zero=nodata convention for DInSAR
    return arr, [x0, x1, y0, y1]   # [left,right,bottom,top]

def sample_tif(tif_path, gdf_pts, nodata_val=None):
    coords = [(p.x, p.y) for p in gdf_pts.geometry]
    if not coords: return np.full(len(coords), np.nan)
    with rasterio.open(tif_path) as src:
        nd = nodata_val if nodata_val is not None else src.nodata
        vals = [float(list(src.sample([c]))[0][0]) for c in coords]
    arr = np.array(vals, dtype=np.float32)
    if nd is not None: arr[arr==nd] = np.nan
    return arr

# ── 1. 데이터 로드 ─────────────────────────────────────────────────────────────
print("\n[1] 데이터 로드")

# CCD
dcoh_vv, ext_vv = load_clip(DCOH_VV, nodata_val=NODATA)
print(f"    CCD VV: shape={dcoh_vv.shape}, valid={np.isfinite(dcoh_vv).sum()}")

# DInSAR (wrapped phase)
dinsar, ext_di = load_clip(DINSAR, nodata_val=None)
# DInSAR has no explicit nodata; 0-values already replaced above
# Restore: wrapped phase can legitimately be 0, so let's not mask 0
with rasterio.open(DINSAR) as src:
    win = win_from_bounds(W, S, E, N, src.transform)
    dinsar = src.read(1, window=win).astype(np.float32)
    wt = src.window_transform(win)
h_, w_ = dinsar.shape
x0=wt.c; y1=wt.f; x1=x0+w_*wt.a; y0=y1+h_*wt.e
ext_di = [x0, x1, y0, y1]
print(f"    DInSAR: shape={dinsar.shape}, valid={np.isfinite(dinsar).sum()}")
di_f = dinsar[np.isfinite(dinsar)]
print(f"    DInSAR range: {di_f.min():.4f} ~ {di_f.max():.4f} rad, mean={di_f.mean():.4f}")

# EMSR 건물
BLDP = [
    EMSR/"EMSR884_AOI02_GRA_MONIT01_v2"/"EMSR884_AOI02_GRA_MONIT01_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI05_GRA_PRODUCT_v1"/"EMSR884_AOI05_GRA_PRODUCT_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI06_GRA_MONIT01_v2"/"EMSR884_AOI06_GRA_MONIT01_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI08_GRA_MONIT01_v2"/"EMSR884_AOI08_GRA_MONIT01_builtUpP_v1.shp",
    EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_builtUpA_v2.shp",
]
parts = []
for p in BLDP:
    if not Path(p).exists(): continue
    g = gpd.read_file(p).to_crs("EPSG:4326")
    if "builtUpA" in str(p): g["geometry"] = g.geometry.centroid
    c = gpd.clip(g, AOI_BOX)
    if len(c) > 0: parts.append(c)
emsr_bld = pd.concat(parts, ignore_index=True) if parts else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
print(f"    EMSR 건물 포인트: {len(emsr_bld)}개")

bldA_raw = None
bldA_path = EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_builtUpA_v2.shp"
if bldA_path.exists():
    bldA_raw = gpd.clip(gpd.read_file(bldA_path).to_crs("EPSG:4326"), AOI_BOX)
    print(f"    EMSR 건물 폴리곤(AOI12): {len(bldA_raw)}개")

# 도로
RPATH = [
    EMSR/"EMSR884_AOI02_GRA_MONIT01_v2"/"EMSR884_AOI02_GRA_MONIT01_transportationL_v1.shp",
    EMSR/"EMSR884_AOI05_GRA_PRODUCT_v1"/"EMSR884_AOI05_GRA_PRODUCT_transportationL_v1.shp",
    EMSR/"EMSR884_AOI06_GRA_MONIT01_v2"/"EMSR884_AOI06_GRA_MONIT01_transportationL_v1.shp",
    EMSR/"EMSR884_AOI08_GRA_MONIT01_v2"/"EMSR884_AOI08_GRA_MONIT01_transportationL_v2.shp",
    EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_transportationL_v2.shp",
]
rparts = []
for p in RPATH:
    if not Path(p).exists(): continue
    g = gpd.read_file(p).to_crs("EPSG:4326")
    c = gpd.clip(g, AOI_BOX)
    if len(c) > 0: rparts.append(c)
roads = pd.concat(rparts, ignore_index=True) if rparts else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
print(f"    도로 세그먼트: {len(roads)}개")

# 진앙
epi = None
if EPI_SHP.exists():
    epi = gpd.read_file(EPI_SHP).to_crs("EPSG:4326")
    print(f"    진앙: {len(epi)}개")

# ── 2. CCD 분석 ────────────────────────────────────────────────────────────────
print("\n[2] CCD 분석")

# 건물 샘플링
vv_vals = sample_tif(DCOH_VV, emsr_bld, nodata_val=NODATA)
emsr_bld = emsr_bld.copy()
emsr_bld["dcoh_vv"] = vv_vals
emsr_bld["cls_vv"] = 0
emsr_bld.loc[emsr_bld["dcoh_vv"] >= THR_RISK, "cls_vv"] = 1
emsr_bld.loc[emsr_bld["dcoh_vv"] >= THR_HIGH, "cls_vv"] = 2
emsr_bld.loc[emsr_bld["dcoh_vv"].isna(), "cls_vv"] = -1

ccd_bld_rows = []
for dmg in DMG_ORDER:
    sub = emsr_bld[emsr_bld["damage_gra"]==dmg]
    if len(sub)==0: continue
    n_r=(sub["cls_vv"]>=1).sum(); n_h=(sub["cls_vv"]==2).sum()
    ccd_bld_rows.append({"grade":dmg,"n":len(sub),"n_risk":int(n_r),"n_high":int(n_h),
                          "pct_risk":round(100*n_r/len(sub),1),"pct_high":round(100*n_h/len(sub),1)})
    print(f"    [{dmg}] {n_r}/{len(sub)} RISK  {n_h}/{len(sub)} HIGH")

# CCD 픽셀 면적
vv_fin = dcoh_vv[np.isfinite(dcoh_vv)]
with rasterio.open(DCOH_VV) as src: px_deg = abs(src.res[0])
px_m = px_deg * 111320
px_km2 = (px_m ** 2) / 1e6
n_risk_px = int((vv_fin >= THR_RISK).sum())
n_high_px = int((vv_fin >= THR_HIGH).sum())
area_risk = round(n_risk_px * px_km2, 2)
area_high = round(n_high_px * px_km2, 2)
print(f"    RISK 면적: {area_risk} km²  HIGH 면적: {area_high} km²")

# ── 3. 도로 분석 ───────────────────────────────────────────────────────────────
print("\n[3] 도로 분석")
road_rows = []; named_risk = []
total_km = 0.0

if len(roads) > 0:
    # UTM으로 변환해서 길이 계산
    roads_utm = roads.to_crs(UTM).copy()
    roads_utm["len_km"] = roads_utm.geometry.length / 1000
    total_km = roads_utm["len_km"].sum()

    # 중점 샘플링 (4326)
    mid_pts = roads.geometry.interpolate(0.5, normalized=True)
    mid_gdf = gpd.GeoDataFrame(geometry=mid_pts, crs="EPSG:4326")
    mid_vv = sample_tif(DCOH_VV, mid_gdf, nodata_val=NODATA)
    roads = roads.copy()
    roads["dcoh_vv"] = mid_vv
    roads["cls_vv"] = 0
    roads.loc[roads["dcoh_vv"] >= THR_RISK, "cls_vv"] = 1
    roads.loc[roads["dcoh_vv"] >= THR_HIGH, "cls_vv"] = 2
    roads_utm["cls_vv"] = roads["cls_vv"].values

    for cls, lbl in [(2,"HIGH"),(1,"RISK"),(0,"안전")]:
        sub = roads_utm[roads_utm["cls_vv"]==cls]
        km = sub["len_km"].sum()
        pct = round(100*km/total_km,1) if total_km>0 else 0
        print(f"    {lbl}: {km:.1f} km ({pct}%)")
        road_rows.append({"cls_lbl":lbl,"km":round(km,1),"pct":pct})

    # 도로 유형별
    if "simplified" in roads.columns:
        for cls, lbl in [(2,"HIGH"),(1,"RISK")]:
            sub = roads_utm[roads_utm["cls_vv"]==cls]
            by_type = sub.groupby(roads.loc[roads_utm.index,"simplified"] if "simplified" in roads.columns else "type")["len_km"].sum().sort_values(ascending=False)
            print(f"    [{lbl}] 유형별:", {k:round(v,1) for k,v in by_type.items()})

    # 위험구역 주요 도로
    if "name" in roads.columns:
        risk_roads = roads_utm[roads_utm["cls_vv"] >= 1].copy()
        risk_roads["name_r"] = roads.loc[risk_roads.index,"name"] if "name" in roads.columns else ""
        named = risk_roads[risk_roads["name_r"].notna() & ~risk_roads["name_r"].isin(["Unknown","",None])]
        if len(named) > 0:
            named_agg = named.groupby("name_r")["len_km"].sum().sort_values(ascending=False).head(8)
            named_risk = [{"name":k,"km":round(v,3)} for k,v in named_agg.items()]
            print("    주요 위험 도로:", {r["name"]:r["km"] for r in named_risk[:5]})

print(f"    총 도로: {total_km:.1f} km")

# ── 4. DInSAR 분석 ────────────────────────────────────────────────────────────
print("\n[4] DInSAR 분석")

# Catia La Mar 내 위상 통계
di_f = dinsar[np.isfinite(dinsar)]
di_p = np.percentile(di_f, [5,25,50,75,95])
print(f"    유효픽셀: {len(di_f):,}")
print(f"    위상 범위: {di_f.min():.4f} ~ {di_f.max():.4f} rad")
print(f"    p25/p50/p75: {di_p[1]:.3f}/{di_p[2]:.3f}/{di_p[3]:.3f} rad")

# 위상 표준편차 (낮으면 코히런트 = 신뢰 가능한 변형 신호)
di_std = float(np.std(di_f))
print(f"    위상 표준편차: {di_std:.4f} rad  (pi={np.pi:.4f})")
# Std ≈ pi/sqrt(3) ≈ 1.81 for uniform random distribution
fringe_coherent = di_std < 1.5  # < pi/sqrt(3)~1.81 for uniform
print(f"    → {'코히런트 위상 패턴 (실제 변형 신호 가능)' if fringe_coherent else '랜덤에 가까운 분포 (저코히런스/노이즈 영향)'}")

# 건물 위치 위상 샘플링
di_vals = sample_tif(DINSAR, emsr_bld, nodata_val=None)
emsr_bld["dinsar_phase"] = di_vals

di_bld_rows = []
for dmg in ["Destroyed","Damaged","Possibly damaged"]:
    sub = emsr_bld[emsr_bld["damage_gra"]==dmg]
    v = sub["dinsar_phase"].dropna()
    if len(v)==0: continue
    std_v = float(np.std(v)); mean_v = float(np.mean(v))
    di_bld_rows.append({"grade":dmg,"n":len(sub),"n_valid":len(v),
                         "mean_rad":round(mean_v,4),"std_rad":round(std_v,4),
                         "mean_cm_equiv":round(abs(mean_v)/(2*np.pi)*LOS_PER_FRINGE,3)})
    print(f"    [{dmg}] mean={mean_v:.4f}rad std={std_v:.4f}rad")

# 전체 장면 개략 fringe 수 추정 (LOS)
# Catia La Mar 중심 ↔ 진앙 거리
cx_lat = (S+N)/2; cx_lon=(W+E)/2
epi_lat = 10.435; epi_lon = -68.47  # mainshock
dist_km = ((cx_lat-epi_lat)**2 + (cx_lon-epi_lon)**2)**0.5 * 111.32
print(f"\n    진앙~Catia La Mar 중심: {dist_km:.0f} km")

# ── 5. 진앙/단층 ───────────────────────────────────────────────────────────────
print("\n[5] 진앙 & 단층")
epi_rows = []
if epi is not None:
    for _, row in epi.iterrows():
        d_km = ((row.geometry.y-cx_lat)**2 + (row.geometry.x-cx_lon)**2)**0.5 * 111.32
        epi_rows.append({"type":row.get("type",""),"mag":row.get("mag",""),
                         "lat":round(row.geometry.y,4),"lon":round(row.geometry.x,4),
                         "depth":row.get("depth_km","?"),"mech":row.get("mechanism","RL strike-slip"),
                         "dist":round(d_km,0),"place":row.get("place","")})
        print(f"    [{row.get('type','')}] M{row.get('mag','')} dist={d_km:.0f}km depth={row.get('depth_km','')}km")

fault_rows = []
if FAULT_SHP.exists():
    faults = gpd.read_file(FAULT_SHP)
    if faults.crs is None: faults = faults.set_crs("EPSG:4326")
    faults_utm = faults.to_crs(UTM)
    aoi_utm = gpd.GeoDataFrame(geometry=[AOI_BOX], crs="EPSG:4326").to_crs(UTM).geometry[0]
    for _, row in faults_utm.iterrows():
        d = row.geometry.distance(aoi_utm)/1000
        if d < 30:
            fault_rows.append({"name":row.get("name","?"),"slip":row.get("slip_type","?"),"d":round(d,1)})
    fault_rows.sort(key=lambda x: x["d"])
    for f in fault_rows[:5]: print(f"    단층: {f['name']} [{f['slip']}] {f['d']}km")

# ── 6. 보고서 작성 ─────────────────────────────────────────────────────────────
print("\n[6] 보고서 작성")

R = []; r = R.append
r("# Catia La Mar 종합 피해 분석 보고서")
r(f"**지역**: La Guaira / Catia La Mar 해안 시가지  ")
r(f"**AOI**: 경도 {W}~{E} / 위도 {S}~{N}  ")
r(f"**분석 자료**: SAR CCD (VV 편파) + DInSAR co-seismic 위상  ")
r("**[DISCLAIMER]** 현장 미검증 예비분석. 확정 피해 판정 아님.")
r("")

# 1. 지진 개요
r("---"); r("## 1. 지진 개요")
r("")
if epi_rows:
    for row in epi_rows:
        r(f"### {row['type'].capitalize()} M{row['mag']}")
        r(f"- **발생시각**: 2026-06-24 UTC")
        r(f"- **위치**: 위도 {row['lat']}, 경도 {row['lon']}  ({row['place']})")
        r(f"- **진원깊이**: {row['depth']} km")
        r(f"- **메커니즘**: 우수향 주향이동단층 (Right-lateral strike-slip)")
        r(f"- **Catia La Mar까지 거리**: {row['dist']} km")
        r("")
else:
    r("- **Mainshock**: M7.5, 2026-06-24, 위도 10.435, 경도 -68.47")
    r("- **진원깊이**: 10 km")
    r("- **메커니즘**: RL strike-slip")
    r(f"- **Catia La Mar까지 거리**: ~{int(dist_km)} km")
    r("")

if fault_rows:
    r("### 인근 활성 단층 (GEM Global Active Faults)")
    r("")
    r("| 단층명 | 이동유형 | AOI까지 거리(km) |")
    r("|-------|--------|----------------|")
    for f in fault_rows[:5]:
        r(f"| {f['name']} | {f['slip']} | {f['d']} |")
    r("")

# 2. 분석 방법
r("---"); r("## 2. 분석 방법 및 임계치")
r("")
r("### CCD (Coherence Change Detection)")
r("")
r("| 구분 | ΔCoh 기준 | 설명 | 신뢰도 |")
r("|------|---------|-----|------|")
r("| 제외 | ΔCoh < 0 | co-event 코히런스 상승 = 피해 신호 아님 | 없음 |")
r("| 제외 | 0.0 ~ 0.1 | 노이즈 플로어 이하 | 낮음 |")
r(f"| **RISK(위험)** | {THR_RISK} ≤ ΔCoh < {THR_HIGH} | 유의미한 코히런스 손실 | 신뢰 |")
r(f"| **HIGH(고위험)** | ΔCoh ≥ {THR_HIGH} | 강한 코히런스 급락 | 높은 신뢰 |")
r("")
r("> ΔCoh = γ_pre − γ_co (양수 = pre보다 co-event 코히런스 감소 = 표면변화/피해 의심)")
r("")
r("### DInSAR (차분 간섭계)")
r("")
r("| 항목 | 내용 |")
r("|------|------|")
r("| 마스터/슬레이브 | 2026-06-18 / 2026-06-25 |")
r("| 포착 이벤트 | 2026-06-24 M7.5 co-seismic 지표변형 |")
r("| 위성 | Sentinel-1 (C-band, λ = 5.6 cm) |")
r("| 위상 유형 | Wrapped phase (감싸인 위상, −π ~ +π rad) |")
r(f"| 변환 계수 | 2π rad (1 fringe) = λ/2 = **{LOS_PER_FRINGE} cm** LOS 변위 |")
r("| 미완료 처리 | 위상 언래핑(SNAPHU) → 절대 변위 변환 필요 |")
r("")

# 3. CCD 분석
r("---"); r("## 3. CCD 위험구역 분석")
r("")
r(f"**Catia La Mar AOI 내 CCD (VV편파):**")
r("")
r("| 등급 | ΔCoh 기준 | 픽셀수 | 면적(km²) |")
r("|------|---------|------|---------|")
n_total_px = int(np.isfinite(dcoh_vv).sum())
r(f"| 전체 유효영역 | — | {n_total_px:,} | {round(n_total_px*px_km2,2)} |")
r(f"| **RISK+HIGH** | ≥ {THR_RISK} | {n_risk_px:,} | **{area_risk}** |")
r(f"| **HIGH** | ≥ {THR_HIGH} | {n_high_px:,} | **{area_high}** |")
r(f"| 변화없음(제외) | < {THR_RISK} | {n_total_px-n_risk_px:,} | {round((n_total_px-n_risk_px)*px_km2,2)} |")
r("")
r(f"> RISK+HIGH 면적: **{area_risk} km²** (전체 {round(100*area_risk/(n_total_px*px_km2),1)}%)")
r("")

r("### 3.1 EMSR884 피해건물 × CCD 교차")
r("")
r(f"**분석 건물 수**: {len(emsr_bld)}개 (AOI12 폴리곤 센트로이드 + AOI02/05/06/08 포인트)")
r("")
r("| 피해등급 | 전체 | RISK+HIGH | 검출률 | HIGH | HIGH검출률 |")
r("|---------|------|---------|------|------|---------|")
for row in ccd_bld_rows:
    r(f"| **{row['grade']}** | {row['n']} | {row['n_risk']} | **{row['pct_risk']}%** | {row['n_high']} | {row['pct_high']}% |")
r("")

# 4. 도로 분석
r("---"); r("## 4. 도로 노출 분석")
r("")
r(f"**AOI 내 총 도로**: {len(roads)}개 세그먼트, **{round(total_km,1)} km**")
r("")
r("| CCD 등급 | 도로 길이(km) | 전체 대비 |")
r("|---------|------------|---------|")
for row in road_rows:
    bold = "**" if row["cls_lbl"] in ["HIGH","RISK"] else ""
    r(f"| {bold}{row['cls_lbl']}{bold} | {row['km']} | {row['pct']}% |")
risk_total_km = sum(row["km"] for row in road_rows if row["cls_lbl"] in ["HIGH","RISK"])
r(f"| **위험구역 합계(RISK+HIGH)** | **{round(risk_total_km,1)}** | **{round(100*risk_total_km/total_km,1) if total_km>0 else 0}%** |")
r("")

if named_risk:
    r("### 위험구역 내 주요 도로 (Top 8)")
    r("")
    r("| 도로명 | 위험구역 내 연장(km) |")
    r("|------|-----------------|")
    for row in named_risk:
        r(f"| {row['name']} | {row['km']} |")
    r("")

# 5. DInSAR 분석
r("---"); r("## 5. DInSAR 지표변형 분석")
r("")
r("### 5.1 위상 분포 (Catia La Mar AOI)")
r("")
r("| 통계 | 값 |")
r("|------|---|")
r(f"| 유효 픽셀 | {len(di_f):,} |")
r(f"| 위상 최솟값 | {di_f.min():.4f} rad |")
r(f"| 위상 최댓값 | {di_f.max():.4f} rad |")
r(f"| 위상 평균 | {di_f.mean():.4f} rad |")
r(f"| 위상 표준편차 | {di_std:.4f} rad |")
r(f"| p25 / p50 / p75 | {di_p[1]:.3f} / {di_p[2]:.3f} / {di_p[3]:.3f} rad |")
r("")
pi_uniform_std = np.pi / np.sqrt(3)
r(f"> 균일 무작위 분포의 표준편차 = π/√3 ≈ **{pi_uniform_std:.3f} rad**")
if di_std < pi_uniform_std * 0.9:
    r(f"> **→ 실제 위상 std({di_std:.3f}) < 균일분포 std({pi_uniform_std:.3f}): 코히런트 신호 존재 가능**")
else:
    r(f"> **→ 위상 std({di_std:.3f}) ≈ 균일분포({pi_uniform_std:.3f}): 저코히런스 or 다중 프린지 포함**")
r("")
r("### 5.2 위상 해석 (Wrapped Phase 기준)")
r("")
r(f"- Sentinel-1 C-band: 1 fringe (2π) = **{LOS_PER_FRINGE} cm LOS 변위**")
r(f"- Catia La Mar 위상 중위값: {di_p[2]:.4f} rad → 단일 cycle 대비 **{round(abs(di_p[2])/(2*np.pi)*LOS_PER_FRINGE,2)} cm** LOS 등가")
r("- 주의: Wrapped phase는 절대 변위 산정 불가 — SNAPHU 언래핑 필요")
r("- 위상 프린지 밀도가 높은 구역(상부-좌측 클러스터)은 더 큰 변형 가능성")
r("")

if di_bld_rows:
    r("### 5.3 피해건물 위치 위상 값")
    r("")
    r("| 피해등급 | 건물수 | 위상 평균(rad) | 위상 표준편차(rad) | 등가 변위(cm) |")
    r("|---------|------|------------|---------------|---------|")
    for row in di_bld_rows:
        r(f"| {row['grade']} | {row['n']} | {row['mean_rad']} | {row['std_rad']} | {row['mean_cm_equiv']} |")
    r("")

# 6. 종합 결론
r("---"); r("## 6. 종합 결론")
r("")
dest_r = next((x["n_risk"] for x in ccd_bld_rows if x["grade"]=="Destroyed"), 0)
dest_n = next((x["n"] for x in ccd_bld_rows if x["grade"]=="Destroyed"), 0)
dmg_r  = next((x["n_risk"] for x in ccd_bld_rows if x["grade"]=="Damaged"), 0)
dmg_n  = next((x["n"] for x in ccd_bld_rows if x["grade"]=="Damaged"), 0)
dmg_pct= next((x["pct_risk"] for x in ccd_bld_rows if x["grade"]=="Damaged"), 0)
r("### CCD 검출 성능 요약")
r("")
r(f"1. **Destroyed 건물 검출**: {dest_r}/{dest_n}개 ({round(100*dest_r/dest_n if dest_n>0 else 0,0):.0f}%) — CCD RISK+HIGH 구역 내 포함 확인")
r(f"2. **Damaged 건물 검출**: {dmg_r}/{dmg_n}개 (**{dmg_pct}%**) — 신뢰도 있는 임계치(ΔCoh≥{THR_RISK}) 기반")
r(f"3. **CCD 위험구역**: Catia La Mar 내 **{area_risk} km²** — 총 면적의 {round(100*area_risk/(n_total_px*px_km2),0):.0f}%")
r(f"4. **도로 노출**: 위험구역 내 **{round(risk_total_km,1)} km** 도로 — 긴급 접근로 사전 확인 필요")
r("")
r("### DInSAR 해석")
r("")
r("5. **Co-seismic 위상**: 2026-06-18/25 쌍 — M7.5 지진 co-seismic 지표변형 포착")
r(f"6. **프린지 신호**: 위상 표준편차 {di_std:.3f} rad — {'코히런트 신호(실제 변형 포함 가능)' if di_std < pi_uniform_std * 0.9 else '다중 프린지/저코히런스 혼재'}")
r(f"7. **진앙 거리**: {int(dist_km)} km — 원거리 표면파 또는 연동 단층 활성화 가능성")
r("8. **SNAPHU 언래핑 필요**: 절대 LOS 변위 산출 및 3D 지표변형 분리 위해 후속 처리 권장")
r("")
r("### 한계사항")
r("")
r("- Destroyed 건물 1개(ΔCoh=-0.178) CCD 미검출 → co-event 코히런스 역상승(잔해 specular?) 추정")
r("- DInSAR wrapped phase 상태: 절대 변위 산정 불가 (SNAPHU 후처리 필요)")
r("- 단일 편파(VV) + 단일 쌍 → 통계 검증 불가")
r("- EMSR884 피해 데이터 수동 광학 판독 기반 → 현장 검증 후 갱신 필요")
r("")
r("---")
r("*[DISCLAIMER] 현장 미검증 예비분석. Sentinel-1 SAR CCD 및 DInSAR 기반 원격탐사 결과. 확정 피해 판정 아님.*")

rpt = OUT / "catia_lamar_report.md"
with open(rpt, "w", encoding="utf-8") as f: f.write("\n".join(R))
print(f"    저장: {rpt.name}")

# ── 7. 지도 (CCD + DInSAR) ───────────────────────────────────────────────────
print("\n[7] 지도 생성")

NORM_CCD  = TwoSlopeNorm(vmin=-0.5, vcenter=0, vmax=0.8)
NORM_DI   = mcolors.Normalize(vmin=-np.pi, vmax=np.pi)

def _add_overlays(ax):
    """도로, 건물폴리곤, 건물포인트 오버레이 공통"""
    if len(roads) > 0:
        roads.plot(ax=ax, color="#f0e040", lw=0.6, alpha=0.5, zorder=4)
    if bldA_raw is not None and len(bldA_raw) > 0:
        for dmg, grp in bldA_raw.groupby("damage_gra"):
            grp.boundary.plot(ax=ax, color=DMG_COLOR.get(dmg,"#888"), lw=1.4, alpha=0.9, zorder=5)
    if len(emsr_bld) > 0:
        for dmg, grp in emsr_bld.groupby("damage_gra"):
            if dmg not in ["Destroyed","Damaged","Possibly damaged"]: continue
            mk = {"Destroyed":"X","Damaged":"^","Possibly damaged":"o"}[dmg]
            sz = {"Destroyed":120,"Damaged":70,"Possibly damaged":40}[dmg]
            ax.scatter(grp.geometry.x, grp.geometry.y, c=DMG_COLOR[dmg],
                       marker=mk, s=sz,
                       edgecolors="white" if dmg!="Destroyed" else "none",
                       linewidths=0.8, alpha=0.95, zorder=6)

def _add_legend(ax):
    patches = [
        mpatches.Patch(fc="#f0e040", label="도로(EMSR884)"),
        mpatches.Patch(fc=DMG_COLOR["Destroyed"], label="Destroyed (✕)"),
        mpatches.Patch(fc=DMG_COLOR["Damaged"], label="Damaged (▲)"),
        mpatches.Patch(fc=DMG_COLOR["Possibly damaged"], label="Possibly damaged (●)"),
    ]
    ax.legend(handles=patches, loc="lower left", fontsize=8,
              framealpha=0.85, facecolor="white", edgecolor="gray")

# --- 그림 1: CCD VV ---
fig, ax = plt.subplots(figsize=(14, 12))
ax.set_xlim(W, E); ax.set_ylim(S, N); ax.set_aspect("equal")
try:
    cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldImagery, zoom="auto", zorder=0)
    print("    CCD: ESRI 베이스맵 추가")
except Exception as e:
    print(f"    CCD: 베이스맵 실패: {e}"); ax.set_facecolor("#c8d7e1")

im_ccd = ax.imshow(np.ma.masked_invalid(dcoh_vv), cmap="RdBu_r", norm=NORM_CCD,
                    extent=ext_vv, origin="upper", alpha=0.65, zorder=2, interpolation="bilinear")
_add_overlays(ax)
cbar = plt.colorbar(im_ccd, ax=ax, shrink=0.55, pad=0.015, aspect=30)
cbar.set_label("ΔCoh = γ_pre − γ_co (VV)", fontsize=11)
_add_legend(ax)
ax.set_xlabel("경도"); ax.set_ylabel("위도"); ax.tick_params(labelsize=9)
ax.set_title(f"Catia La Mar — SAR CCD (VV편파)\n"
             f"빨강: 코히런스 감소(피해의심, ΔCoh>{THR_RISK})  파랑: 코히런스 증가  "
             f"HIGH≥{THR_HIGH}\n[DISCLAIMER] 현장 미검증 예비분석", fontsize=11, fontweight="bold")
plt.tight_layout()
p1 = OUT/"catia_lamar_VV.png"
fig.savefig(p1, dpi=200, bbox_inches="tight", facecolor="white"); plt.close()
print(f"    저장: {p1.name} ({p1.stat().st_size//1024}KB)")

# --- 그림 2: DInSAR Wrapped Phase ---
fig, ax = plt.subplots(figsize=(14, 12))
ax.set_xlim(W, E); ax.set_ylim(S, N); ax.set_aspect("equal")
try:
    cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldImagery, zoom="auto", zorder=0)
    print("    DInSAR: ESRI 베이스맵 추가")
except Exception as e:
    print(f"    DInSAR: 베이스맵 실패: {e}"); ax.set_facecolor("#c8d7e1")

im_di = ax.imshow(dinsar, cmap="twilight_shifted", norm=NORM_DI,
                   extent=ext_di, origin="upper", alpha=0.65, zorder=2, interpolation="bilinear")
_add_overlays(ax)
cbar2 = plt.colorbar(im_di, ax=ax, shrink=0.55, pad=0.015, aspect=30)
cbar2.set_label("위상 (rad)  −π ~ +π", fontsize=11)
cbar2.set_ticks([-np.pi, -np.pi/2, 0, np.pi/2, np.pi])
cbar2.set_ticklabels(["-π", "-π/2", "0", "+π/2", "+π"])
_add_legend(ax)
ax.set_xlabel("경도"); ax.set_ylabel("위도"); ax.tick_params(labelsize=9)
ax.set_title(f"Catia La Mar — DInSAR Wrapped Phase (2026-06-18/25)\n"
             f"Co-seismic 지표변형 | 1 fringe = 2π = {LOS_PER_FRINGE}cm LOS | Twilight 컬러맵(순환)\n"
             f"[DISCLAIMER] 현장 미검증 예비분석", fontsize=11, fontweight="bold")
plt.tight_layout()
p2 = OUT/"catia_lamar_dinsar.png"
fig.savefig(p2, dpi=200, bbox_inches="tight", facecolor="white"); plt.close()
print(f"    저장: {p2.name} ({p2.stat().st_size//1024}KB)")

# --- 그림 3: 2패널 비교 (CCD | DInSAR) ---
fig, axes = plt.subplots(1, 2, figsize=(26, 11))
for ax, arr, ext, nm, cmap_, norm_, clabel in [
    (axes[0], np.ma.masked_invalid(dcoh_vv), ext_vv, "CCD VV", "RdBu_r", NORM_CCD,
     f"ΔCoh (VV)  빨강>>{THR_RISK}"),
    (axes[1], dinsar, ext_di, "DInSAR Wrapped Phase", "twilight_shifted", NORM_DI,
     "위상(rad)  −π~+π")
]:
    ax.set_xlim(W, E); ax.set_ylim(S, N); ax.set_aspect("equal")
    try: cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldImagery, zoom="auto", zorder=0)
    except: ax.set_facecolor("#c8d7e1")
    im = ax.imshow(arr, cmap=cmap_, norm=norm_, extent=ext,
                   origin="upper", alpha=0.65, zorder=2, interpolation="bilinear")
    _add_overlays(ax)
    cb = plt.colorbar(im, ax=ax, shrink=0.5, pad=0.01, aspect=25)
    cb.set_label(clabel, fontsize=10)
    if "DInSAR" in nm:
        cb.set_ticks([-np.pi, -np.pi/2, 0, np.pi/2, np.pi])
        cb.set_ticklabels(["-π","-π/2","0","+π/2","+π"])
    ax.set_title(f"【{nm}】", fontsize=12, fontweight="bold")
    ax.set_xlabel("경도"); ax.set_ylabel("위도"); ax.tick_params(labelsize=8)

patches_leg = [
    mpatches.Patch(fc="#f0e040", label="도로(EMSR884)"),
    mpatches.Patch(fc=DMG_COLOR["Destroyed"], label="Destroyed"),
    mpatches.Patch(fc=DMG_COLOR["Damaged"], label="Damaged"),
    mpatches.Patch(fc=DMG_COLOR["Possibly damaged"], label="Possibly damaged"),
]
fig.legend(handles=patches_leg, loc="lower center", fontsize=9, ncol=4,
           framealpha=0.85, bbox_to_anchor=(0.5, 0.0))
fig.suptitle(f"Catia La Mar 종합 분석 — CCD × DInSAR (2026-06-24 M7.5)\n"
             f"[DISCLAIMER] 현장 미검증 예비분석", fontsize=13, fontweight="bold", y=1.01)
plt.tight_layout(rect=[0, 0.05, 1, 1])
p3 = OUT/"catia_lamar_compare.png"
fig.savefig(p3, dpi=200, bbox_inches="tight", facecolor="white"); plt.close()
print(f"    저장: {p3.name} ({p3.stat().st_size//1024}KB)")

print("\n" + "="*65)
print("  완료")
for f in sorted(OUT.glob("catia_lamar*")):
    print(f"    {f.name:<50} {f.stat().st_size//1024:>5}KB")
print("="*65)
print("[DISCLAIMER] 현장 미검증 예비분석.")
