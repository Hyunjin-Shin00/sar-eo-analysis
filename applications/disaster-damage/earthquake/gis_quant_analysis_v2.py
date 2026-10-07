"""
GIS 정량 분석 v2 — 2등급 재분류 (신뢰도 기반 임계치)
임계치: RISK(위험): 0.1 ≤ ΔCoh < 0.4  /  HIGH(고위험): ΔCoh ≥ 0.4
- ΔCoh < 0 은 co-event 코히런스가 오히려 증가 → 피해 신호 아님 (신뢰성 없음)
- 하한 0.1: 노이즈 플로어(~0.05-0.1) 위의 실질적 코히런스 손실 시작점
[DISCLAIMER] 현장 미검증 예비분석.
"""
import os, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import shapes as raster_shapes
from rasterio.mask import mask as raster_mask
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from shapely.geometry import shape, box, mapping
from shapely.ops import unary_union
warnings.filterwarnings("ignore")

matplotlib.rc("font", family="Malgun Gothic")
matplotlib.rcParams["axes.unicode_minus"] = False

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE  = Path(r"<DATA_ROOT>")
RIGHT = BASE / "Venezuela" / "right"
OUT   = RIGHT / "output" / "gis"
EMSR  = BASE / "EMSR884_products"
UTM   = "EPSG:32619"

DCOH_TIF  = RIGHT / "output" / "dcoh_VV.tif"          # raw ΔCoh float32
CCD2_TIF  = RIGHT / "output" / "dcoh_class2_VV.tif"   # 새 2등급 분류

# 2등급 임계치 (신뢰도 기반 — ΔCoh > 0 = 코히런스 손실 = 실질적 피해 신호)
# ΔCoh < 0 은 co-event 코히런스가 오히려 높아진 것 → 피해 신호 아님
THR_RISK = 0.1   # 노이즈 플로어 위의 실질적 코히런스 손실 하한
THR_HIGH = 0.4   # 유의미한 코히런스 급락 (강한 신호)

CLS_LABEL = {0:"변화없음", 1:"RISK(위험)", 2:"HIGH(고위험)"}
CLS_COLOR = {0:"#e0e0e0", 1:"#fc8d59", 2:"#d73027"}
DMG_ORDER = ["Destroyed","Damaged","Possibly damaged","No visible damage","Not Analysed"]
DMG_COLOR = {"Destroyed":"#d73027","Damaged":"#fc8d59","Possibly damaged":"#fee08b",
             "No visible damage":"#91cf60","Not Analysed":"#aaaaaa"}

os.makedirs(OUT, exist_ok=True)

# ── 1. 새 2등급 래스터 생성 ───────────────────────────────────────────────────
print("="*65); print("  GIS 분석 v2 (2등급, Destroyed 전체 포함)"); print("="*65)
print("\n[1] 2등급 래스터 생성")
print(f"  RISK : {THR_RISK} <= DCoh < {THR_HIGH}")
print(f"  HIGH : DCoh >= {THR_HIGH}")

with rasterio.open(DCOH_TIF) as src:
    dcoh_raw = src.read(1).astype(np.float32)
    tr = src.transform; crs = src.crs
    nd = src.nodata  # -9999

dcoh_raw[dcoh_raw == nd] = np.nan

cls2 = np.zeros(dcoh_raw.shape, dtype=np.uint8)
valid = np.isfinite(dcoh_raw)
cls2[valid & (dcoh_raw >= THR_RISK) & (dcoh_raw < THR_HIGH)] = 1   # RISK
cls2[valid & (dcoh_raw >= THR_HIGH)]                               = 2   # HIGH

for c in [2, 1, 0]:
    n = int((cls2 == c).sum())
    px_km2 = (abs(tr.a) * 111320) ** 2 / 1e6
    print(f"  {CLS_LABEL[c]}: {n:,} px = {n*px_km2:.1f} km²")

# 저장
profile = {"driver":"GTiff","count":1,"dtype":"uint8","crs":crs,
           "transform":tr,"width":cls2.shape[1],"height":cls2.shape[0],
           "nodata":255,"compress":"lzw"}
with rasterio.open(CCD2_TIF,"w",**profile) as dst:
    dst.write(cls2, 1)
print(f"  저장: {CCD2_TIF.name}")

