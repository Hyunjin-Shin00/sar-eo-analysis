"""S1 코히런스 변화탐지 + 진폭 변화 (Sentinel-1). N2 CCD와 동일 산출 구성.
   코히런스: 기존 s1fin 간섭코히런스(0519x0531, 0531x0613) 재활용 + 변화(후-전).
   진폭: 0519/0531/0613 신규 지오코딩 -> RGB + 로그비(0519->0613) + 필터(임계+단조성+공간정리).
   결과 taean_CCD, s1_ 명명. 물(DEM<=1m) 마스킹."""
import numpy as np, time, rasterio
from scipy.ndimage import zoom, map_coordinates, spline_filter
import scipy.ndimage as ndi
from scipy.interpolate import griddata
import matplotlib; matplotlib.use("Agg")
from matplotlib import font_manager as fm
import matplotlib.pyplot as plt
FP="/mnt/c/Windows/Fonts/malgun.ttf"; fm.fontManager.addfont(FP)
plt.rcParams['font.family']=fm.FontProperties(fname=FP).get_name(); plt.rcParams['axes.unicode_minus']=False
from rasterio.transform import from_origin; from rasterio.warp import reproject, Resampling
import n2insar as N, s1insar as S1
t0=time.time(); OUT="/mnt/c/N2_InSAR/N2/taean_CCD/"; INS="/mnt/c/N2_InSAR/N2/taean_Insar/"
def log(*a): print("[%6.1fs]"%(time.time()-t0),*a,flush=True)
Z="/mnt/c/N2_InSAR/sentinel1/"; DEM="/mnt/c/N2_InSAR/DEM/cop_dem_N36E126.tif"
S,Nn,W,E=36.3899,36.4350,126.3548,126.4107; AY,AX=2,12; dem=N.DemInterp(DEM)
ZP={"0519":Z+"S1C_IW_SLC__1SDV_20260519T214004_20260519T214028_007728_00FB4A_A82C.zip",
    "0531":Z+"S1C_IW_SLC__1SDV_20260531T214004_20260531T214029_007903_010126_2310.zip",
    "0613":Z+"S1D_IW_SLC__1SDV_20260613T214015_20260613T214042_003223_0059FE_D74F.zip"}
res=0.00027778; gx=np.arange(W,E+res,res); gy=np.arange(Nn,S-res,-res); GX,GY=np.meshgrid(gx,gy); EXT=[gx[0],gx[-1],gy[-1],gy[0]]
tr=from_origin(gx[0]-res/2,gy[0]+res/2,res,res)
demg=np.full(GX.shape,np.nan,np.float32); dd=rasterio.open(DEM)
reproject(dd.read(1).astype('float32'),demg,src_transform=dd.transform,src_crs=dd.crs,dst_transform=tr,dst_crs='EPSG:4326',resampling=Resampling.bilinear)
WATER=~(np.isfinite(demg)&(demg>1.0))
def load_grid(f):
    ds=rasterio.open(f); a=ds.read(1).astype('float32'); out=np.full(GX.shape,np.nan,np.float32)
    reproject(a,out,src_transform=ds.transform,src_crs=ds.crs,dst_transform=tr,dst_crs='EPSG:4326',resampling=Resampling.bilinear,src_nodata=np.nan,dst_nodata=np.nan)
    out[WATER]=np.nan; return out
