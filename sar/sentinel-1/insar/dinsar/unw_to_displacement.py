"""ISCE2 언랩 결과(filt_topophase.unw.geo, band2=위상)를 LOS 변위로 변환해 GeoTIFF 산출.
   d_LOS = -(lambda/4pi) * phi_unw  [양수=위성쪽 접근/거리감소].
   ★바다/물 마스킹: Copernicus DEM(바다=0m) 고도 <= WATER_H 픽셀 제거. 기준점은 육지 코히런스 픽셀.
   출력: isce2/merged/isce_los_disp_cm.tif (+ meters), watermask, 미리보기 PNG."""
import numpy as np, rasterio, time
from rasterio.warp import reproject, Resampling
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import s1insar as S1
t0=time.time()
M="<DATA_ROOT>/N2_InSAR/N2/taean_Insar/isce2/merged/"
Z="<DATA_ROOT>/N2_InSAR/sentinel1/S1C_IW_SLC__1SDV_20260519T214004_20260519T214028_007728_00FB4A_A82C.zip"
WATER_H=1.0                                                    # 이 고도(m) 이하 = 바다/물로 간주해 마스킹
lam=S1.S1Scene(Z,"iw1","vv",0).wavelength                       # S1 C-band 파장(정확값)
print("[%.1fs] wavelength = %.6f m (%.4f cm)"%(time.time()-t0,lam,lam*100))

unw=rasterio.open(M+"filt_topophase.unw.geo"); phase=unw.read(2).astype(np.float64); amp=unw.read(1).astype(np.float64)
cor=rasterio.open(M+"topophase.cor.geo").read(2).astype(np.float64)
tr=unw.transform; crs=unw.crs; H,W=phase.shape

# 물 마스크: Copernicus DEM 을 ISCE 격자로 리샘플 후 저고도 = 바다
dem=rasterio.open("<DATA_ROOT>/N2_InSAR/DEM/cop_dem_N36E126.tif")
demg=np.full((H,W),np.nan,np.float32)
reproject(dem.read(1).astype('float32'),demg,src_transform=dem.transform,src_crs=dem.crs,
          dst_transform=tr,dst_crs='EPSG:4326',resampling=Resampling.bilinear)
land=np.isfinite(demg)&(demg>WATER_H)                          # 육지
water=~land

# 유효 = 언랩됨 & 코히런스>0 & 육지
valid=(phase!=0)&np.isfinite(phase)&(cor>0)&land
COH_REF=0.3                                                     # 기준점: 육지 & 코히런스>=0.3
ref_mask=valid&(cor>=COH_REF)
ref=np.median(phase[ref_mask]) if ref_mask.sum()>20 else np.median(phase[valid])
phase_rel=phase-ref                                            # 기준점 상대 위상

disp_m=-(lam/(4*np.pi))*phase_rel                             # LOS 변위(m), +=위성접근
disp_cm=disp_m*100.0
disp_cm[~valid]=np.nan; disp_m[~valid]=np.nan                 # 바다·무효 픽셀 NaN

def wtif(nm,arr,dt='float32'):
    with rasterio.open(M+nm,'w',driver='GTiff',height=H,width=W,count=1,dtype=dt,
                       crs=crs,transform=tr,nodata=(np.nan if dt=='float32' else 0),compress='deflate') as d:
        d.write(arr.astype(dt),1)
wtif("isce_los_disp_cm.tif",disp_cm); wtif("isce_los_disp_m.tif",disp_m)
wtif("isce_watermask.tif",land.astype('uint8'),'uint8')       # 1=육지, 0=물

vv=disp_cm[np.isfinite(disp_cm)]
print("[%.1fs] land frac=%.2f (water masked=%.2f)  valid(land)px=%d  ref px=%d"%(time.time()-t0,land.mean(),water.mean(),valid.sum(),ref_mask.sum()))
print("       disp_cm(land)  min=%.2f  max=%.2f  mean=%.2f  std=%.2f  p5=%.2f p95=%.2f"%(
      vv.min(),vv.max(),vv.mean(),vv.std(),np.percentile(vv,5),np.percentile(vv,95)))

# 미리보기
ext=[unw.bounds.left,unw.bounds.right,unw.bounds.bottom,unw.bounds.top]
lim=np.nanpercentile(np.abs(disp_cm),98)
demshow=np.where(np.isfinite(demg),demg,np.nan)
fig,ax=plt.subplots(1,3,figsize=(19,5.5))
im=ax[0].imshow(demshow,cmap='terrain',extent=ext); ax[0].set_title("Copernicus DEM (m) — sea≈0"); plt.colorbar(im,ax=ax[0],fraction=.046,label="m")
ax[0].contour(np.flipud(land.astype(float)),levels=[0.5],colors='r',linewidths=0.8,extent=ext)
im=ax[1].imshow(np.where(np.isfinite(disp_cm),disp_cm,np.nan),cmap='RdBu_r',vmin=-lim,vmax=lim,extent=ext)
ax[1].set_title("ISCE2 LOS disp (cm) — WATER MASKED  [+=toward sat]"); plt.colorbar(im,ax=ax[1],fraction=.046,label="cm")
im=ax[2].imshow(np.where(land,cor,np.nan),cmap='viridis',vmin=0,vmax=1,extent=ext); ax[2].set_title("coherence (land only, mean %.2f)"%np.nanmean(cor[land&(cor>0)])); plt.colorbar(im,ax=ax[2],fraction=.046)
for a in ax: a.set_xlabel("lon"); a.set_ylabel("lat")
plt.suptitle("Taean S1C 0519x0531 (12-day, C-band) — ISCE2 unwrapped -> LOS disp, sea(DEM<=%.1fm) masked"%WATER_H,fontsize=12)
plt.tight_layout(); plt.savefig(M+"isce_los_disp.png",dpi=110); print("[%.1fs] saved isce_los_disp.png"%(time.time()-t0))