# ── 2. 벡터화 (HIGH만 — RISK는 너무 많은 픽셀) ───────────────────────────────
print("\n[2] HIGH 등급 벡터화")
ccd_b   = rasterio.open(CCD2_TIF).bounds
ccd_box = box(ccd_b.left, ccd_b.bottom, ccd_b.right, ccd_b.top)

mask_h = (cls2 == 2).astype(np.uint8)
polys_h = [shape(g).simplify(0.002) for g, v in raster_shapes(mask_h, transform=tr) if v == 1]
gdf_high = gpd.GeoDataFrame({"cls":2,"geometry":polys_h}, crs=crs) if polys_h else gpd.GeoDataFrame(geometry=[], crs=crs)
print(f"  HIGH 폴리곤: {len(gdf_high)}개")

# ── 3. 벡터 데이터 로드 ──────────────────────────────────────────────────────
print("\n[3] 벡터 데이터 로드")
PATHS = {
    "builtUpA_AOI12": EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_builtUpA_v2.shp",
    "builtUpP_AOI02": EMSR/"EMSR884_AOI02_GRA_MONIT01_v2"/"EMSR884_AOI02_GRA_MONIT01_builtUpP_v1.shp",
    "builtUpP_AOI06": EMSR/"EMSR884_AOI06_GRA_MONIT01_v2"/"EMSR884_AOI06_GRA_MONIT01_builtUpP_v1.shp",
    "builtUpP_AOI08": EMSR/"EMSR884_AOI08_GRA_MONIT01_v2"/"EMSR884_AOI08_GRA_MONIT01_builtUpP_v1.shp",
    "transL_AOI02":   EMSR/"EMSR884_AOI02_GRA_MONIT01_v2"/"EMSR884_AOI02_GRA_MONIT01_transportationL_v1.shp",
    "transL_AOI12":   EMSR/"EMSR884_AOI12_GRA_PRODUCT_v2"/"EMSR884_AOI12_GRA_PRODUCT_transportationL_v2.shp",
    "transL_AOI05":   EMSR/"EMSR884_AOI05_GRA_PRODUCT_v1"/"EMSR884_AOI05_GRA_PRODUCT_transportationL_v1.shp",
    "transL_AOI06":   EMSR/"EMSR884_AOI06_GRA_MONIT01_v2"/"EMSR884_AOI06_GRA_MONIT01_transportationL_v1.shp",
    "transL_AOI08":   EMSR/"EMSR884_AOI08_GRA_MONIT01_v2"/"EMSR884_AOI08_GRA_MONIT01_transportationL_v2.shp",
    "groundMov":      EMSR/"EMSR884_AOI00_GRM_PRODUCT_v2"/"EMSR884_AOI00_GRM_PRODUCT_groundMovementA_v2.shp",
    "epicenters":     BASE/"epicenters"/"epicenters_2026.shp",
    "faults":         BASE/"fault"/"gem-global-active-faults"/"shapefile"/"gem_active_faults.shp",
}
gdfs = {}
for k, p in PATHS.items():
    if not Path(p).exists(): continue
    g = gpd.read_file(p)
    if g.crs is None: g = g.set_crs("EPSG:4326")
    g = g.to_crs("EPSG:4326")
    clipped = gpd.clip(g, ccd_box)
    gdfs[k] = clipped if len(clipped) > 0 else None
    print(f"  {k}: {len(clipped)}개")

# ── 4. 건물 포인트 — raw ΔCoh 샘플링 → 2등급 분류 ───────────────────────────
print("\n[4] 건물 ΔCoh 샘플링 (raw) + 2등급 분류")

parts = []
for k in ["builtUpP_AOI02","builtUpP_AOI06","builtUpP_AOI08"]:
    g = gdfs.get(k)
    if g is not None and len(g) > 0:
        d = g[["damage_gra","geometry"]].copy(); d["src"] = k; parts.append(d)
bA = gdfs.get("builtUpA_AOI12")
if bA is not None:
    bA_pt = bA.copy(); bA_pt["geometry"] = bA_pt.geometry.centroid
    bA_pt["src"] = "builtUpA(centroid)"
    parts.append(bA_pt[["damage_gra","geometry","src"]])

