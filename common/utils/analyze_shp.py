"""Taean.shp 폴리곤 내부에서 N2/S1 각 변화 산출물이 값을 낼 수 있는지 분석.
   폴리곤 래스터화 -> DEM(육/수), 코히런스(N2 vs S1), 진폭변화, OT상관 을 폴리곤 내부 통계로 평가."""
import numpy as np, json, rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin; from rasterio.warp import reproject, Resampling
from osgeo import ogr
import matplotlib; matplotlib.use("Agg")
from matplotlib import font_manager as fm
import matplotlib.pyplot as plt
FP="/mnt/c/Windows/Fonts/malgun.ttf"; fm.fontManager.addfont(FP)
plt.rcParams['font.family']=fm.FontProperties(fname=FP).get_name(); plt.rcParams['axes.unicode_minus']=False
CCD="<DATA_ROOT>/N2_InSAR/N2/taean_CCD/"; OT="<DATA_ROOT>/N2_InSAR/N2/taean_OT/"; DEM="<DATA_ROOT>/N2_InSAR/DEM/cop_dem_N36E126.tif"
S,Nn,W,E=36.3899,36.4350,126.3548,126.4107
res=0.00027778; gx=np.arange(W,E+res,res); gy=np.arange(Nn,S-res,-res); GX,GY=np.meshgrid(gx,gy); H,Wd=GX.shape
EXT=[gx[0],gx[-1],gy[-1],gy[0]]; tr=from_origin(gx[0]-res/2,gy[0]+res/2,res,res)
# 폴리곤 래스터화
ds=ogr.Open('<DATA_ROOT>/N2_InSAR/shp/Taean.shp'); ly=ds.GetLayer(); f=ly.GetNextFeature(); gj=json.loads(f.GetGeometryRef().ExportToJson())
poly=rasterize([(gj,1)],out_shape=(H,Wd),transform=tr,fill=0,all_touched=True).astype(bool)
print("폴리곤 화소수(30m grid):",poly.sum())
def load(f):
    d=rasterio.open(f); a=d.read(1).astype('float32'); out=np.full((H,Wd),np.nan,np.float32)
    reproject(a,out,src_transform=d.transform,src_crs=d.crs,dst_transform=tr,dst_crs='EPSG:4326',resampling=Resampling.bilinear,src_nodata=np.nan,dst_nodata=np.nan); return out
demg=np.full((H,Wd),np.nan,np.float32); dd=rasterio.open(DEM)
reproject(dd.read(1).astype('float32'),demg,src_transform=dd.transform,src_crs=dd.crs,dst_transform=tr,dst_crs='EPSG:4326',resampling=Resampling.bilinear)
prods={
 "N2 coh (0511x0515,4d)":CCD+"N2_AL_20260511_20260515_coherence.tif",
 "S1 coh (0519x0531,12d)":CCD+"s1_20260519_20260531_coherence.tif",
 "N2 logratio dB (0511-0706)":CCD+"N2_AL_20260511_20260706_logratio_dB.tif",
 "S1 logratio dB (0519-0613)":CCD+"s1_20260519_20260613_logratio_dB.tif",
 "N2 OT corr (0515x0614)":OT+"N2_AL_20260515_20260614_OT_correlation.tif",
 "S1 OT corr (0519x0613)":OT+"s1_20260519_20260613_OT_correlation.tif",
}
def stat(a,m):
    v=a[m&np.isfinite(a)];
    return (len(v),100*len(v)/max(m.sum(),1),np.nanmean(v) if len(v) else np.nan,np.nanmedian(v) if len(v) else np.nan)
print("\n=== 폴리곤 내부 DEM(고도) ===")
dv=demg[poly&np.isfinite(demg)]
print("  min %.2f  p25 %.2f  median %.2f  p75 %.2f  max %.2f  m"%(dv.min(),np.percentile(dv,25),np.median(dv),np.percentile(dv,75),dv.max()))
print("  육지(>1m) 비율 %.0f%%  (물마스크로 잘리는 비율 %.0f%%)"%(100*np.mean(dv>1),100*np.mean(dv<=1)))
print("\n=== 폴리곤 내부 산출물 통계 (유효화소수, 유효%, 평균, 중앙값) ===")
res_stats={}
for name,fp in prods.items():
    try:
        a=load(fp); n,pc,mn,md=stat(a,poly); res_stats[name]=(n,pc,mn,md)
        print("  %-28s n=%4d  valid=%5.1f%%  mean=%.3f  median=%.3f"%(name,n,pc,mn,md))
    except Exception as e: print("  %-28s ERR %s"%(name,e)); res_stats[name]=None

# --- 그림: 폴리곤 확대 + 오버레이 ---
from matplotlib.patches import Polygon as MplPoly
coords=gj['coordinates'][0]
def draw_poly(ax): ax.add_patch(MplPoly(coords,fill=False,edgecolor='red',lw=2))
pb=[min(c[0] for c in coords),max(c[0] for c in coords),min(c[1] for c in coords),max(c[1] for c in coords)]
pad=0.004; zext=[pb[0]-pad,pb[1]+pad,pb[2]-pad,pb[3]+pad]
panels=[("N2 코히런스 4일",CCD+"N2_AL_20260511_20260515_coherence.tif",'viridis',(0,0.6)),
        ("S1 코히런스 12일",CCD+"s1_20260519_20260531_coherence.tif",'viridis',(0,0.6)),
        ("N2 진폭 로그비 dB",CCD+"N2_AL_20260511_20260706_logratio_dB.tif",'RdBu_r',(-6,6)),
        ("S1 진폭 로그비 dB",CCD+"s1_20260519_20260613_logratio_dB.tif",'RdBu_r',(-6,6))]
fig,ax=plt.subplots(1,4,figsize=(21,5.6))
for i,(t,fp,cm,vr) in enumerate(panels):
    a=load(fp); m=poly&np.isfinite(a); mv=np.nanmean(a[m]) if m.sum() else np.nan
    im=ax[i].imshow(a,cmap=cm,vmin=vr[0],vmax=vr[1],extent=EXT); draw_poly(ax[i])
    ax[i].set_xlim(zext[0],zext[1]); ax[i].set_ylim(zext[2],zext[3])
    ax[i].set_title("%s\n폴리곤 평균 %.3f"%(t,mv),fontsize=10); plt.colorbar(im,ax=ax[i],fraction=.046); ax[i].set_xlabel("경도")
ax[0].set_ylabel("위도")
plt.suptitle("Taean.shp 폴리곤(빨강) 내부 변화 산출 가능성 — N2 vs S1",fontsize=13)
plt.tight_layout(); plt.savefig(CCD+"shp_feasibility.png",dpi=120); print("\nsaved shp_feasibility.png")
