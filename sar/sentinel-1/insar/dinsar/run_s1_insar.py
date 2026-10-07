"""Sentinel-1 IW(TOPS) InSAR — 0531(S1C)x0613(S1D), iw1 burst0, 남부 태안 AOI.
   n2insar 흐름 그대로(기하 코레지+지형위상제거+멀티룩+코히런스+지오코딩), TOPS 디램프만 추가.
   목적: 동일 코드가 좋은 데이터(C-band, B⊥~15m)에서 높은 코히런스를 내는지 검증."""
import numpy as np, json, time
from scipy.ndimage import zoom, map_coordinates, spline_filter
from scipy.interpolate import griddata
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import rasterio; from rasterio.transform import from_origin
import pyproj
import s1insar as S1, n2insar as N
t0=time.time(); OUT="/mnt/c/N2_InSAR/N2/taean_Insar/"
def log(*a): print("[%6.1fs]"%(time.time()-t0),*a,flush=True)
Z="/mnt/c/N2_InSAR/sentinel1/"
MAS=Z+"S1C_IW_SLC__1SDV_20260531T214004_20260531T214029_007903_010126_2310.zip"
SLV=Z+"S1D_IW_SLC__1SDV_20260613T214015_20260613T214042_003223_0059FE_D74F.zip"
DEM="/mnt/c/N2_InSAR/DEM/cop_dem_N36E126.tif"
S,Nn,W,E=36.3899,36.4350,126.3548,126.4107
AY,AX=3,12   # 멀티룩 ~ az42m, rg ground~50m

dem=N.DemInterp(DEM)
m=S1.S1Scene(MAS,"iw1","vv",burst=0); s=S1.S1Scene(SLV,"iw1","vv",burst=0)
N.calibrate_side(m,36.41,126.38); N.calibrate_side(s,36.41,126.38)
lam=m.wavelength; log("scenes ready lam=%.5f side=%d/%d"%(lam,m._side,s._side))