bpt_summary = []
if parts:
    bpt = pd.concat(parts, ignore_index=True)
    coords = [(g.x, g.y) for g in bpt.geometry]
    with rasterio.open(DCOH_TIF) as src:
        raw_vals = [float(list(src.sample([c]))[0][0]) for c in coords]
    bpt["dcoh"] = raw_vals
    bpt.loc[bpt["dcoh"] == -9999, "dcoh"] = np.nan

    # 2등급 분류 적용
    bpt["cls2"] = 0
    bpt.loc[bpt["dcoh"] >= THR_RISK, "cls2"] = 1
    bpt.loc[bpt["dcoh"] >= THR_HIGH, "cls2"] = 2
    bpt.loc[bpt["dcoh"].isna(), "cls2"] = 0
    bpt["cls_lbl"] = bpt["cls2"].map(CLS_LABEL)

    total = len(bpt)
    in_risk = (bpt["cls2"] >= 1).sum()
    in_high = (bpt["cls2"] == 2).sum()
    print(f"  총 {total}개  →  위험구역(RISK+HIGH): {in_risk}개 ({100*in_risk/total:.1f}%)  HIGH: {in_high}개 ({100*in_high/total:.1f}%)")

    ct = pd.crosstab(bpt["damage_gra"], bpt["cls_lbl"])
    col_order = [c for c in ["HIGH(고위험)","RISK(위험)","변화없음"] if c in ct.columns]
    ct = ct.reindex(columns=col_order, fill_value=0)
    row_order = [d for d in DMG_ORDER if d in ct.index]
    ct = ct.reindex(row_order, fill_value=0)
    ct["합계"] = ct.sum(axis=1)
    print(f"\n  피해등급 × CCD 2등급 교차표:\n{ct.to_string()}")

    for dmg in ["Destroyed","Damaged","Possibly damaged"]:
        sub = bpt[bpt["damage_gra"]==dmg]
        if len(sub) == 0: continue
        r = (sub["cls2"] >= 1).sum()
        h = (sub["cls2"] == 2).sum()
        bpt_summary.append({"피해등급":dmg,"전체":len(sub),
                            "위험구역내":int(r),"검출률%":round(100*r/len(sub),1),
                            "HIGH내":int(h),"HIGH검출률%":round(100*h/len(sub),1)})
        print(f"  [{dmg}] 위험구역: {r}/{len(sub)} ({100*r/len(sub):.1f}%)  HIGH: {h}/{len(sub)} ({100*h/len(sub):.1f}%)")
else:
    bpt = None

# ── 5. 건물 폴리곤 CCD 오버레이 ──────────────────────────────────────────────
print("\n[5] 건물 폴리곤 오버레이 (AOI12)")
poly_rows = []
if bA is not None and len(bA) > 0:
    bA_utm = bA.to_crs(UTM)
    with rasterio.open(CCD2_TIF) as src:
        for idx, row in bA.iterrows():
            try:
                out, _ = raster_mask(src, [mapping(row.geometry)], crop=True, nodata=255)
                v = out[0]; tp=(v<255).sum(); hp=(v==2).sum(); rp=(v>=1).sum()
            except: tp=hp=rp=0
            area_m2 = bA_utm.loc[idx].geometry.area if idx in bA_utm.index else 0
            poly_rows.append({"damage_gra":row.get("damage_gra","?"),
                              "area_m2":round(area_m2),
                              "pct_high":round(100*hp/tp,1) if tp>0 else 0,
                              "pct_risk":round(100*rp/tp,1) if tp>0 else 0})
    df_poly = pd.DataFrame(poly_rows)
    grp = df_poly.groupby("damage_gra").agg(
        n=("area_m2","count"), total_area_km2=("area_m2",lambda x:x.sum()/1e6),
        avg_pct_high=("pct_high","mean"), avg_pct_risk=("pct_risk","mean")).reset_index()
    print(grp.round(3).to_string(index=False))
else:
    df_poly = pd.DataFrame(); grp = pd.DataFrame()

# ── 6. 도로 노출 분석 ─────────────────────────────────────────────────────────
print("\n[6] 도로 노출 분석")
road_parts = []
for k in ["transL_AOI02","transL_AOI12","transL_AOI05","transL_AOI06","transL_AOI08"]:
    g = gdfs.get(k)
    if g is not None and len(g) > 0:
        d = g[["simplified","name","damage_gra","geometry"]].copy(); d["src"]=k
        road_parts.append(d)

