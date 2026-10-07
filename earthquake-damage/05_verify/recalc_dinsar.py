"""재계산 2: CCD 등급 래스터 · DInSAR 변위 통계 · EMS GRM 비교 (읽기 전용)"""
import os
import warnings; warnings.filterwarnings("ignore")
import numpy as np, rasterio
from rasterio.windows import from_bounds
from rasterio.warp import reproject, Resampling
V=os.environ.get("DATA_ROOT", "<DATA_ROOT>")+"/Venezuela/"
with rasterio.open(V+"right/output/dcoh_class_VV.tif") as s: c=s.read(1)
print("class_VV 값별 px:",{int(k):int(v) for k,v in zip(*np.unique(c,return_counts=True))})
with rasterio.open(V+"right/output/dcoh_class2_VV.tif") as s: c=s.read(1)
print("class2_VV 값별 px:",{int(k):int(v) for k,v in zip(*np.unique(c,return_counts=True))})
# 등급 래스터가 γ_pre 마스크를 쓰는지 확인
with rasterio.open(V+"right/20260613_20260618_Orb_Stack_Ifg_Deb_Flt_IW1_TC.tif") as s: print("gamma_pre tif bands",s.count,s.descriptions,s.shape)
print("== right DInSAR LOS 변위 (06-18→06-25)")
b=(-67.0735,10.5627,-66.9351,10.6149)
with rasterio.open(V+"right/20260618_20260625_C8C0_Orb_Stack_Ifg_Deb_Flt_unw_vh_dsp_TC.tif") as s:
    w=from_bounds(*b,s.transform); d=s.read(1,window=w); full=s.read(1,out_shape=(s.height//4,s.width//4))
v=d[np.isfinite(d)&(d!=0)]*100
print(" fusion AOI px %d: min %.1f max %.1f mean %.1f p5 %.1f p50 %.1f p95 %.1f cm"%(v.size,v.min(),v.max(),v.mean(),*np.percentile(v,[5,50,95])))
vf=full[np.isfinite(full)&(full!=0)]*100
print(" 전체 장면(1/4 표본) px %d: min %.1f max %.1f p5 %.1f p50 %.1f p95 %.1f std %.1f cm"%(vf.size,vf.min(),vf.max(),*np.percentile(vf,[5,50,95]),vf.std()))
print("== left 1일 페어(06-23 S1A → 06-24 S1C, 본진 약 45분 후 촬영) 언랩 위상 vs EMS GRM")
lam=0.0554658
with rasterio.open(V+"left/subset_1_of_2026062320260624_Orb_Stack_Ifg_Deb_Flt_unw_TC.tif") as s:
    f=8; ph=s.read(1,out_shape=(s.height//f,s.width//f)); tr=s.transform*s.transform.scale(s.width/ph.shape[1],s.height/ph.shape[0]); crs=s.crs
ph[(ph==0)|~np.isfinite(ph)]=np.nan
print(" 유효 %.1f%%, 위상 범위 %.1f~%.1f rad (= %.1f~%.1f cm, d=-φλ/4π 부호 미적용 크기)"%(np.isfinite(ph).mean()*100,np.nanmin(ph),np.nanmax(ph),np.nanmin(ph)*lam/4/np.pi*100,np.nanmax(ph)*lam/4/np.pi*100))
E=os.environ.get("DATA_ROOT", "<DATA_ROOT>")+"/EMSR884_products/EMSR884_AOI00_GRM_PRODUCT_v2/EMSR884_AOI00_GRM_PRODUCT_groundMovementA_v2.tif"
em=np.full(ph.shape,np.nan,np.float32)
with rasterio.open(E) as s:
    reproject(rasterio.band(s,1),em,dst_transform=tr,dst_crs=crs,resampling=Resampling.average,src_nodata=np.nan,dst_nodata=np.nan)
m=np.isfinite(ph)&np.isfinite(em)
print(" 겹침 화소 %d (8배 다운샘플)"%m.sum())
if m.sum()>100:
    d_ours=-ph[m]*lam/(4*np.pi); e=em[m]
    r=np.corrcoef(d_ours,e)[0,1]
    print(" EMS GRM(m) 범위 p5 %.3f p50 %.3f p95 %.3f"%tuple(np.percentile(e,[5,50,95])))
    print(" 우리 LOS(m, d=-φλ/4π) p5 %.3f p50 %.3f p95 %.3f"%tuple(np.percentile(d_ours,[5,50,95])))
    print(" Pearson r(우리, EMS) = %.3f  (부호 반대 규약이면 %.3f)"%(r,-r))
    dd=(d_ours-np.median(d_ours))-(e-np.median(e)); print(" 중앙값 제거 후 차이 RMS %.3f m, 슬로프(EMS~우리) %.2f"%(np.sqrt(np.mean(dd**2)),np.polyfit(d_ours,e,1)[0]))
    np.savez_compressed("left_vs_ems.npz",ours=np.where(m,-ph*lam/(4*np.pi),np.nan),ems=np.where(m,em,np.nan),b=np.array(rasterio.transform.array_bounds(*ph.shape,tr)))
