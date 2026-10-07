#!/usr/bin/env python3
# Diagnose whether ERA5 tropo correction removed the topo-correlated velocity residual.
import os
ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')  # dir containing SBAS/ and sentinel1/
import numpy as np, h5py
MP=ROOT+'/SBAS/DSC/mintpy'; GEO=f'{MP}/geo'
gv=h5py.File(f'{GEO}/geo_velocity.h5','r'); v=gv['velocity'][:]*1000.0
a=gv.attrs; y0=float(a['Y_FIRST']);x0=float(a['X_FIRST']);dy=float(a['Y_STEP']);dx=float(a['X_STEP'])
tc=h5py.File(f'{GEO}/geo_temporalCoherence.h5','r')['temporalCoherence'][:]
hgt=h5py.File(f'{GEO}/geo_geometryRadar.h5','r')['height'][:].astype('float64')
ny,nx=v.shape
mlat=abs(dy)*111320.0; mlon=abs(dx)*111320.0*np.cos(np.deg2rad(y0))
gy,gx=np.gradient(hgt,mlat,mlon); slope=np.degrees(np.arctan(np.hypot(gy,gx)))
water=(slope<2.0)&(hgt<3330)
# reference pixel check
RLAT,RLON=38.2821,72.6066
rr=int(round((RLAT-y0)/dy)); cc=int(round((RLON-x0)/dx))
print("ref pixel (%.4f,%.4f) -> yx=%d,%d  v=%.2f mm/yr  tcoh=%.2f  hgt=%.0f"%(RLAT,RLON,rr,cc,v[rr,cc],tc[rr,cc],hgt[rr,cc]))
rel=np.isfinite(v)&(v!=0)&(tc>0.7)&(~water)
vv=v[rel]; hh=hgt[rel]
print("valid land px (tcoh>0.7): %d"%vv.size)
print("velocity  median=%.2f  mean=%.2f  p2=%.1f  p50=%.1f  p98=%.1f  min=%.1f max=%.1f"%(
    np.median(vv),np.mean(vv),np.percentile(vv,2),np.percentile(vv,50),np.percentile(vv,98),vv.min(),vv.max()))
# correlation & slope velocity~elevation
c=np.corrcoef(hh,vv)[0,1]; s,b=np.polyfit(hh,vv,1)
print("velocity~elevation:  corr=%.3f   slope=%.4f mm/yr/m   (prev height_corr: corr=-0.66 slope=-0.049)"%(c,s))
# fraction subsiding (< -2 mm/yr) after implicit ref
print("frac |v|<3: %.1f%%   frac v<-3: %.1f%%   frac v>3: %.1f%%"%(
    100*np.mean(np.abs(vv)<3),100*np.mean(vv<-3),100*np.mean(vv>3)))
