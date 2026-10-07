"""개선 자작 파이프라인: 기하코레지 + 코히런스기반 방위/거리 정밀정합(ESD-lite)
   + 거리 flat/topo 제거 + 잔차 방위램프 제거 + Goldstein + snaphu 언랩 + 지오코딩.
   모드: s1ab(S1C 0519x0531), s1cd(S1C0531 x S1D0613), n2(N2 0515x0614)."""
import numpy as np, os, sys, subprocess, json, time
from scipy.ndimage import zoom, map_coordinates, spline_filter, uniform_filter
from scipy.interpolate import griddata
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import rasterio; from rasterio.transform import from_origin
import pyproj
import s1insar as S1, n2insar as N
t0=time.time(); OUT="/mnt/c/N2_InSAR/N2/taean_Insar/"; WK=OUT+"work/"
def log(*a): print("[%6.1fs]"%(time.time()-t0),*a,flush=True)
SNAPHU="$CONDA_PREFIX/bin/snaphu.conda_backup"
mode=sys.argv[1] if len(sys.argv)>1 else "s1ab"
Z="/mnt/c/N2_InSAR/sentinel1/"; DEM="/mnt/c/N2_InSAR/DEM/cop_dem_N36E126.tif"
S,Nn,W,E=36.3899,36.4350,126.3548,126.4107
dem=N.DemInterp(DEM)
if mode in ("s1ab","s1cd"):
    is_tops=True; AY,AX=3,12
    if mode=="s1ab":
        mz=Z+"S1C_IW_SLC__1SDV_20260519T214004_20260519T214028_007728_00FB4A_A82C.zip"; sz=Z+"S1C_IW_SLC__1SDV_20260531T214004_20260531T214029_007903_010126_2310.zip"; pref="s1cust_ab"; tag="S1C 0519x0531"
    else:
        mz=Z+"S1C_IW_SLC__1SDV_20260531T214004_20260531T214029_007903_010126_2310.zip"; sz=Z+"S1D_IW_SLC__1SDV_20260613T214015_20260613T214042_003223_0059FE_D74F.zip"; pref="s1cust_cd"; tag="S1C0531 x S1D0613"
    m=S1.S1Scene(mz,"iw1","vv",0); s=S1.S1Scene(sz,"iw1","vv",0)
    N.calibrate_side(m,36.41,126.38); N.calibrate_side(s,36.41,126.38)
    NLINES_m=m.lpb; NCOLS_m=m.ncols; slp=s.lpb
else:
    is_tops=False; AY,AX=20,12
    R="/mnt/c/N2_InSAR/N2/Taean_recent/"
    mz=R+"20260515/N2_SAR_20260515_063509K_16360_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260515_063509_ST_BB_VV_A_L_SSC_B_NP04.h5"
    sz=R+"20260614/N2_SAR_20260614_063801K_16812_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260614_063801_ST_BB_VV_A_L_SSC_B_NP04.h5"
    import h5py
    def cen(h5):
        with h5py.File(h5,'r') as f: c=np.array(f.attrs["Scene Center Geodetic Coordinates"],float); return float(c[0]),float(c[1])
    m=N.Scene(mz); s=N.Scene(sz); N.calibrate_side(m,*cen(mz)); N.calibrate_side(s,*cen(sz))
    NLINES_m=m.nlines; NCOLS_m=m.ncols; slp=s.nlines; pref="n2cust"; tag="N2 0515x0614"
lam=m.wavelength; log("mode=%s tops=%s lam=%.5f"%(mode,is_tops,lam))

def read(sc,l0,l1,c0,c1):
    if is_tops: cx,ret,_=sc.read_deramped(l0,l1,c0,c1); return cx,ret
    return sc.read_slc(l0,l1,c0,c1)