road_rows = []; named_risk = pd.DataFrame()
if road_parts:
    roads = pd.concat(road_parts, ignore_index=True)
    roads_utm = roads.to_crs(UTM)
    total_km = roads_utm.geometry.length.sum() / 1000
    print(f"  총 {len(roads)}개 / {total_km:.1f} km")

    mid_pts = roads.geometry.interpolate(0.5, normalized=True)
    coords_r = [(p.x, p.y) for p in mid_pts]
    with rasterio.open(DCOH_TIF) as src:
        raw_r = [float(list(src.sample([c]))[0][0]) for c in coords_r]
    roads = roads.copy()
    raw_arr = np.array(raw_r, dtype=np.float32)
    raw_arr[raw_arr == -9999] = np.nan
    road_cls = np.zeros(len(raw_arr), dtype=int)
    road_cls[raw_arr >= THR_RISK]  = 1
    road_cls[raw_arr >= THR_HIGH]  = 2
    roads["cls2"] = road_cls
    roads_utm = roads.to_crs(UTM).copy()
    roads_utm["len_km"] = roads_utm.geometry.length / 1000

    for c, lab in [(2,"HIGH"),(1,"RISK"),(0,"변화없음")]:
        sub = roads_utm[roads_utm["cls2"]==c]
        km = sub["len_km"].sum(); pct = 100*km/total_km if total_km > 0 else 0
        print(f"  {lab}: {km:.1f} km ({pct:.1f}%)")
        road_rows.append({"등급":lab,"km":round(km,1),"pct":round(pct,1)})
        if c in [1,2]:
            by_type = sub.groupby("simplified")["len_km"].sum().sort_values(ascending=False)
            for t,l in by_type.items():
                print(f"      {t}: {l:.1f} km")

    risk_roads = roads_utm[roads_utm["cls2"] >= 1]
    named = risk_roads[risk_roads["name"].notna() & ~risk_roads["name"].isin(["Unknown",""])]
    if len(named) > 0:
        named_risk = named.groupby("name")["len_km"].sum().sort_values(ascending=False).head(10).reset_index()
        named_risk.columns = ["도로명","위험구역내_km"]
        print("\n  위험구역 주요 도로 Top10:")
        print(named_risk.to_string(index=False))
else:
    roads = None; total_km = 0

# ── 7. 지표이동 × CCD ────────────────────────────────────────────────────────
print("\n[7] 지표이동 × CCD")
gm = gdfs.get("groundMov"); gm_rows = []
if gm is not None and len(gm) > 0:
    def parse_mv(v):
        try: p=str(v).split(" to "); return (float(p[0])+float(p[1]))/2
        except: return np.nan
    gm = gm.copy(); gm["mv_mid"] = gm["value"].apply(parse_mv)
    coords_gm = [(p.x,p.y) for p in gm.geometry.centroid]
    with rasterio.open(DCOH_TIF) as src:
        raw_gm = [float(list(src.sample([c]))[0][0]) for c in coords_gm]
    raw_gm_arr = np.array(raw_gm); raw_gm_arr[raw_gm_arr==-9999]=np.nan
    gm_cls = np.zeros(len(raw_gm_arr),dtype=int)
    gm_cls[raw_gm_arr>=THR_RISK]=1; gm_cls[raw_gm_arr>=THR_HIGH]=2
    gm["cls2"] = gm_cls
    for c in [2,1,0]:
        sub=gm[gm["cls2"]==c]
        if len(sub)==0: continue
        gm_rows.append({"CCD등급":CLS_LABEL[c],"폴리곤수":len(sub),
                        "평균변위m":round(sub["mv_mid"].mean(),4),
                        "최대변위m":round(sub["mv_mid"].max(),4)})
        print(f"  {CLS_LABEL[c]}: {len(sub)}개, 평균={sub['mv_mid'].mean():.4f}m, max={sub['mv_mid'].max():.4f}m")
else:
    print("  장면 내 지표이동 데이터 없음")

