"""N2 ACD 진폭 로그비 0515->0614 (InSAR/OT와 동일 쌍). SSC 진폭, 동일 멀티룩·지오코딩."""
import numpy as np, rasterio
from scipy.ndimage import map_coordinates
from scipy.interpolate import griddata
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
import n2insar as N
R="/mnt/c/N2_InSAR/N2/Taean_recent/"; CCD="/mnt/c/N2_InSAR/Result/taean_CCD/"; DEM="/mnt/c/N2_InSAR/DEM/cop_dem_N36E126.tif"
S,Nn,W,E=36.3899,36.4350,126.3548,126.4107; AY,AX=10,12; dem=N.DemInterp(DEM)
P={"0515":R+"20260515/N2_SAR_20260515_063509K_16360_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260515_063509_ST_BB_VV_A_L_SSC_B_NP04.h5",
   "0614":R+"20260614/N2_SAR_20260614_063801K_16812_A_ST_B5_L00_RAW_B.NP04/Distribution/N2_SAR_20260614_063801_ST_BB_VV_A_L_SSC_B_NP04.h5"}
res=0.00027778; gx=np.arange(W,E+res,res); gy=np.arange(Nn,S-res,-res); GX,GY=np.meshgrid(gx,gy); tr=from_origin(gx[0]-res/2,gy[0]+res/2,res,res)
demg=np.full(GX.shape,np.nan,"float32"); dd=rasterio.open(DEM)
reproject(dd.read(1).astype("float32"),demg,src_transform=dd.transform,src_crs=dd.crs,dst_transform=tr,dst_crs="EPSG:4326",resampling=Resampling.bilinear)
WATER=~(np.isfinite(demg)&(demg>1.0))
def mlc(x): n=(x.shape[0]//AY)*AY; mm=(x.shape[1]//AX)*AX; return x[:n,:mm].reshape(n//AY,AY,mm//AX,AX).mean(axis=(1,3))
def win(m):
    LA,LO=np.meshgrid(np.linspace(S,Nn,6),np.linspace(W,E,6)); T=N.geo2ecef(LA.ravel(),LO.ravel(),np.full(LA.size,15.))
    tm,Rm=N.geo2rdr(m,T,t_guess=m.line_to_t(m.nlines//2)); mln=m.t_to_line(tm); mcl=m.r_to_col(Rm); mar=150
    return (max(0,int(mln.min())-mar),min(m.nlines,int(mln.max())+mar),max(0,int(mcl.min())-mar),min(m.ncols,int(mcl.max())+mar))
def amp_geo(key):
    m=N.Scene(P[key]); N.calibrate_side(m,36.41,126.38); L0,L1,C0,C1=win(m)
    cx,_=m.read_slc(L0,L1,C0,C1); amp=np.abs(cx).astype(np.float32)
    SG=8; si=np.arange(L0,L1,SG); sj=np.arange(C0,C1,SG); GI,GJ=np.meshgrid(si,sj,indexing="ij")
    Tg,LAT,LON,_=N.rdr2geo_dem(m,m.line_to_t(GI),m.col_to_r(GJ),dem,h0=float(np.nanmedian(dem.arr)),n_iter=4)
    A=np.sqrt(mlc(amp**2)); H,Wd=A.shape
    ry,rx=np.meshgrid(np.arange(H),np.arange(Wd),indexing="ij"); oy=(ry*AY+AY/2)/SG; ox=(rx*AX+AX/2)/SG
    la=map_coordinates(LAT,[oy.ravel(),ox.ravel()],order=1,mode="nearest"); lo=map_coordinates(LON,[oy.ravel(),ox.ravel()],order=1,mode="nearest")
    v=np.isfinite(la)&(A.ravel()>0); G=griddata(np.c_[lo[v],la[v]],A.ravel()[v],(GX,GY),method="linear"); G[WATER]=np.nan
    print("amp",key,"done"); return G
A15=amp_geo("0515"); A14=amp_geo("0614")
land=np.isfinite(A15)&np.isfinite(A14)&(A15>0)&(A14>0)
LR=np.full(A15.shape,np.nan,"float32"); LR[land]=20*np.log10(A14[land]/A15[land])
with rasterio.open(CCD+"N2_AL_20260515_20260614_logratio_dB.tif","w",driver="GTiff",height=LR.shape[0],width=LR.shape[1],count=1,dtype="float32",crs="EPSG:4326",transform=tr,nodata=np.nan,compress="deflate") as d: d.write(LR,1)
v=LR[np.isfinite(LR)]; print("saved N2_AL_20260515_20260614_logratio_dB.tif  mean %.2f std %.2f dB"%(v.mean(),v.std()))
