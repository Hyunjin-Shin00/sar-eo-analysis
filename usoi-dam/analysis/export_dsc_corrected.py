#!/usr/bin/env python3
# DSC LOS velocity with an EMPIRICAL stratified-tropo correction (remove the strong
# velocity~elevation trend that MintPy height_correlation under-corrected), re-referenced
# to stable rock (38.282375,72.607), water-masked, AOI-cropped. Outputs a p2/p98-stretched
# Leaflet overlay + QGIS GeoTIFF + a displacement time series at the point.
import os
ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')  # dir containing SBAS/ and sentinel1/
import numpy as np, h5py, json
from osgeo import gdal, osr
import matplotlib; matplotlib.use('Agg')
import matplotlib.cm as cm; from matplotlib.colors import TwoSlopeNorm
import matplotlib.pyplot as plt, datetime

MP=ROOT+'/SBAS/DSC/mintpy'; GEO=f'{MP}/geo'
OUT=ROOT+'/SBAS/DECOMP'
S,N,W,E = 38.1559, 38.3414, 72.5162, 72.7164
PLAT,PLON = 38.2574, 72.6091
REFLAT,REFLON = 38.282375, 72.607

gv=h5py.File(f'{GEO}/geo_velocity.h5','r'); v=gv['velocity'][:]*1000.0
a=gv.attrs; x0=float(a['X_FIRST']);y0=float(a['Y_FIRST']);dx=float(a['X_STEP']);dy=float(a['Y_STEP'])
tc=h5py.File(f'{GEO}/geo_temporalCoherence.h5','r')['temporalCoherence'][:]
hgt=h5py.File(f'{GEO}/geo_geometryRadar.h5','r')['height'][:].astype('float64')
ny,nx=v.shape
mlat=abs(dy)*111320.0; mlon=abs(dx)*111320.0*np.cos(np.deg2rad(y0))
gy,gx=np.gradient(hgt,mlat,mlon); slope=np.degrees(np.arctan(np.hypot(gy,gx)))
water=(slope<2.0)&(hgt<3330)

rel=np.isfinite(v)&(v!=0)&(tc>0.5)&(~water)
hh=hgt[rel]; vv=v[rel]; keep=np.ones(hh.size,bool)
for _ in range(3):
    a1,b1=np.polyfit(hh[keep],vv[keep],1); res=vv-(a1*hh+b1); keep=np.abs(res)<2*np.std(res[keep])
vc=v-a1*hgt
def rc(la,lo): return int(round((la-y0)/dy)),int(round((lo-x0)/dx))
rr,cc=rc(REFLAT,REFLON); vc=vc-vc[rr,cc]
print("topo slope removed: %.4f mm/yr/m"%a1)

def r_(lat): return int(round((lat-y0)/dy))
def c_(lon): return int(round((lon-x0)/dx))
r0,r1=max(0,r_(N)),min(ny,r_(S)); c0,c1=max(0,c_(W)),min(nx,c_(E))
sub=vc[r0:r1,c0:c1]; val=(np.isfinite(v)&(v!=0)&(tc>0.3)&(~water))[r0:r1,c0:c1]
sy0=y0+dy*r0; sx0=x0+dx*c0; sny,snx=sub.shape
Ncr,Scr,Wcr,Ecr=sy0,sy0+dy*sny,sx0,sx0+dx*snx
vs=sub[val]; p2,p98=float(np.percentile(vs,2)),float(np.percentile(vs,98))
VMAX=30  # deformation-scale display cap; residual non-linear tropo (SW ridge) saturates

rgba=cm.get_cmap('RdBu_r')(TwoSlopeNorm(vmin=-VMAX,vcenter=0,vmax=VMAX)(np.clip(sub,-VMAX,VMAX)))
rgba[...,3]=np.where(val,1.0,0.0)
plt.imsave(f'{OUT}/Usoi_DSC_corr_overlay.png',rgba)

# raw velocity field (float32, NaN=invalid, C-order) for JS-side live colormapping,
# plus a 256-entry RdBu_r LUT so the browser can restretch min/max interactively.
field=np.where(val,sub,np.nan).astype('<f4')
field.tofile(f'{OUT}/Usoi_DSC_corr_field.bin')
_lut=(cm.get_cmap('RdBu_r')(np.linspace(0,1,256))[:,:3]*255).round().astype(int).tolist()
vdmin=float(np.percentile(vs,1)); vdmax=float(np.percentile(vs,99))

ND=-9999.0; out=np.where(val,sub,ND).astype('float32')
ds=gdal.GetDriverByName('GTiff').Create(f'{OUT}/Usoi_DSC_LOS_corr_mm-yr.tif',snx,sny,1,gdal.GDT_Float32,options=['COMPRESS=DEFLATE','TILED=YES'])
ds.SetGeoTransform([sx0,dx,0,sy0,0,dy]); srs=osr.SpatialReference(); srs.ImportFromEPSG(4326); ds.SetProjection(srs.ExportToWkt())
b=ds.GetRasterBand(1); b.WriteArray(out); b.SetNoDataValue(ND); ds.FlushCache(); ds=None

import glob as _glob
_tscand=sorted(_glob.glob(f'{GEO}/geo_timeseries_*_ramp_demErr.h5'))
_tsf=[p for p in _tscand if 'ERA5' in p] or _tscand
print("timeseries file:",_tsf[-1].split('/')[-1])
tsf=h5py.File(_tsf[-1],'r')
dates=[d.decode() if isinstance(d,bytes) else str(d) for d in tsf['date'][:]]
r,c=r_(PLAT),c_(PLON)
disp=tsf['timeseries'][:,r,c]*1000.0; disp=disp-disp[0]
def yr(d): dt=datetime.datetime.strptime(d,'%Y%m%d'); return dt.year+(dt.timetuple().tm_yday-1)/365.25
t=np.array([yr(d) for d in dates]); A=np.vstack([t-t[0],np.ones_like(t)]).T
vel,ic=np.linalg.lstsq(A,disp,rcond=None)[0]; rmse=float(np.sqrt(np.mean((disp-(A@[vel,ic]))**2)))

meta=dict(bounds=[[Scr,Wcr],[Ncr,Ecr]], vmax=VMAX, p2=round(p2,1), p98=round(p98,1),
  point=[PLAT,PLON], ref=[REFLAT,REFLON], point_tcoh=round(float(tc[r,c]),2),
  fit_vel=round(float(vel),2), fit_rmse=round(rmse,2),
  n_land=int(val.sum()), pct=round(100*val.sum()/val.size,1),
  median=round(float(np.median(vs)),1), topo_slope=round(float(a1),4),
  snx=int(snx), sny=int(sny), lut=_lut,
  vdata_min=round(vdmin,1), vdata_max=round(vdmax,1),
  vmin_default=-VMAX, vmax_default=VMAX,
  ts=dict(date=dates, year=[round(float(x),4) for x in t], disp=[round(float(x),2) for x in disp]))
json.dump(meta,open(f'{OUT}/dsc_corr_meta.json','w'))
print("VMAX(p2/p98 sym)=%d  median=%.1f  n_land=%d  fit_vel=%.1f rmse=%.1f"%(VMAX,meta['median'],meta['n_land'],meta['fit_vel'],meta['fit_rmse']))
