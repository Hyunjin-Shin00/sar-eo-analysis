"""재계산 1: CCD 면적·EMSR884 교차·v7 분류 교차 (읽기 전용)"""
import os
import warnings; warnings.filterwarnings("ignore")
import numpy as np, rasterio, geopandas as gpd, pandas as pd, json
from rasterio.windows import from_bounds
from shapely.geometry import box
R=os.environ.get("DATA_ROOT", "<DATA_ROOT>")+"/"; V=R+"Venezuela/"
DV=V+"right/output/dcoh_VV.tif"
def pxarea(src, lat):
    a=src.res[0]; return (a*111.32*np.cos(np.radians(lat)))*(a*110.57)  # km2
def clip(bounds):
    with rasterio.open(DV) as s:
        w=from_bounds(*bounds,s.transform); a=s.read(1,window=w,boundless=True,fill_value=-9999.)
        return a, s
print("== A. 전체 장면 ΔCoh 3등급 (right VV)")
with rasterio.open(DV) as s:
    a=s.read(1); pa=pxarea(s,10.48)
    v=a[(a!=-9999)&np.isfinite(a)]
    print(" valid px",v.size," px area km2 %.6f (스크립트 가정 0.000196)"%pa)
    for lo,hi,n in [(0.2,0.4,"LOW"),(0.4,0.6,"MID"),(0.6,9,"HIGH")]:
        c=int(((v>=lo)&(v<hi)).sum()); print(f"  {n}: {c} px  {c*0.000196:.2f} km2(0.000196 가정) / {c*pa:.2f} km2(실면적)")
    print("  ΔCoh<0 비율 %.3f, 중앙값 %.3f"%((v<0).mean(),np.median(v)))
print("== B. AOI 면적")
for name,b in [("catia(-67.075,10.578,-66.995,10.618)",(-67.075,10.578,-66.995,10.618)),("fusion(-67.0735,10.5627,-66.9351,10.6149)",(-67.0735,10.5627,-66.9351,10.6149))]:
    a,s=clip(b); pa=pxarea(s,10.59); v=a[(a!=-9999)&np.isfinite(a)]
    print(f" {name}: valid {v.size} px = {v.size*pa:.2f} km2 | >=0.1 {int((v>=0.1).sum())} ({(v>=0.1).mean()*100:.1f}%) {int((v>=0.1).sum())*pa:.2f} km2 | >=0.4 {int((v>=0.4).sum())} ({(v>=0.4).mean()*100:.1f}%) {int((v>=0.4).sum())*pa:.2f} km2")
print("== C. EMSR884 피해건물 × CCD (catia AOI clip)")
E=R+"EMSR884_products/"
P=[E+"EMSR884_AOI02_GRA_MONIT01_v2/EMSR884_AOI02_GRA_MONIT01_builtUpP_v1.shp",E+"EMSR884_AOI05_GRA_PRODUCT_v1/EMSR884_AOI05_GRA_PRODUCT_builtUpP_v1.shp",
   E+"EMSR884_AOI06_GRA_MONIT01_v2/EMSR884_AOI06_GRA_MONIT01_builtUpP_v1.shp",E+"EMSR884_AOI08_GRA_MONIT01_v2/EMSR884_AOI08_GRA_MONIT01_builtUpP_v1.shp",
   E+"EMSR884_AOI12_GRA_PRODUCT_v2/EMSR884_AOI12_GRA_PRODUCT_builtUpA_v2.shp"]
g=pd.concat([gpd.read_file(p).to_crs(4326) for p in P],ignore_index=True)
g=gpd.GeoDataFrame(g,geometry=g.geometry.centroid,crs=4326)
print(" EMSR 전체 피해객체:",g.damage_gra.value_counts().to_dict())
def samp(gg):
    with rasterio.open(DV) as s: return np.array([x[0] for x in s.sample([(p.x,p.y) for p in gg.geometry])])
g["d"]=samp(g)
for nm,b in [("catia",(-67.075,10.578,-66.995,10.618)),("fusion",(-67.0735,10.5627,-66.9351,10.6149))]:
    gg=g[g.within(box(*b))].copy()
    print(f" [{nm}] n={len(gg)}")
    for k,sub in gg.groupby("damage_gra"):
        d=sub.d.values; ok=(d!=-9999)
        print(f"   {k}: n={len(d)} nodata={int((~ok).sum())} >=0.1 {int((d>=0.1).sum())} ({(d>=0.1).mean()*100:.1f}%)  >=0.4 {int((d>=0.4).sum())}  median ΔCoh {np.median(d[ok]):.3f}")
gg=g.copy(); ok=gg.d!=-9999
print(" [전체장면, 0.4 기준] n=%d, >=0.4: %d (%.1f%%)"%(len(gg),int((gg.d>=0.4).sum()),(gg.d>=0.4).mean()*100))
for k,sub in gg.groupby("damage_gra"): print("   ",k,len(sub),int((sub.d>=0.4).sum()),int((sub.d>=0.2).sum()), "nodata",int((sub.d==-9999).sum()))
print("== D. v7 광학 분류 재현")
f=gpd.read_file(V+"analysis_v7/damage_assessment_categories.gpkg")
print(" 등급:",f.damage_category.value_counts().to_dict())
print(pd.crosstab(f.damage_category,[f.is_hand_damaged,f.is_hand_intact]))
J=json.load(open(V+"analysis_v7/damage_classifier_v7.json"))
X=f[J["features"]].values.astype(float); z=(X-np.array(J["scaler_mean"]))/np.array(J["scaler_scale"])
p=1/(1+np.exp(-(z@np.array(J["lr_coef"])+J["lr_intercept"])))
okp=np.isfinite(p)
print(" LR 재채점 vs 저장 pred_proba_v7_lr 최대차 %.2e (유효 %d)"%(np.nanmax(np.abs(p-f.pred_proba_v7_lr.values)),okp.sum()))
print(" p>=thr(%.4f): %d"%(J["decision_threshold_lr"],int((p>=J["decision_threshold_lr"]).sum())))
for c in ["full_destruction","partial_affected","minor_or_none"]:
    s=f[f.damage_category==c]; print("  %s: p_lr range %.3f~%.3f, p_gb range %.4f~%.4f"%(c,s.pred_proba_v7_lr.min(),s.pred_proba_v7_lr.max(),s.pred_proba_v7_gb.min(),s.pred_proba_v7_gb.max()))
from sklearn.metrics import roc_auc_score
h=f[(f.is_hand_damaged==1)|(f.is_hand_intact==1)]
y=(h.is_hand_damaged==1).astype(int); 
print(" 수작업 라벨 n=%d (pos %d / neg %d), 저장 LR 확률 in-sample AUC %.3f, GB %.3f"%(len(h),y.sum(),len(y)-y.sum(),roc_auc_score(y,h.pred_proba_v7_lr.fillna(0)),roc_auc_score(y,h.pred_proba_v7_gb.fillna(0))))
fc=gpd.GeoDataFrame(f,geometry=f.geometry.centroid,crs=f.crs).to_crs(4326); fc["d"]=samp(fc)
print(" v7 등급 × CCD(fusion 0.1/0.4):")
for c in ["full_destruction","partial_affected","minor_or_none"]:
    d=fc[fc.damage_category==c].d.values
    print(f"   {c}: n={len(d)} >=0.1 {int((d>=0.1).sum())} ({(d>=0.1).mean()*100:.1f}%)  >=0.4 {int((d>=0.4).sum())} ({(d>=0.4).mean()*100:.1f}%) nodata {int((d==-9999).sum())}")