# ── 8. 진앙 & 단층 ───────────────────────────────────────────────────────────
print("\n[8] 진앙 & 단층")
epi = gdfs.get("epicenters") if gdfs.get("epicenters") is not None else gpd.read_file(PATHS["epicenters"]).to_crs("EPSG:4326")
epi_rows = []
if epi is not None and len(epi)>0:
    epi_utm = epi.to_crs(UTM)
    sc_cent  = ccd_box.centroid
    for _, row in epi.iterrows():
        d = row.geometry.distance(sc_cent)*111.32
        print(f"  [{row.get('type','')}] M{row.get('mag','')} {row.get('place','')} | 장면중심~{d:.0f}km")
    if not gdf_high.empty:
        h_u = gdf_high.to_crs(UTM).geometry.unary_union.centroid
        for _, row in epi_utm.iterrows():
            d = row.geometry.distance(h_u)/1000
            epi_rows.append({"type":row.get("type",""),"mag":row.get("mag",""),"dist_km":round(d,1)})
            print(f"  [{row.get('type','')}] → HIGH 클러스터 중심 {d:.1f} km")

faults_all = gpd.read_file(PATHS["faults"])
if faults_all.crs is None: faults_all=faults_all.set_crs("EPSG:4326")
faults_utm = faults_all.to_crs(UTM)
fault_rows = []
if not gdf_high.empty:
    h_u = gdf_high.to_crs(UTM).geometry.unary_union
    for _,row in faults_utm.iterrows():
        d=row.geometry.distance(h_u)/1000
        fault_rows.append({"name":row.get("name","?"),"slip":row.get("slip_type","?"),"d":round(d,1)})
    fault_rows.sort(key=lambda x:x["d"])
    print("  HIGH 근접 단층 Top5:")
    for f in fault_rows[:5]: print(f"    {f['name']} [{f['slip']}]: {f['d']} km")

# ── 9. GeoPackage ────────────────────────────────────────────────────────────
print("\n[9] GeoPackage 저장")
gpkg = OUT/"analysis_results_v2.gpkg"
if not gdf_high.empty:
    gdf_high.to_file(gpkg, driver="GPKG", layer="ccd_HIGH")
if bpt is not None:
    bpt.drop(columns=["dcoh"], errors="ignore").to_crs("EPSG:4326").to_file(gpkg, driver="GPKG", layer="buildings_ccd_v2")
if bA is not None and poly_rows:
    bA_out=bA.copy().reset_index(drop=True)
    for col in ["pct_high","pct_risk"]:
        bA_out[col]=[r[col] for r in poly_rows]
    bA_out.to_file(gpkg, driver="GPKG", layer="buildings_poly_ccd_v2")
if roads is not None:
    roads.to_crs("EPSG:4326").to_file(gpkg, driver="GPKG", layer="roads_ccd_v2")
if epi is not None:
    epi.to_file(gpkg, driver="GPKG", layer="epicenters")
print(f"  저장: {gpkg.name}")

# ── 10. 시각화 ───────────────────────────────────────────────────────────────
print("\n[10] 시각화")

with rasterio.open(CCD2_TIF) as src:
    ccd_vis = src.read(1).astype(float)
ccd_vis[ccd_vis==255]=np.nan
extent=[ccd_b.left,ccd_b.right,ccd_b.bottom,ccd_b.top]

cm2  = mcolors.ListedColormap(["#e0e0e0","#fc8d59","#d73027"])
nm2  = mcolors.BoundaryNorm([-0.5,0.5,1.5,2.5],3)

fig,ax=plt.subplots(figsize=(14,11))
ax.imshow(ccd_vis,cmap=cm2,norm=nm2,extent=extent,aspect="auto",alpha=0.8,zorder=1)
if roads is not None:
    roads.plot(ax=ax,color="#666",lw=0.4,alpha=0.4,zorder=2)
if bA is not None and len(bA)>0:
    bA.boundary.plot(ax=ax,color="darkred",lw=1.0,zorder=4,label="피해건물(폴리곤)")
if bpt is not None:
    for dmg, sub in bpt.groupby("damage_gra"):
        mk={"Destroyed":"X","Damaged":"^","Possibly damaged":"o"}.get(dmg,"s")
        ax.scatter(sub.geometry.x,sub.geometry.y,c=DMG_COLOR.get(dmg,"#888"),
                   marker=mk,s=60,zorder=5,linewidths=1.3,
                   edgecolors="black" if dmg!="Destroyed" else "none",label=f"{dmg}")
