"""사구 변화 — 코히런스 변화탐지 + 진폭 다중시점 (N2 A_L). OT와 다른 기법 → taean_CCD.
   ① 코히런스: 초기 짧은쌍(0511x0515,4일) vs 후기(0614x0706,22일) 간섭 코히런스 + 차분
      (활성모래=저코히런스. 활성역 패턴/경계 변화가 사구활동 정황)
   ② 진폭: 0511/0614/0706 다중시점 지오코딩 → RGB 합성 + 진폭차분(0706-0511) (사면 형태이동 시각화)
   물(DEM<=1m) 마스킹. 결과 C:\\N2_InSAR\\N2\\taean_CCD."""
import numpy as np, time
from scipy.ndimage import zoom, map_coordinates, spline_filter
from scipy.interpolate import griddata
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import rasterio; from rasterio.transform import from_origin; from rasterio.warp import reproject, Resampling
import n2insar as N
t0=time.time(); OUT="<DATA_ROOT>/N2_InSAR/N2/taean_CCD/"
def log(*a): print("[%6.1fs]"%(time.time()-t0),*a,flush=True)
R="<DATA_ROOT>/N2_InSAR/N2/Taean_recent/"; DEM="<DATA_ROOT>/N2_InSAR/DEM/cop_dem_N36E126.tif"
S,Nn,W,E=36.3899,36.4350,126.3548,126.4107; AY,AX=10,12; dem=N.DemInterp(DEM)
P={"0511":R+"20260511/N2_SAR_20260511_064011K_16300_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260511_064011_ST_BB_VV_A_L_SSC_B_NP04.h5",
   "0515":R+"20260515/N2_SAR_20260515_063509K_16360_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260515_063509_ST_BB_VV_A_L_SSC_B_NP04.h5",
   "0614":R+"20260614/N2_SAR_20260614_063801K_16812_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260614_063801_ST_BB_VV_A_L_SSC_B_NP04.h5",
   "0706":R+"20260706/N2_SAR_20260706_064518K_17144_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260706_064518_ST_BB_VV_A_L_SSC_B_NP04.h5"}
