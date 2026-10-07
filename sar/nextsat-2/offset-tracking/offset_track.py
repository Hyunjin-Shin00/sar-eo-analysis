"""진폭 오프셋 트래킹 (사구) — 모드 선택형 + 지상footprint 기준 사각 템플릿 + 방향 화살표.
   python offset_track.py <mode>   mode in {n2_0515x0614, n2_0511x0706, s1_0519x0613}
   * 템플릿/간격을 지상 미터(TMPL_M/STEP_M)로 지정 → 축별 픽셀크기로 환산(사구 크기에 맞춤).
   * 부호: +azimuth = 타깃이 +방위(비행)방향 이동, +range = 타깃이 먼거리(위성서 멀어짐)방향 이동. (합성검증으로 부호 보정)
   * range/azimuth 실제 지상방향(북기준 방위각) 계산해 화살표로 표기. 물(DEM<=1m) 마스킹.
   결과: C:\\N2_InSAR\\N2\\taean_OT."""
import numpy as np, time, sys, json
from scipy.ndimage import zoom, map_coordinates, spline_filter
from scipy.interpolate import griddata
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import rasterio; from rasterio.transform import from_origin; from rasterio.warp import reproject, Resampling
import n2insar as N, s1insar as S1
t0=time.time(); OUT="/mnt/c/N2_InSAR/N2/taean_OT/"
def log(*a): print("[%6.1fs]"%(time.time()-t0),*a,flush=True)
DEM="/mnt/c/N2_InSAR/DEM/cop_dem_N36E126.tif"; S,Nn,W,E=36.3899,36.4350,126.3548,126.4107
TMPL_M=100.0; STEP_M=50.0; SRCH_M=20.0        # 지상 템플릿/간격/최대잔차탐색 (m)
mode=sys.argv[1] if len(sys.argv)>1 else "n2_0515x0614"
R="/mnt/c/N2_InSAR/N2/Taean_recent/"; Z="/mnt/c/N2_InSAR/sentinel1/"
CFG={
 "n2_0515x0614":dict(sensor="n2",days=30,pref="n2off_0515x0614",ML=2,
   mz=R+"20260515/N2_SAR_20260515_063509K_16360_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260515_063509_ST_BB_VV_A_L_SSC_B_NP04.h5",
   sz=R+"20260614/N2_SAR_20260614_063801K_16812_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260614_063801_ST_BB_VV_A_L_SSC_B_NP04.h5"),
 "n2_0511x0706":dict(sensor="n2",days=56,pref="n2off_0511x0706",ML=2,
   mz=R+"20260511/N2_SAR_20260511_064011K_16300_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260511_064011_ST_BB_VV_A_L_SSC_B_NP04.h5",
   sz=R+"20260706/N2_SAR_20260706_064518K_17144_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260706_064518_ST_BB_VV_A_L_SSC_B_NP04.h5"),
 "n2_0511x0515":dict(sensor="n2",days=4,pref="n2off_0511x0515",ML=2,
   mz=R+"20260511/N2_SAR_20260511_064011K_16300_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260511_064011_ST_BB_VV_A_L_SSC_B_NP04.h5",
   sz=R+"20260515/N2_SAR_20260515_063509K_16360_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260515_063509_ST_BB_VV_A_L_SSC_B_NP04.h5"),
 "n2_0614x0706":dict(sensor="n2",days=22,pref="n2off_0614x0706",ML=2,
   mz=R+"20260614/N2_SAR_20260614_063801K_16812_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260614_063801_ST_BB_VV_A_L_SSC_B_NP04.h5",
   sz=R+"20260706/N2_SAR_20260706_064518K_17144_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260706_064518_ST_BB_VV_A_L_SSC_B_NP04.h5"),
 "n2_0402x0406":dict(sensor="n2",days=4,pref="n2off_0402x0406",ML=2,
   mz=R+"20260402/N2_SAR_20260402_065617K_15712_A_ST_B4_L00_RAW_B.NP04/Distribution/N2_SAR_20260402_065617_ST_BB_VV_A_R_SSC_B_NP04.h5",
   sz=R+"20260406/N2_SAR_20260406_065305K_15772_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260406_065305_ST_BB_VV_A_R_SSC_B_NP04.h5"),
 "n2_0518x0529":dict(sensor="n2",days=11,pref="n2off_0518x0529",ML=2,
   mz=R+"20260518/N2_SAR_20260518_065434K_16405_A_ST_B0_L00_RAW_B.NP04/Distribution/N2_SAR_20260518_065434_ST_BB_VV_A_R_SSC_B_NP04.h5",
   sz=R+"20260529/N2_SAR_20260529_070256K_16571_A_ST_B6_L00_RAW_B.NP04/Distribution/N2_SAR_20260529_070256_ST_BB_VV_A_R_SSC_B_NP04.h5"),
 "n2_0402x0613":dict(sensor="n2",days=72,pref="n2off_0402x0613",ML=2,
   mz=R+"20260402/N2_SAR_20260402_065617K_15712_A_ST_B4_L00_RAW_B.NP04/Distribution/N2_SAR_20260402_065617_ST_BB_VV_A_R_SSC_B_NP04.h5",
   sz=R+"20260613/N2_SAR_20260613_070258K_16797_A_ST_B4_L00_RAW_B.NP04/Distribution/N2_SAR_20260613_070258_ST_BB_VV_A_R_SSC_B_NP04.h5"),
 "s1_0519x0613":dict(sensor="s1",days=25,pref="s1off_0519x0613",ML=1,
   mz=Z+"S1C_IW_SLC__1SDV_20260519T214004_20260519T214028_007728_00FB4A_A82C.zip",
   sz=Z+"S1D_IW_SLC__1SDV_20260613T214015_20260613T214042_003223_0059FE_D74F.zip"),
}
c=CFG[mode]; ML=c["ML"]; pref=c["pref"]; dem=N.DemInterp(DEM)
if c["sensor"]=="n2": m=N.Scene(c["mz"]); s=N.Scene(c["sz"])
else: m=S1.S1Scene(c["mz"],"iw1","vv",0); s=S1.S1Scene(c["sz"],"iw1","vv",0)
N.calibrate_side(m,36.41,126.38); N.calibrate_side(s,36.41,126.38)
NLm,NCm,NLs=m.nlines,m.ncols,s.nlines
P,V=m.orbit(m.line_to_t(NLm//2)); az_pix=np.linalg.norm(V)*m.dt_az; rg_pix=m.dr

# --- 지상 footprint -> 축별 픽셀 템플릿(ml-px) ---
def px(mm,pixm): return max(16,int(round(mm/(pixm*ML))))
TAZ=px(TMPL_M,az_pix); TRG=px(TMPL_M,rg_pix)
STAZ=max(6,int(round(STEP_M/(az_pix*ML)))); STRG=max(6,int(round(STEP_M/(rg_pix*ML))))
MSHY=int(np.clip(round(SRCH_M/(az_pix*ML)),3,TAZ//2-2)); MSHX=int(np.clip(round(SRCH_M/(rg_pix*ML)),3,TRG//2-2))
log("%s az_pix=%.3f rg_pix=%.3f | template ml-px az=%d(%.0fm) rg=%d(%.0fm) step az=%d rg=%d search az=+-%d rg=+-%d"%(
    mode,az_pix,rg_pix,TAZ,TAZ*az_pix*ML,TRG,TRG*rg_pix*ML,STAZ,STRG,MSHY,MSHX))

# --- AOI window in master ---
LA,LO=np.meshgrid(np.linspace(S,Nn,6),np.linspace(W,E,6)); Tc=N.geo2ecef(LA.ravel(),LO.ravel(),np.full(LA.size,15.))
tm,Rm=N.geo2rdr(m,Tc,t_guess=m.line_to_t(NLm//2)); mln=m.t_to_line(tm); mcl=m.r_to_col(Rm)
mar=200 if c["sensor"]=="n2" else 60
L0=max(0,int(mln.min())-mar);L1=min(NLm,int(mln.max())+mar);C0=max(0,int(mcl.min())-mar);C1=min(NCm,int(mcl.max())+mar);NL,NC=L1-L0,C1-C0
mas,_=m.read_slc(L0,L1,C0,C1); amp_m=np.abs(mas).astype(np.float32); log("master read (%dx%d)"%(NL,NC))

# --- range/azimuth 실제 지상방향(북기준 방위각, 시계방향) at AOI 중심 ---
latc,lonc=0.5*(S+Nn),0.5*(W+E); Tc0=N.geo2ecef(np.array([latc]),np.array([lonc]),np.array([15.]))
tc0,Rc0=N.geo2rdr(m,Tc0,t_guess=m.line_to_t(NLm//2)); tc0=float(tc0); Rc0=float(Rc0)
def ll(t,Rr): T=N.rdr2geo(m,np.array([t]),np.array([Rr]),0.0); la,lo,_=N.ecef2geo(T); return float(la),float(lo)
la0,lo0=ll(tc0,Rc0); laR,loR=ll(tc0,Rc0+50.0); laA,loA=ll(tc0+50*m.dt_az,Rc0)   # +range 50m, +azimuth 50 lines
def bearing(la1,lo1):
    dN=(la1-la0)*111320.0; dE=(lo1-lo0)*111320.0*np.cos(np.radians(la0)); return np.degrees(np.arctan2(dE,dN))%360.0
TH_RG=bearing(laR,loR); TH_AZ=bearing(laA,loA)
log("bearings from North: +Azimuth=%.1f deg  +Range=%.1f deg"%(TH_AZ,TH_RG))

# --- 기하 코레지 ---
SG=8 if c["sensor"]=="n2" else 4; si=np.arange(L0,L1,SG); sj=np.arange(C0,C1,SG); GI,GJ=np.meshgrid(si,sj,indexing='ij')
Tg,LATg,LONg,HGTg=N.rdr2geo_dem(m,m.line_to_t(GI),m.col_to_r(GJ),dem,h0=float(np.nanmedian(dem.arr)),n_iter=4)
ts,Rs=N.geo2rdr(s,Tg,t_guess=s.line_to_t(NLs//2))
up=lambda a: zoom(a.astype(np.float64),(NL/a.shape[0],NC/a.shape[1]),order=1)
LINEs=up(s.t_to_line(ts)); COLs=up(s.r_to_col(Rs)); log("geom mapping done")
sl0=max(0,int(LINEs.min())-8);sl1=min(NLs,int(LINEs.max())+8);sc0=max(0,int(COLs.min())-8);sc1=min(NCm,int(COLs.max())+8)
slv,_=s.read_slc(sl0,sl1,sc0,sc1)
sre=spline_filter(slv.real.astype(np.float32),3); sim=spline_filter(slv.imag.astype(np.float32),3)
re=map_coordinates(sre,[LINEs-sl0,COLs-sc0],order=3,mode='constant',cval=0,prefilter=False)
im=map_coordinates(sim,[LINEs-sl0,COLs-sc0],order=3,mode='constant',cval=0,prefilter=False)
amp_s=np.abs(re+1j*im).astype(np.float32); log("secondary coregistered")

def mlamp(a):
    if ML==1: return a
    n=(a.shape[0]//ML)*ML; mm=(a.shape[1]//ML)*ML
    return a[:n,:mm].reshape(n//ML,ML,mm//ML,ML).mean(axis=(1,3))
Am=mlamp(amp_m); As=mlamp(amp_s); H,Wd=Am.shape
def geo_at(ry,rx):
    oy=ry*ML+ML/2; ox=rx*ML+ML/2; gy=oy/SG; gx=ox/SG
    la=map_coordinates(LATg,[gy,gx],order=1,mode='nearest'); lo=map_coordinates(LONg,[gy,gx],order=1,mode='nearest'); return la,lo

# --- 사각 NCC ---
def ncc(a,b):
    A=a-a.mean(); B=b-b.mean(); den=np.sqrt((A*A).sum()*(B*B).sum())+1e-9
    cc=np.fft.fftshift(np.fft.ifft2(np.fft.fft2(A)*np.conj(np.fft.fft2(B))).real)/den
    hy,hx=a.shape; cy,cx=hy//2,hx//2
    sub=cc[cy-MSHY:cy+MSHY+1,cx-MSHX:cx+MSHX+1]; p=np.unravel_index(np.argmax(sub),sub.shape); py,px=p[0]+cy-MSHY,p[1]+cx-MSHX
    if py<=0 or py>=hy-1 or px<=0 or px>=hx-1: return None
    cyv=cc[py-1,px],cc[py,px],cc[py+1,px]; cxv=cc[py,px-1],cc[py,px],cc[py,px+1]
    dy=0.5*(cyv[0]-cyv[2])/(cyv[0]-2*cyv[1]+cyv[2]+1e-9); dx=0.5*(cxv[0]-cxv[2])/(cxv[0]-2*cxv[1]+cxv[2]+1e-9)
    return (py-cy)+dy,(px-cx)+dx,cc[py,px]

ys=np.arange(0,H-TAZ,STAZ); xs=np.arange(0,Wd-TRG,STRG)
DAZ=np.full((len(ys),len(xs)),np.nan); DRG=np.full_like(DAZ,np.nan); CC=np.full_like(DAZ,np.nan); RY=np.zeros_like(DAZ); RX=np.zeros_like(DAZ)
for iy,y in enumerate(ys):
    for ix,x in enumerate(xs):
        RY[iy,ix]=y+TAZ/2; RX[iy,ix]=x+TRG/2; a=Am[y:y+TAZ,x:x+TRG]; b=As[y:y+TAZ,x:x+TRG]
        if a.mean()<=0 or b.mean()<=0: continue
        r=ncc(a,b)
        if r is not None: DAZ[iy,ix],DRG[iy,ix],CC[iy,ix]=r
log("NCC grid %dx%d valid=%d"%(DAZ.shape[0],DAZ.shape[1],np.isfinite(DAZ).sum()))

# 부호 보정: ncc = -(특징 이동) → 타깃 변위 = -ncc
CCTH=np.nanpercentile(CC,60); good=np.isfinite(DAZ)&(CC>=max(CCTH,0.08))
def deramp(F):
    m2=good&np.isfinite(F); yy,xx=np.mgrid[0:F.shape[0],0:F.shape[1]]
    A=np.c_[np.ones(m2.sum()),xx[m2],yy[m2]]; cc2,*_=np.linalg.lstsq(A,F[m2],rcond=None); return F-(cc2[0]+cc2[1]*xx+cc2[2]*yy)
az_m=deramp(-DAZ)*ML*az_pix; rg_m=deramp(-DRG)*ML*rg_pix        # + = 타깃 +방위/+거리 이동
for F in (az_m,rg_m): F[~good]=np.nan
la_c,lo_c=geo_at(RY,RX)
log("az 1sig=%.2fm rg 1sig=%.2fm CCth=%.3f CCmedian=%.3f"%(np.nanstd(az_m),np.nanstd(rg_m),max(CCTH,0.08),np.nanmedian(CC)))

# --- 지오코딩 + 물 마스크 ---
res=0.00027778; gx=np.arange(W,E+res,res); gy=np.arange(Nn,S-res,-res); GX,GY=np.meshgrid(gx,gy)
pts=np.c_[lo_c.ravel(),la_c.ravel()]; vv=good.ravel()&np.isfinite(lo_c.ravel())
def gc(F): return griddata(pts[vv],F.ravel()[vv],(GX,GY),method='linear')
G_az=gc(az_m); G_rg=gc(rg_m); G_cc=gc(np.where(good,CC,np.nan))
demg=np.full(GX.shape,np.nan,np.float32); dd=rasterio.open(DEM)
reproject(dd.read(1).astype('float32'),demg,src_transform=dd.transform,src_crs=dd.crs,dst_transform=from_origin(gx[0]-res/2,gy[0]+res/2,res,res),dst_crs='EPSG:4326',resampling=Resampling.bilinear)
water=~(np.isfinite(demg)&(demg>1.0))
for G in (G_az,G_rg,G_cc): G[water]=np.nan
tr=from_origin(gx[0]-res/2,gy[0]+res/2,res,res)
def wtif(nm,arr):
    with rasterio.open(OUT+nm,'w',driver='GTiff',height=arr.shape[0],width=arr.shape[1],count=1,dtype='float32',crs='EPSG:4326',transform=tr,nodata=np.nan,compress='deflate') as d: d.write(arr.astype('float32'),1)
wtif(pref+"_azimuth_m.tif",G_az); wtif(pref+"_range_m.tif",G_rg); wtif(pref+"_correlation.tif",G_cc); log("tifs saved")

# --- 미리보기 + 방향 화살표 ---
ext=[gx[0],gx[-1],gy[-1],gy[0]]; la=max(np.nanpercentile(np.abs(G_az),95),1e-3); lr=max(np.nanpercentile(np.abs(G_rg),95),1e-3)
def compass(ax):
    x0=gx[0]+0.13*(gx[-1]-gx[0]); y0=gy[-1]+0.17*(gy[0]-gy[-1]); L=0.011
    for th,lab,col in [(TH_AZ,"+Az %.0f°"%TH_AZ,'k'),(TH_RG,"+Rg %.0f°"%TH_RG,'b'),(0.0,"N",'0.4')]:
        dx=L*np.sin(np.radians(th)); dy=L*np.cos(np.radians(th))
        ax.annotate("",xy=(x0+dx,y0+dy),xytext=(x0,y0),arrowprops=dict(arrowstyle='-|>',color=col,lw=2.2))
        ax.text(x0+1.35*dx,y0+1.35*dy,lab,color=col,fontsize=8,ha='center',va='center',fontweight='bold')
fig,ax=plt.subplots(1,3,figsize=(19,5.5))
im=ax[0].imshow(G_az,cmap='RdBu_r',vmin=-la,vmax=la,extent=ext); ax[0].set_title("Azimuth offset (m)  1sig=%.2fm"%np.nanstd(G_az)); plt.colorbar(im,ax=ax[0],fraction=.046)
im=ax[1].imshow(G_rg,cmap='RdBu_r',vmin=-lr,vmax=lr,extent=ext); ax[1].set_title("Range(slant) offset (m)  1sig=%.2fm"%np.nanstd(G_rg)); plt.colorbar(im,ax=ax[1],fraction=.046)
im=ax[2].imshow(G_cc,cmap='viridis',vmin=0,vmax=max(0.3,np.nanpercentile(G_cc,95)),extent=ext); ax[2].set_title("NCC peak (median %.3f, keep>=%.2f)"%(np.nanmedian(CC),max(CCTH,0.08))); plt.colorbar(im,ax=ax[2],fraction=.046)
for a in ax: compass(a); a.set_xlabel("lon"); a.set_ylabel("lat")
plt.suptitle("Amplitude offset tracking — %s (%d-day) | template %.0fm step %.0fm | +Az=%.0f° +Rg=%.0f° (from N, +=target moves that way) | water masked"%(
    mode,c["days"],TMPL_M,STEP_M,TH_AZ,TH_RG),fontsize=11)
plt.tight_layout(); plt.savefig(OUT+pref+"_overview.png",dpi=110); log("saved %s_overview.png"%pref)
json.dump(dict(mode=mode,pair=pref,days=c["days"],sensor=c["sensor"],az_pix=round(az_pix,3),rg_pix=round(rg_pix,3),ML=ML,
  template_m=TMPL_M,step_m=STEP_M,TAZ_TRG_mlpx=[TAZ,TRG],step_mlpx=[STAZ,STRG],search_mlpx=[MSHY,MSHX],
  bearing_az_deg=round(float(TH_AZ),1),bearing_rg_deg=round(float(TH_RG),1),
  az_1sigma_m=round(float(np.nanstd(G_az)),2),rg_1sigma_m=round(float(np.nanstd(G_rg)),2),ncc_median=round(float(np.nanmedian(CC)),3),
  ncc_keep_threshold=round(float(max(CCTH,0.08)),3),valid_patches=int(np.isfinite(DAZ).sum()),land_valid=int(np.isfinite(G_az).sum())),
  open(OUT+pref+"_summary.json","w"),indent=2)
log("SUMMARY az1sig=%.2f rg1sig=%.2f nccmed=%.3f AZ=%.1f RG=%.1f"%(np.nanstd(G_az),np.nanstd(G_rg),np.nanmedian(CC),TH_AZ,TH_RG))