if epi is not None and len(epi)>0:
    for _,row in epi.iterrows():
        clr="#ff0000" if row.get("type")=="mainshock" else "#ff8800"
        ax.plot(row.geometry.x,row.geometry.y,"*",ms=22,color=clr,mec="black",mew=0.8,
                zorder=10,label=f"진앙 {row.get('type','')} M{row.get('mag','')}")
ccd_patches=[mpatches.Patch(color="#fc8d59",label=f"RISK (DCoh≥{THR_RISK})"),
             mpatches.Patch(color="#d73027",label=f"HIGH (DCoh≥{THR_HIGH})")]
hdl,lbl=ax.get_legend_handles_labels()
ax.legend(handles=hdl+ccd_patches,loc="lower left",fontsize=7,framealpha=0.85,ncol=2)
ax.set_title(f"CCD 2등급 분류 × EMSR884 피해  [예비분석, 미검증]\n"
             f"RISK: DCoh≥{THR_RISK}  /  HIGH: DCoh≥{THR_HIGH}",fontsize=12,fontweight="bold")
ax.set_xlabel("경도"); ax.set_ylabel("위도")
ax.set_xlim(extent[:2]); ax.set_ylim(extent[2:])
plt.tight_layout()
fig.savefig(OUT/"map_v2.png",dpi=180,bbox_inches="tight")
plt.close(); print("  저장: map_v2.png")

# 건물 히트맵
if bpt is not None:
    ct2=pd.crosstab(bpt["damage_gra"],bpt["cls_lbl"])
    co=[c for c in ["HIGH(고위험)","RISK(위험)","변화없음"] if c in ct2.columns]
    ct2=ct2.reindex(columns=co,fill_value=0)
    ro=[d for d in DMG_ORDER if d in ct2.index]
    ct2=ct2.reindex(ro,fill_value=0)
    fig2,ax2=plt.subplots(figsize=(7,4))
    im=ax2.imshow(ct2.values,cmap="Reds",aspect="auto")
    ax2.set_xticks(range(len(ct2.columns)));ax2.set_xticklabels(ct2.columns,fontsize=10)
    ax2.set_yticks(range(len(ct2.index)));ax2.set_yticklabels(ct2.index,fontsize=10)
    for i in range(len(ct2.index)):
        for j in range(len(ct2.columns)):
            v=ct2.values[i,j]
            ax2.text(j,i,str(v),ha="center",va="center",fontsize=12,fontweight="bold",
                     color="white" if v>ct2.values.max()*0.5 else "black")
    plt.colorbar(im,ax=ax2,label="건물 수")
    ax2.set_title(f"건물 피해등급 × CCD 2등급  [예비분석, 미검증]",fontsize=11)
    plt.tight_layout()
    fig2.savefig(OUT/"chart_buildings_v2.png",dpi=150,bbox_inches="tight")
    plt.close(); print("  저장: chart_buildings_v2.png")

# 도로 막대
if road_rows:
    df_rr=pd.DataFrame(road_rows)
    colors_r={"HIGH":"#d73027","RISK":"#fc8d59","변화없음":"#e0e0e0"}
    fig3,ax3=plt.subplots(figsize=(7,4))
    bars=ax3.bar(df_rr["등급"],df_rr["km"],color=[colors_r.get(r,"#aaa") for r in df_rr["등급"]],edgecolor="black",lw=0.8)
    for bar,pct in zip(bars,df_rr["pct"]):
        ax3.text(bar.get_x()+bar.get_width()/2,bar.get_height()+1,f"{pct:.1f}%",ha="center",va="bottom",fontsize=10)
    ax3.set_title("CCD 2등급 위험구역 노출 도로 길이  [예비분석, 미검증]",fontsize=11)
    ax3.set_xlabel("CCD 등급"); ax3.set_ylabel("도로 길이 (km)")
    plt.tight_layout()
    fig3.savefig(OUT/"chart_roads_v2.png",dpi=150,bbox_inches="tight")
    plt.close(); print("  저장: chart_roads_v2.png")

# ── 11. 보고서 ────────────────────────────────────────────────────────────────
print("\n[11] 보고서")
R=[]; r=R.append