# master AOI 윈도우
LA,LO=np.meshgrid(np.linspace(S,Nn,6),np.linspace(W,E,6))
T=N.geo2ecef(LA.ravel(),LO.ravel(),np.full(LA.size,15.0))
tm,Rm=N.geo2rdr(m,T,t_guess=m.line_to_t(m.lpb//2)); mln=m.t_to_line(tm); mcl=m.r_to_col(Rm)
mar=60
L0=max(0,int(mln.min())-mar); L1=min(m.lpb,int(mln.max())+mar)
C0=max(0,int(mcl.min())-mar); C1=min(m.ncols,int(mcl.max())+mar); NL,NC=L1-L0,C1-C0
log("master AOI window L[%d:%d](%d) C[%d:%d](%d)"%(L0,L1,NL,C0,C1,NC))
masf,_,_=m.read_deramped(L0,L1,C0,C1); log("master deramped read %s"%(masf.shape,))

# 기하: master -> ground(DEM) -> slave burst0
SG=4; sub_i=np.arange(L0,L1,SG); sub_j=np.arange(C0,C1,SG); GI,GJ=np.meshgrid(sub_i,sub_j,indexing='ij')
tmg=m.line_to_t(GI); Rmg=m.col_to_r(GJ)
Tg,LATg,LONg,HGTg=N.rdr2geo_dem(m,tmg,Rmg,dem,h0=float(np.nanmedian(dem.arr)),n_iter=4)
ts,Rs=N.geo2rdr(s,Tg,t_guess=s.line_to_t(s.lpb//2))
LINEs_g=s.t_to_line(ts); COLs_g=s.r_to_col(Rs)
def up(a): return zoom(a.astype(np.float64),(NL/a.shape[0],NC/a.shape[1]),order=1)
LINEs=up(LINEs_g); COLs=up(COLs_g)
DR=up(Rmg-Rs).astype(np.float32); DR-=np.median(DR)
LAT=up(LATg).astype(np.float32); LON=up(LONg).astype(np.float32); HGT=up(HGTg).astype(np.float32)
log("geometry ready; slave line[%.0f,%.0f] col[%.0f,%.0f]"%(LINEs.min(),LINEs.max(),COLs.min(),COLs.max()))

# 슬레이브 버스트0 윈도우 읽기(디램프) + 리샘플
sl0=max(0,int(LINEs.min())-8); sl1=min(s.lpb,int(LINEs.max())+8)
sc0=max(0,int(COLs.min())-8); sc1=min(s.ncols,int(COLs.max())+8)
slvf,_,_=s.read_deramped(sl0,sl1,sc0,sc1)
sre=spline_filter(slvf.real.astype(np.float32),order=3); sim=spline_filter(slvf.imag.astype(np.float32),order=3)
def resamp(la,co):
    re=map_coordinates(sre,[la-sl0,co-sc0],order=3,mode='constant',cval=0,prefilter=False)
    im=map_coordinates(sim,[la-sl0,co-sc0],order=3,mode='constant',cval=0,prefilter=False)
    return (re+1j*im).astype(np.complex64)
slv_co=resamp(LINEs,COLs); log("slave resampled (deramped domain)")

# 간섭도/코히런스 (B⊥~15m → 지형/평지 위상 무시가능하나 φ_ref 제거)
def mls(x,ay=AY,ax=AX):
    n=(x.shape[0]//ay)*ay; mm=(x.shape[1]//ax)*ax
    return x[:n,:mm].reshape(n//ay,ay,mm//ax,ax).sum(axis=(1,3))
def mlc(x,ay=AY,ax=AX):
    n=(x.shape[0]//ay)*ay; mm=(x.shape[1]//ax)*ax
    return x[:n,:mm].reshape(n//ay,ay,mm//ax,ax).mean(axis=(1,3))
phref=(-4*np.pi/lam)*DR; raw=masf*np.conj(slv_co)
def rough(sgn):
    g=np.angle(mlc((raw*np.exp(1j*sgn*phref)).astype(np.complex64)))
    dv=np.angle(np.exp(1j*(g[:,1:]-g[:,:-1]))); dh=np.angle(np.exp(1j*(g[1:,:]-g[:-1,:])))
    return np.nanmean(dv**2)+np.nanmean(dh**2)
SGN=1 if rough(1)<rough(-1) else -1
diff=(raw*np.exp(1j*SGN*phref)).astype(np.complex64)
ifg_ml=mls(diff)
coh=np.abs(mls(raw))/(np.sqrt(mls(np.abs(masf)**2)*mls(np.abs(slv_co)**2))+1e-9)
amp_ml=np.sqrt(mlc(np.abs(masf)**2)); hgt_ml=mlc(HGT); lat_ml=mlc(LAT); lon_ml=mlc(LON)
def cohmean(a,b):
    n=(a.shape[0]//AY)*AY; mm=(a.shape[1]//AX)*AX
    return float(np.nanmean(np.abs(mls(a[:n,:mm]*np.conj(b[:n,:mm])))/(np.sqrt(mls(np.abs(a[:n,:mm])**2)*mls(np.abs(b[:n,:mm])**2))+1e-9)))
c0=cohmean(masf,slv_co); cf=cohmean(masf,resamp(LINEs+300,COLs))
log("sign=%+d coh mean=%.3f | EVIDENCE coh(reg)=%.3f vs coh(+300px)=%.3f"%(SGN,np.nanmean(coh),c0,cf))

# 지오코딩 (AOI UTM bbox, 30m)
tr=pyproj.Transformer.from_crs("EPSG:4326","EPSG:32652",always_xy=True)
aE,aN=tr.transform([W,W,E,E],[S,Nn,Nn,S]); res=30.0
gx=np.arange(min(aE),max(aE)+res,res); gy=np.arange(max(aN),min(aN)-res,-res); GX,GY=np.meshgrid(gx,gy)
Ex,Nx=tr.transform(lon_ml.ravel(),lat_ml.ravel()); valid=np.isfinite(Ex)&(amp_ml.ravel()>0)
pts=np.c_[Ex[valid],Nx[valid]]
def gc(v,method='linear'): return griddata(pts,v.ravel()[valid],(GX,GY),method=method)
G_amp=gc(amp_ml); G_coh=gc(coh); G_hgt=gc(hgt_ml); G_ph=gc(np.angle(ifg_ml),'nearest')
mask=~np.isfinite(G_amp)
for g in (G_amp,G_coh,G_hgt,G_ph): g[mask]=np.nan
transform=from_origin(gx[0]-res/2,gy[0]+res/2,res,res)
def wtif(nm,arr):
    with rasterio.open(OUT+nm,'w',driver='GTiff',height=arr.shape[0],width=arr.shape[1],count=1,dtype='float32',
                       crs='EPSG:32652',transform=transform,nodata=np.nan,compress='deflate') as d: d.write(arr.astype('float32'),1)
wtif("s1_insar_amplitude.tif",G_amp); wtif("s1_insar_coherence.tif",G_coh)
wtif("s1_insar_wrapped_phase.tif",G_ph); wtif("s1_insar_dem.tif",G_hgt)
# 육지 코히런스
land=np.isfinite(G_coh)&(G_hgt>5)&(G_amp>np.nanpercentile(G_amp[np.isfinite(G_amp)],40))
landcoh=float(np.nanmean(G_coh[land])) if land.sum()>0 else float('nan')
json.dump(dict(sensor="Sentinel-1 IW/TOPS",pair="20260531(S1C)-20260613(S1D)",swath="iw1 burst0 VV",
               dt_days=13,Bperp_m=15,wavelength_cm=round(lam*100,3),ml_looks_az_rg=[AY,AX],
               coh_mean=round(float(np.nanmean(coh)),3),coh_land=round(landcoh,3),
               coh_at_registration=round(c0,3),coh_at_300px_offset=round(cf,3),
               aoi_SNWE=[S,Nn,W,E],dem="GLO-30 cop_dem_N36E126 (local)",
               conclusion=("coherent" if c0-cf>0.15 else "low")),
          open(OUT+"s1_insar_summary.json","w"),indent=2)
log("land coherence=%.3f  wrote GeoTIFFs+summary"%landcoh)

# overview
def na(a): l=np.log1p(np.nan_to_num(a)); v=l[np.isfinite(l)&(l>0)]; lo,hi=np.percentile(v,[2,98]); return np.clip((l-lo)/(hi-lo),0,1)
ext=[gx[0]/1000,gx[-1]/1000,gy[-1]/1000,gy[0]/1000]
fig,ax=plt.subplots(2,3,figsize=(19,13))
ax[0,0].imshow(na(G_amp),cmap='gray',extent=ext); ax[0,0].set_title("Amplitude (S1 VV, AOI)")
im=ax[0,1].imshow(G_coh,cmap='viridis',vmin=0,vmax=1,extent=ext); ax[0,1].set_title("Coherence mean %.2f (land %.2f)"%(np.nanmean(G_coh),landcoh)); plt.colorbar(im,ax=ax[0,1],fraction=.046)
ax[0,2].imshow(G_ph,cmap='hsv',extent=ext); ax[0,2].set_title("Wrapped interferogram")
im2=ax[1,0].imshow(G_hgt,cmap='terrain',extent=ext); ax[1,0].set_title("DEM GLO-30"); plt.colorbar(im2,ax=ax[1,0],fraction=.046)
ax[1,1].bar(["reg","+300px"],[c0,cf],color=['#2a9d8f','#e76f51']); ax[1,1].set_ylim(0,1); ax[1,1].grid(axis='y',alpha=.3)
ax[1,1].set_title("coherence check\ncoh(reg)=%.3f vs coh(+300px)=%.3f"%(c0,cf))
cc=G_coh[np.isfinite(G_coh)]; ax[1,2].hist(cc,bins=50,color='#264653'); ax[1,2].set_title("Coherence histogram (median %.2f)"%np.nanmedian(cc))
for a in [ax[0,0],ax[0,1],ax[0,2],ax[1,0]]: a.set_xlabel("E km"); a.set_ylabel("N km")
plt.suptitle("Sentinel-1 IW InSAR (SAME code as N2) - Taean 2026-05-31 x 06-13, B⊥=15m, 13d, C-band | AOI 36.39-36.44N",fontsize=12)
plt.tight_layout(rect=[0,0,1,0.96]); plt.savefig(OUT+"s1_insar_overview.png",dpi=95); log("saved overview")