# --- 코히런스 재활용 ---
Cab=load_grid(INS+"s1fin_ab_coherence.tif"); Ccd=load_grid(INS+"s1fin_cd_coherence.tif")
Cchg=Ccd-Cab
log("coh reuse: 0519x0531 mean %.3f, 0531x0613 mean %.3f"%(np.nanmean(Cab),np.nanmean(Ccd)))
def mls(x): n=(x.shape[0]//AY)*AY; mm=(x.shape[1]//AX)*AX; return x[:n,:mm].reshape(n//AY,AY,mm//AX,AX).mean(axis=(1,3))
def amp_geo(key):
    m=S1.S1Scene(ZP[key],"iw1","vv",0); N.calibrate_side(m,36.41,126.38)
    LA,LO=np.meshgrid(np.linspace(S,Nn,6),np.linspace(W,E,6)); T=N.geo2ecef(LA.ravel(),LO.ravel(),np.full(LA.size,15.))
    tm,Rm=N.geo2rdr(m,T,t_guess=m.line_to_t(m.lpb//2)); mln=m.t_to_line(tm); mcl=m.r_to_col(Rm); mar=60
    L0=max(0,int(mln.min())-mar);L1=min(m.lpb,int(mln.max())+mar);C0=max(0,int(mcl.min())-mar);C1=min(m.ncols,int(mcl.max())+mar)
    cx,_=m.read_slc(L0,L1,C0,C1); amp=np.abs(cx).astype(np.float32); NL,NC=amp.shape
    SG=4; si=np.arange(L0,L1,SG); sj=np.arange(C0,C1,SG); GI,GJ=np.meshgrid(si,sj,indexing='ij')
    Tg,LAT,LON,_=N.rdr2geo_dem(m,m.line_to_t(GI),m.col_to_r(GJ),dem,h0=float(np.nanmedian(dem.arr)),n_iter=4)
    A=mls(amp); H,Wd=A.shape
    ry,rx=np.meshgrid(np.arange(H),np.arange(Wd),indexing='ij'); oy=((ry*AY+AY/2))/SG; ox=((rx*AX+AX/2))/SG
    la=map_coordinates(LAT,[oy.ravel(),ox.ravel()],order=1,mode='nearest'); lo=map_coordinates(LON,[oy.ravel(),ox.ravel()],order=1,mode='nearest')
    v=np.isfinite(la)&(A.ravel()>0); G=griddata(np.c_[lo[v],la[v]],A.ravel()[v],(GX,GY),method='linear'); G[WATER]=np.nan
    log("amp %s done"%key); return G
A19=amp_geo("0519"); A31=amp_geo("0531"); A13=amp_geo("0613")
# 로그비 + 필터 (0519->0613)
land=np.isfinite(A19)&np.isfinite(A13)&(A19>0)&(A13>0)
LR=np.full(A19.shape,np.nan); LR[land]=20*np.log10(A13[land]/A19[land])
v=LR[np.isfinite(LR)]; med=np.median(v); mad=np.median(np.abs(v-med)); thr=max(2*1.4826*mad,1.5)
LRf=LR.copy(); LRf[~np.isfinite(LRf)]=med; LRf=ndi.median_filter(LRf,3); LRf[~land]=np.nan
sigm=np.isfinite(LRf)&(np.abs(LRf-med)>thr)
d1=A31-A19; d2=A13-A31; mono=np.isfinite(d1)&np.isfinite(d2)&(np.sign(d1)==np.sign(d2))
mask=sigm&mono; mask=ndi.binary_opening(mask,structure=np.ones((3,3)))
lab,n=ndi.label(mask)
if n>0: sz=ndi.sum(np.ones(lab.shape),lab,index=np.arange(1,n+1)); keep=np.zeros(n+1,bool); keep[1:]=sz>=8; mask=keep[lab]
change=np.where(mask,LRf-med,np.nan); frac=100.0*mask.sum()/max(land.sum(),1)
log("S1 LR thr=%.2fdB changed land frac=%.1f%%"%(thr,frac))
def norm(a): lo,hi=np.nanpercentile(a,2),np.nanpercentile(a,98); return np.clip((a-lo)/(hi-lo+1e-9),0,1)
RGB=np.dstack([norm(A19),norm(A31),norm(A13)]); RGB[np.repeat(WATER[:,:,None],3,axis=2)]=0
def wtif(nm,a):
    with rasterio.open(OUT+nm,'w',driver='GTiff',height=a.shape[0],width=a.shape[1],count=1,dtype='float32',crs='EPSG:4326',transform=tr,nodata=np.nan,compress='deflate') as d: d.write(a.astype('float32'),1)
wtif("s1_20260519_20260531_coherence.tif",Cab); wtif("s1_20260531_20260613_coherence.tif",Ccd)
wtif("s1_coherence_change_20260519_20260531_vs_20260531_20260613.tif",Cchg)
wtif("s1_20260519_amplitude.tif",A19); wtif("s1_20260531_amplitude.tif",A31); wtif("s1_20260613_amplitude.tif",A13)
wtif("s1_20260519_20260613_logratio_dB.tif",LR); wtif("s1_20260519_20260613_change_filtered_dB.tif",change)
log("tifs saved")
# 그림
lim=max(np.nanpercentile(np.abs(LR),98),thr+1)
fig,ax=plt.subplots(2,3,figsize=(19,11))
ax[0,0].imshow(RGB,extent=EXT); ax[0,0].set_title("진폭 다중시점 RGB\nR=0519 G=0531 B=0613")
im=ax[0,1].imshow(LR-med,cmap='RdBu_r',vmin=-lim,vmax=lim,extent=EXT); ax[0,1].set_title("진폭 로그비 0519->0613 (dB)\n+밝아짐 / -어두워짐"); plt.colorbar(im,ax=ax[0,1],fraction=.046)
im=ax[0,2].imshow(change,cmap='RdBu_r',vmin=-lim,vmax=lim,extent=EXT); ax[0,2].set_title("진폭 변화 필터 최종 (육지의 %.1f%%)\n지속·유의·공간정리"%frac); plt.colorbar(im,ax=ax[0,2],fraction=.046)
im=ax[1,0].imshow(Cab,cmap='viridis',vmin=0,vmax=0.6,extent=EXT); ax[1,0].set_title("코히런스 0519x0531 (12일)  평균 %.2f"%np.nanmean(Cab)); plt.colorbar(im,ax=ax[1,0],fraction=.046)
im=ax[1,1].imshow(Ccd,cmap='viridis',vmin=0,vmax=0.6,extent=EXT); ax[1,1].set_title("코히런스 0531x0613 (13일)  평균 %.2f"%np.nanmean(Ccd)); plt.colorbar(im,ax=ax[1,1],fraction=.046)
im=ax[1,2].imshow(Cchg,cmap='RdBu_r',vmin=-0.3,vmax=0.3,extent=EXT); ax[1,2].set_title("코히런스 변화 (후 - 전)\n+안정화 / -활성화"); plt.colorbar(im,ax=ax[1,2],fraction=.046)
for a in ax.ravel(): a.set_xlabel("경도"); a.set_ylabel("위도")
plt.suptitle("태안 사구 — Sentinel-1 CCD (코히런스 변화 + 다중시점 진폭), 물 마스킹",fontsize=13)
plt.tight_layout(); plt.savefig(OUT+"s1_CCD_overview.png",dpi=110); log("saved s1_CCD_overview.png")