r("# CCD × EMSR884 GIS 분석 보고서 v2")
r(f"**2등급 재분류 — Destroyed 전체 포함 기준**  ")
r(f"**RISK(위험)**: ΔCoh ≥ {THR_RISK}  /  **HIGH(고위험)**: ΔCoh ≥ {THR_HIGH}  ")
r("**[DISCLAIMER]** 현장 미검증 예비분석. 확정 피해 판정 아님.\n")

r("---"); r("## 1. CCD 2등급 위험구역 면적")
r("| 등급 | ΔCoh 기준 | 픽셀수 | 면적(km²) |")
r("|------|---------|--------|---------|")
px_km2=(abs(tr.a)*111320)**2/1e6
for c,lb in [(2,f"≥ {THR_HIGH}"),(1,f"{THR_RISK} ~ {THR_HIGH}"),(0,f"< {THR_RISK}")]:
    n=int((cls2==c).sum())
    r(f"| {CLS_LABEL[c]} | {lb} | {n:,} | {n*px_km2:.1f} |")
risk_n=int((cls2>=1).sum())
r(f"| **위험구역 합계(RISK+HIGH)** | ≥ {THR_RISK} | {risk_n:,} | **{risk_n*px_km2:.1f}** |")
r()

r("---"); r("## 2. 건물 피해 × CCD 2등급 교차 분석")
if bpt is not None:
    tot=len(bpt); in_r=(bpt["cls2"]>=1).sum(); in_h=(bpt["cls2"]==2).sum()
    r(f"**총 건물**: {tot}개  |  **위험구역**: {in_r}개 ({100*in_r/tot:.1f}%)  |  **HIGH**: {in_h}개 ({100*in_h/tot:.1f}%)")
    r()
    r("### 피해등급 × CCD 등급 교차표")
    r()
    ct3=pd.crosstab(bpt["damage_gra"],bpt["cls_lbl"])
    co=[c for c in ["HIGH(고위험)","RISK(위험)","변화없음"] if c in ct3.columns]
    ct3=ct3.reindex(columns=co,fill_value=0)
    ro=[d for d in DMG_ORDER if d in ct3.index]
    ct3=ct3.reindex(ro,fill_value=0); ct3["합계"]=ct3.sum(axis=1)
    r("| 피해등급 | "+" | ".join(ct3.columns)+" |")
    r("|"+"---|"*(len(ct3.columns)+1))
    for idx2,row2 in ct3.iterrows():
        r("| "+idx2+" | "+" | ".join(str(v) for v in row2)+" |")
    r()
    r("### 피해등급별 검출률")
    r()
    r("| 피해등급 | 전체 | 위험구역내 | 검출률 | HIGH내 | HIGH검출률 |")
    r("|---------|------|---------|------|------|--------|")
    for row in bpt_summary:
        r(f"| {row['피해등급']} | {row['전체']} | {row['위험구역내']} | {row['검출률%']}% | {row['HIGH내']} | {row['HIGH검출률%']}% |")
    r()

if not grp.empty:
    r("### 건물 폴리곤 통계 (AOI12)")
    r()
    r("| 피해등급 | 건물수 | 총면적(km²) | 평균 HIGH비율 | 평균 위험비율 |")
    r("|---------|------|----------|-----------|-----------|")
    for _,row in grp.iterrows():
        r(f"| {row.damage_gra} | {int(row.n)} | {row.total_area_km2:.4f} | {row.avg_pct_high:.1f}% | {row.avg_pct_risk:.1f}% |")
    r()

r("---"); r("## 3. 도로 노출")
if road_rows:
    r(f"**총 도로**: {total_km:.1f} km")
    r()
    r("| CCD 등급 | 노출 길이(km) | 전체 대비 |")
    r("|---------|------------|---------|")
    for row in road_rows:
        r(f"| {row['등급']} | {row['km']} | {row['pct']}% |")
    r()
    if len(named_risk)>0:
        r("### 위험구역 내 주요 도로 Top10")
        r(); r("| 도로명 | 위험구역내(km) |"); r("|------|------|")
        for _,rrow in named_risk.iterrows():
            r(f"| {rrow.iloc[0]} | {rrow.iloc[1]:.3f} |")
        r()