# master AOI 윈도우
LA,LO=np.meshgrid(np.linspace(S,Nn,6),np.linspace(W,E,6)); T=N.geo2ecef(LA.ravel(),LO.ravel(),np.full(LA.size,15.0))
tm,Rm=N.geo2rdr(m,T,t_guess=m.line_to_t(NLINES_m//2)); mln=m.t_to_line(tm); mcl=m.r_to_col(Rm)
mar=60 if is_tops else 100
L0=max(0,int(mln.min())-mar); L1=min(NLINES_m,int(mln.max())+mar); C0=max(0,int(mcl.min())-mar); C1=min(NCOLS_m,int(mcl.max())+mar); NL,NC=L1-L0,C1-C0
masf,_=read(m,L0,L1,C0,C1); log("master read %s L[%d:%d]C[%d:%d]"%(masf.shape,L0,L1,C0,C1))
SG=4 if is_tops else 5
sub_i=np.arange(L0,L1,SG); sub_j=np.arange(C0,C1,SG); GI,GJ=np.meshgrid(sub_i,sub_j,indexing='ij')
tmg=m.line_to_t(GI); Rmg=m.col_to_r(GJ)
Tg,LATg,LONg,HGTg=N.rdr2geo_dem(m,tmg,Rmg,dem,h0=float(np.nanmedian(dem.arr)),n_iter=4)
ts,Rs=N.geo2rdr(s,Tg,t_guess=s.line_to_t(slp//2))
def up(a): return zoom(a.astype(np.float64),(NL/a.shape[0],NC/a.shape[1]),order=1)
LINEs=up(s.t_to_line(ts)); COLs=up(s.r_to_col(Rs)); DR=up(Rmg-Rs).astype(np.float64)
LAT=up(LATg).astype(np.float32); LON=up(LONg).astype(np.float32); HGT=up(HGTg).astype(np.float32)
sl0=max(0,int(LINEs.min())-8); sl1=min(slp,int(LINEs.max())+8); sc0=max(0,int(COLs.min())-8); sc1=min(NCOLS_m,int(COLs.max())+8)
slvf,_=read(s,sl0,sl1,sc0,sc1)
sre=spline_filter(slvf.real.astype(np.float32),order=3); sim=spline_filter(slvf.imag.astype(np.float32),order=3)
def resamp(la,co):
    re=map_coordinates(sre,[la-sl0,co-sc0],order=3,mode='constant',cval=0,prefilter=False)
    im=map_coordinates(sim,[la-sl0,co-sc0],order=3,mode='constant',cval=0,prefilter=False)
    return (re+1j*im).astype(np.complex64)
def mls(x,ay=AY,ax=AX):
    n=(x.shape[0]//ay)*ay; mm=(x.shape[1]//ax)*ax; return x[:n,:mm].reshape(n//ay,ay,mm//ax,ax).sum(axis=(1,3))
def mlc(x,ay=AY,ax=AX):
    n=(x.shape[0]//ay)*ay; mm=(x.shape[1]//ax)*ax; return x[:n,:mm].reshape(n//ay,ay,mm//ax,ax).mean(axis=(1,3))
pw=None
def coh_of(dl,dc):
    global pw
    sc_=resamp(LINEs+dl,COLs+dc); r=masf*np.conj(sc_)
    if pw is None: pw=np.sqrt(mls(np.abs(masf)**2))+1e-9
    return float(np.nanmean(np.abs(mls(r))/(np.sqrt(mls(np.abs(masf)**2)*mls(np.abs(sc_)**2))+1e-9))), sc_
# --- ESD-lite: 코히런스 기반 방위/거리 정밀정합 ---
best=(-1,0,0)
for dl in np.arange(-2.0,2.01,0.5):
    for dc in np.arange(-2.0,2.01,0.5):
        v,_=coh_of(dl,dc)
        if v>best[0]: best=(v,dl,dc)
b2=best
for dl in np.arange(best[1]-0.4,best[1]+0.41,0.1):
    for dc in np.arange(best[2]-0.4,best[2]+0.41,0.1):
        v,_=coh_of(dl,dc)
        if v>b2[0]: b2=(v,dl,dc)
v,dl,dc=b2; c0geom,_=coh_of(0,0)
log("refine: best coh=%.3f at dl=%.2f dc=%.2f (geom-only coh=%.3f)"%(v,dl,dc,c0geom))
slv_co=resamp(LINEs+dl,COLs+dc)
raw=(masf*np.conj(slv_co)).astype(np.complex64)
# 거리 flat/topo 제거
phref=(4*np.pi/lam)*(DR-np.median(DR))
flat=(raw*np.exp(1j*phref)).astype(np.complex64); flat_ml=mls(flat)
# 잔차 2D 위상램프 제거(FFT peak; TOPS 방위램프 포함)
coh_raw=np.abs(mls(raw))/(np.sqrt(mls(np.abs(masf)**2)*mls(np.abs(slv_co)**2))+1e-9)
msk=coh_raw>max(np.nanpercentile(coh_raw,60),0.2); zz=flat_ml.copy(); zz[~msk]=0
F=np.fft.fftshift(np.abs(np.fft.fft2(zz))); py,px=np.unravel_index(np.argmax(F),F.shape)
fy=(py-zz.shape[0]//2)/zz.shape[0]; fx=(px-zz.shape[1]//2)/zz.shape[1]
yf,xf=np.meshgrid(np.arange(flat.shape[0]),np.arange(flat.shape[1]),indexing='ij')
dr_full=(flat*np.exp(-1j*2*np.pi*(fy*(yf/AY)+fx*(xf/AX)))).astype(np.complex64)
dr_ml=mls(dr_full)
coh=np.abs(mls(dr_full))/(np.sqrt(mls(np.abs(masf)**2)*mls(np.abs(slv_co)**2))+1e-9)
log("flat/topo+ramp(fx=%.4f fy=%.4f) removed; coh mean=%.3f"%(fx,fy,np.nanmean(coh)))
# Goldstein
def goldstein(cpx,alpha=0.5,bs=16):
    out=np.zeros_like(cpx);H,Wd=cpx.shape;st=bs//2;win=np.hanning(bs)[:,None]*np.hanning(bs)[None,:];ws=np.zeros((H,Wd))+1e-9
    for y in range(0,H-bs+1,st):
        for x in range(0,Wd-bs+1,st):
            b=cpx[y:y+bs,x:x+bs];Sp=np.fft.fft2(b);mag=uniform_filter(np.abs(Sp),3)
            out[y:y+bs,x:x+bs]+=np.fft.ifft2(Sp*(mag/(mag.max()+1e-9))**alpha)*win;ws[y:y+bs,x:x+bs]+=win
    return out/ws
filt=goldstein((dr_ml/(np.abs(dr_ml)+1e-9))*coh).astype(np.complex64)
# snaphu 언랩
wd=WK+f"snaphu_{pref}"; os.makedirs(wd,exist_ok=True); wid=filt.shape[1]
filt.astype(np.complex64).tofile(wd+"/ifg.cpx"); coh.astype(np.float32).tofile(wd+"/coh.cor")
open(wd+"/c.conf","w").write(f"INFILE {wd}/ifg.cpx\nLINELENGTH {wid}\nOUTFILE {wd}/unw.bin\nCORRFILE {wd}/coh.cor\nINFILEFORMAT COMPLEX_DATA\nCORRFILEFORMAT FLOAT_DATA\nOUTFILEFORMAT FLOAT_DATA\nSTATCOSTMODE SMOOTH\nINITMETHOD MCF\n")
rr=subprocess.run([SNAPHU,"-f",wd+"/c.conf"],capture_output=True,text=True)
unw=np.fromfile(wd+"/unw.bin",np.float32).reshape(filt.shape) if os.path.exists(wd+"/unw.bin") else np.full(filt.shape,np.nan)
log("snaphu rc=%d"%rr.returncode)
# 지오코딩(EPSG:4326 AOI)
lat_ml=mlc(LAT.astype(np.complex64)).real; lon_ml=mlc(LON.astype(np.complex64)).real; amp_ml=np.sqrt(mlc(np.abs(masf)**2)); hgt_ml=mlc(HGT.astype(np.complex64)).real
res=0.00027778; gx=np.arange(W,E+res,res); gy=np.arange(Nn,S-res,-res); GX,GY=np.meshgrid(gx,gy)
pts=np.c_[lon_ml.ravel(),lat_ml.ravel()]; vv=(amp_ml.ravel()>0)&np.isfinite(lon_ml.ravel())
def gc(a,mth='linear'): return griddata(pts[vv],a.ravel()[vv],(GX,GY),method=mth)
G_coh=gc(coh); G_unw=gc(unw); G_wr=gc(np.angle(dr_ml),'nearest'); G_amp=gc(amp_ml); G_hgt=gc(hgt_ml)
mk=~np.isfinite(G_amp)
for g in (G_coh,G_unw,G_wr,G_hgt): g[mk]=np.nan
tr=from_origin(gx[0]-res/2,gy[0]+res/2,res,res)
def wtif(nm,arr):
    with rasterio.open(OUT+nm,'w',driver='GTiff',height=arr.shape[0],width=arr.shape[1],count=1,dtype='float32',crs='EPSG:4326',transform=tr,nodata=np.nan,compress='deflate') as d: d.write(arr.astype('float32'),1)
wtif(pref+"_coherence.tif",G_coh); wtif(pref+"_unwrapped_phase.tif",G_unw); wtif(pref+"_wrapped_phase.tif",G_wr); wtif(pref+"_amplitude.tif",G_amp)
los=G_unw*lam/(4*np.pi)*100; wtif(pref+"_los_disp_cm.tif",los)
summ=dict(mode=mode,tag=tag,tops=is_tops,coh_mean=round(float(np.nanmean(G_coh)),3),coh_land=round(float(np.nanmean(G_coh[np.isfinite(G_coh)&(G_hgt>5)])),3),
          refine_dl=round(dl,2),refine_dc=round(dc,2),coh_geom=round(c0geom,3),ramp_fx_fy=[round(fx,4),round(fy,4)],AY_AX=[AY,AX])
# s1ab면 ISCE와 비교
if mode=="s1ab":
    def read_isce(f,band):
        from rasterio.warp import reproject, Resampling
        ds=rasterio.open(f); a=ds.read(band).astype('float32'); a[a==0]=np.nan
        out=np.full(G_coh.shape,np.nan,np.float32); reproject(a,out,src_transform=ds.transform,src_crs=ds.crs,dst_transform=tr,dst_crs='EPSG:4326',resampling=Resampling.bilinear,src_nodata=np.nan,dst_nodata=np.nan); return out
    Ic=read_isce(OUT+"isce2/merged/topophase.cor.geo",2); Iu=read_isce(OUT+"isce2/merged/filt_topophase.unw.geo",2)
    def corr(a,b):
        mm=np.isfinite(a)&np.isfinite(b);
        if mm.sum()<50: return np.nan
        aa=a[mm]-a[mm].mean(); bb=b[mm]-b[mm].mean(); return float((aa*bb).sum()/np.sqrt((aa*aa).sum()*(bb*bb).sum()))
    def dep(u):
        mm=np.isfinite(u); yy,xx=np.mgrid[0:u.shape[0],0:u.shape[1]]; A=np.c_[np.ones(mm.sum()),xx[mm],yy[mm]]; c,*_=np.linalg.lstsq(A,u[mm],rcond=None); return u-(c[0]+c[1]*xx+c[2]*yy)
    summ["isce_coh_mean"]=round(float(np.nanmean(Ic)),3); summ["coh_corr_vs_isce"]=round(corr(G_coh,Ic),3); summ["unw_corr_vs_isce"]=round(corr(dep(G_unw),dep(Iu)),3)
json.dump(summ,open(OUT+pref+"_summary.json","w"),indent=2); log("SUMMARY %s"%json.dumps(summ,ensure_ascii=False))
# overview
def na(a): l=np.log1p(np.nan_to_num(a)); v=l[np.isfinite(l)&(l>0)]; lo,hi=np.percentile(v,[2,98]); return np.clip((l-lo)/(hi-lo),0,1)
ext=[gx[0],gx[-1],gy[-1],gy[0]]
fig,ax=plt.subplots(2,3,figsize=(18,12))
ax[0,0].imshow(na(G_amp),cmap='gray',extent=ext); ax[0,0].set_title("Amplitude")
im=ax[0,1].imshow(G_coh,cmap='viridis',vmin=0,vmax=1,extent=ext); ax[0,1].set_title("Coherence %.2f (land %.2f)"%(summ['coh_mean'],summ['coh_land'])); plt.colorbar(im,ax=ax[0,1],fraction=.046)
ax[0,2].imshow(G_wr,cmap='hsv',extent=ext); ax[0,2].set_title("Wrapped (flat/topo+ramp removed)")
im=ax[1,0].imshow(G_unw,cmap='rainbow',extent=ext); ax[1,0].set_title("Unwrapped (rad)"); plt.colorbar(im,ax=ax[1,0],fraction=.046)
im=ax[1,1].imshow(G_hgt,cmap='terrain',extent=ext); ax[1,1].set_title("DEM"); plt.colorbar(im,ax=ax[1,1],fraction=.046)
cc=G_coh[np.isfinite(G_coh)]; ax[1,2].hist(cc,bins=40,color='#264653'); ax[1,2].set_title("Coh histogram (med %.2f)"%np.nanmedian(cc))
plt.suptitle("Improved custom pipeline (ESD-lite + ramp removal + snaphu) - %s | refine dl=%.2f dc=%.2f"%(tag,dl,dc),fontsize=12)
plt.tight_layout(rect=[0,0,1,0.96]); plt.savefig(OUT+pref+"_overview.png",dpi=92); log("saved %s_overview.png"%pref)