res=0.00027778; gx=np.arange(W,E+res,res); gy=np.arange(Nn,S-res,-res); GX,GY=np.meshgrid(gx,gy); EXT=[gx[0],gx[-1],gy[-1],gy[0]]
tr=from_origin(gx[0]-res/2,gy[0]+res/2,res,res)
# 물 마스크
demg=np.full(GX.shape,np.nan,np.float32); dd=rasterio.open(DEM)
reproject(dd.read(1).astype('float32'),demg,src_transform=dd.transform,src_crs=dd.crs,dst_transform=tr,dst_crs='EPSG:4326',resampling=Resampling.bilinear)
WATER=~(np.isfinite(demg)&(demg>1.0))
def mls(x): n=(x.shape[0]//AY)*AY; mm=(x.shape[1]//AX)*AX; return x[:n,:mm].reshape(n//AY,AY,mm//AX,AX).sum(axis=(1,3))
def mlc(x): n=(x.shape[0]//AY)*AY; mm=(x.shape[1]//AX)*AX; return x[:n,:mm].reshape(n//AY,AY,mm//AX,AX).mean(axis=(1,3))
def win(m):
    LA,LO=np.meshgrid(np.linspace(S,Nn,6),np.linspace(W,E,6)); T=N.geo2ecef(LA.ravel(),LO.ravel(),np.full(LA.size,15.))
    tm,Rm=N.geo2rdr(m,T,t_guess=m.line_to_t(m.nlines//2)); mln=m.t_to_line(tm); mcl=m.r_to_col(Rm); mar=150
    L0=max(0,int(mln.min())-mar);L1=min(m.nlines,int(mln.max())+mar);C0=max(0,int(mcl.min())-mar);C1=min(m.ncols,int(mcl.max())+mar)
    return L0,L1,C0,C1
def geom(m,L0,L1,C0,C1):
    SG=8; si=np.arange(L0,L1,SG); sj=np.arange(C0,C1,SG); GI,GJ=np.meshgrid(si,sj,indexing='ij')
    Tg,LAT,LON,_=N.rdr2geo_dem(m,m.line_to_t(GI),m.col_to_r(GJ),dem,h0=float(np.nanmedian(dem.arr)),n_iter=4)
    return Tg,GI,GJ,LAT,LON,SG

def amp_geo(key):
    m=N.Scene(P[key]); N.calibrate_side(m,36.41,126.38); L0,L1,C0,C1=win(m); NL,NC=L1-L0,C1-C0
    cx,_=m.read_slc(L0,L1,C0,C1); amp=np.abs(cx).astype(np.float32)
    Tg,GI,GJ,LAT,LON,SG=geom(m,L0,L1,C0,C1)
    A=np.sqrt(mlc(amp**2)); H,Wd=A.shape
    ry,rx=np.meshgrid(np.arange(H),np.arange(Wd),indexing='ij')
    oy=(ry*AY+AY/2)/SG; ox=(rx*AX+AX/2)/SG
    la=map_coordinates(LAT,[oy.ravel(),ox.ravel()],order=1,mode='nearest'); lo=map_coordinates(LON,[oy.ravel(),ox.ravel()],order=1,mode='nearest')
    v=np.isfinite(la)&(A.ravel()>0); G=griddata(np.c_[lo[v],la[v]],A.ravel()[v],(GX,GY),method='linear'); G[WATER]=np.nan
    log("amp %s done"%key); return G

def coh_geo(mk,sk):
    m=N.Scene(P[mk]); s=N.Scene(P[sk]); N.calibrate_side(m,36.41,126.38); N.calibrate_side(s,36.41,126.38)
    L0,L1,C0,C1=win(m); NL,NC=L1-L0,C1-C0; lam=m.wavelength
    mas,_=m.read_slc(L0,L1,C0,C1); Tg,GI,GJ,LAT,LON,SG=geom(m,L0,L1,C0,C1)
    ts,Rs=N.geo2rdr(s,Tg,t_guess=s.line_to_t(s.nlines//2))
    up=lambda a: zoom(a.astype(np.float64),(NL/a.shape[0],NC/a.shape[1]),order=1)
    LINEs=up(s.t_to_line(ts)); COLs=up(s.r_to_col(Rs)); DR=up(m.col_to_r(GJ)-Rs).astype(np.float64)
    sl0=max(0,int(LINEs.min())-8);sl1=min(s.nlines,int(LINEs.max())+8);sc0=max(0,int(COLs.min())-8);sc1=min(s.ncols,int(COLs.max())+8)
    slv,_=s.read_slc(sl0,sl1,sc0,sc1); sre=spline_filter(slv.real.astype(np.float32),3); sim=spline_filter(slv.imag.astype(np.float32),3)
    re=map_coordinates(sre,[LINEs-sl0,COLs-sc0],order=3,mode='constant',cval=0,prefilter=False)
    im=map_coordinates(sim,[LINEs-sl0,COLs-sc0],order=3,mode='constant',cval=0,prefilter=False); sco=(re+1j*im).astype(np.complex64)
    phref=(4*np.pi/lam)*(DR-np.median(DR)); ifg=(mas*np.conj(sco)*np.exp(1j*phref)).astype(np.complex64)
    coh=np.abs(mls(ifg))/(np.sqrt(mls(np.abs(mas)**2)*mls(np.abs(sco)**2))+1e-9); H,Wd=coh.shape
    ry,rx=np.meshgrid(np.arange(H),np.arange(Wd),indexing='ij'); oy=(ry*AY+AY/2)/SG; ox=(rx*AX+AX/2)/SG
    la=map_coordinates(LAT,[oy.ravel(),ox.ravel()],order=1,mode='nearest'); lo=map_coordinates(LON,[oy.ravel(),ox.ravel()],order=1,mode='nearest')
    amv=np.sqrt(mlc(np.abs(mas)**2)).ravel(); v=np.isfinite(la)&(amv>0)
    G=griddata(np.c_[lo[v],la[v]],coh.ravel()[v],(GX,GY),method='linear'); G[WATER]=np.nan
    log("coh %sx%s done mean=%.3f"%(mk,sk,np.nanmean(G))); return G

# --- 산출 ---
A11=amp_geo("0511"); A14=amp_geo("0614"); A07=amp_geo("0706")
C_early=coh_geo("0511","0515"); C_late=coh_geo("0614","0706")
def wtif(nm,arr,dt='float32'):
    with rasterio.open(OUT+nm,'w',driver='GTiff',height=arr.shape[0],width=arr.shape[1],count=1,dtype=dt,crs='EPSG:4326',transform=tr,nodata=np.nan,compress='deflate') as d: d.write(arr.astype(dt),1)
wtif("coh_early_0511x0515.tif",C_early); wtif("coh_late_0614x0706.tif",C_late); wtif("coh_diff_late_minus_early.tif",C_late-C_early)
def norm(a):
    lo,hi=np.nanpercentile(a,2),np.nanpercentile(a,98); return np.clip((a-lo)/(hi-lo+1e-9),0,1)
RGB=np.dstack([norm(A11),norm(A14),norm(A07)]); RGB[np.repeat(WATER[:,:,None],3,axis=2)]=0
ampdiff=norm(A07)-norm(A11); ampdiff[WATER]=np.nan
wtif("amp_0511.tif",A11); wtif("amp_0614.tif",A14); wtif("amp_0706.tif",A07); wtif("amp_diff_0706_minus_0511.tif",ampdiff)
log("tifs saved")

# --- 그림 ---
fig,ax=plt.subplots(2,3,figsize=(19,11))
ax[0,0].imshow(RGB,extent=EXT); ax[0,0].set_title("Amplitude multitemporal RGB\nR=0511 G=0614 B=0706 (color=형태이동)")
im=ax[0,1].imshow(ampdiff,cmap='RdBu_r',vmin=-0.5,vmax=0.5,extent=EXT); ax[0,1].set_title("Amplitude change 0706 - 0511 (normalized)"); plt.colorbar(im,ax=ax[0,1],fraction=.046)
ax[0,2].axis('off'); ax[0,2].text(0.5,0.5,"코히런스 변화탐지\n(아래 행)\n\n활성모래=저코히런스\n활성역 패턴 변화\n= 사구활동 정황\n\n주의: 모래는 이동무관 0\n→ '이동증명' 아님",ha='center',va='center',fontsize=11)
im=ax[1,0].imshow(C_early,cmap='viridis',vmin=0,vmax=0.6,extent=EXT); ax[1,0].set_title("Coherence EARLY 0511x0515 (4d)  mean %.2f"%np.nanmean(C_early)); plt.colorbar(im,ax=ax[1,0],fraction=.046)
im=ax[1,1].imshow(C_late,cmap='viridis',vmin=0,vmax=0.6,extent=EXT); ax[1,1].set_title("Coherence LATE 0614x0706 (22d)  mean %.2f"%np.nanmean(C_late)); plt.colorbar(im,ax=ax[1,1],fraction=.046)
im=ax[1,2].imshow(C_late-C_early,cmap='RdBu_r',vmin=-0.3,vmax=0.3,extent=EXT); ax[1,2].set_title("Coherence change (late - early)\n+높아짐(안정화) / -낮아짐(활성화)"); plt.colorbar(im,ax=ax[1,2],fraction=.046)
for a in ax.ravel():
    if a.has_data(): a.set_xlabel("lon"); a.set_ylabel("lat")
plt.suptitle("Taean dune — SAR coherence change + multitemporal amplitude (N2 A_L), water masked",fontsize=13)
plt.tight_layout(); plt.savefig(OUT+"CCD_overview.png",dpi=110); log("saved CCD_overview.png")