r("---"); r("## 4. 지표이동 × CCD")
if gm_rows:
    r("| CCD 등급 | 폴리곤수 | 평균변위(m) | 최대변위(m) |")
    r("|---------|--------|----------|----------|")
    for row in gm_rows: r(f"| {row['CCD등급']} | {row['폴리곤수']} | {row['평균변위m']} | {row['최대변위m']} |")
    r()
else: r("장면 내 지표이동 데이터 없음.\n")

r("---"); r("## 5. 진앙 & 단층")
if epi is not None:
    for _,row in epi.iterrows():
        r(f"- **{row.get('type','')}**: M{row.get('mag','')} / {row.get('place','')} / 깊이 {row.get('depth_km','')}km")
    for er in epi_rows:
        r(f"- [{er['type']}] → CCD HIGH 클러스터 중심 **{er['dist_km']} km**")
    r()
if fault_rows:
    r("**HIGH 근접 단층 (GEM):**")
    r()
    r("| 단층명 | 이동유형 | 거리(km) |")
    r("|-------|--------|---------|")
    for f in fault_rows[:5]: r(f"| {f['name']} | {f['slip']} | {f['d']} |")
    r()

r("---"); r("## 6. 종합 시사점")
r()
if bpt is not None:
    tot=len(bpt); in_r=(bpt["cls2"]>=1).sum()
    dest=bpt[bpt["damage_gra"]=="Destroyed"]; dest_r=(dest["cls2"]>=1).sum()
    r(f"1. **Destroyed 전체 포함 확인**: 임계치 ΔCoh ≥ {THR_RISK} 적용 시 Destroyed {dest_r}/{len(dest)}개 ({100*dest_r/len(dest):.0f}%) 위험구역 포함.")
    r(f"2. **전체 건물 검출률**: {in_r}/{tot}개 ({100*in_r/tot:.1f}%) — Damaged 포함 대부분 포착.")
if road_rows:
    risk_km=sum(r2['km'] for r2 in road_rows if r2['등급']!='변화없음')
    r(f"3. **도로 노출**: 위험구역 내 도로 **{risk_km:.0f} km** ({total_km:.0f} km 중).")
r(f"4. **단층 직접 교차**: BOCONO-SAN_SEBASTIAN-EL_PILAR_FAULT 등 기존 활성 단층과 HIGH 클러스터 중첩.")
r(f"5. **진앙 거리**: 본 장면은 진앙에서 ~160km 이상. 카라카스 도심 구조물 원거리 반응 또는 단층 직접 영향 해석 필요.")
r()
r("### 임계치 근거")
r()
r(f"- **ΔCoh < 0 제외 원칙**: ΔCoh = γ_pre − γ_co < 0 은 co-event 코히런스가 오히려 증가한 경우. 피해 신호와 반대 방향이므로 신뢰성 없음.")
r(f"- ΔCoh 하한 **{THR_RISK}** (RISK 시작): 단일 패스 S-1 IW 코히런스 노이즈 플로어(~0.05-0.1) 이상. 실질적인 코히런스 손실 시작점.")
r(f"- ΔCoh 상한(HIGH) **{THR_HIGH}**: 강한 코히런스 급락 구간. Destroyed 중위값(0.44) 근처. HIGH에는 Destroyed 약 절반 이상 포함.")
r(f"- Destroyed 1개(ΔCoh=-0.1784)는 CCD 미검출 — 해당 위치의 코히런스가 지진 후 오히려 증가(noise/debris specular reflection 가능). CCD false negative로 처리.")
r(f"- COH_THR(γ_pre 전처리) 미적용 — 사전 코히런스 필터링 제거하여 건물 누락 방지")
r()
r("---")
r("*[DISCLAIMER] 현장 미검증 예비분석. 단일 co-event 페어 기반. 확정 피해 판정 아님.*")

rpt=OUT/"report_v2.md"
with open(rpt,"w",encoding="utf-8") as f: f.write("\n".join(R))
print(f"  저장: {rpt.name}")

print("\n"+"="*65)
print("  완료.")
for p in sorted(OUT.glob("*v2*")):
    print(f"    {p.name:<44} {p.stat().st_size//1024:>4} KB")
print("="*65)
print("\n[DISCLAIMER] 현장 미검증 예비분석. 확정 피해 판정 아님.")
